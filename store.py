"""대화 기록과 파일 저장소.

배포 환경은 Supabase(DB + Storage)를 쓰고, 로컬 확인과 테스트는 메모리 저장소를 쓴다.
두 클래스는 같은 메서드를 가지므로 main.py는 어느 쪽인지 신경 쓰지 않는다.
"""

from datetime import datetime, timezone

import httpx


class MemoryStore:
    """서버를 끄면 사라지는 저장소. 로컬 확인과 테스트용."""

    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.files: dict[str, bytes] = {}

    async def add_message(self, message: dict) -> dict:
        saved = {
            **message,
            "id": len(self.messages) + 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.messages.append(saved)
        return saved

    async def recent_messages(self, room: str, limit: int = 200) -> list[dict]:
        return [m for m in self.messages if m["room"] == room][-limit:]

    async def messages_after(self, room: str, after_id: int) -> list[dict]:
        return [m for m in self.messages if m["room"] == room and m["id"] > after_id]

    async def get_message(self, message_id: int) -> dict | None:
        return next((m for m in self.messages if m["id"] == message_id), None)

    async def used_bytes(self) -> int:
        return sum(m.get("file_size") or 0 for m in self.messages)

    async def upload_file(self, path: str, data: bytes, content_type: str) -> None:
        self.files[path] = data

    async def download_file(
        self, path: str, byte_range: str | None = None
    ) -> tuple[int, bytes, dict]:
        return 200, self.files[path], {}

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


class SupabaseStore:
    """Supabase REST API로 messages 테이블과 비공개 버킷을 다룬다."""

    def __init__(self, url: str, key: str, bucket: str = "pigeon-files") -> None:
        self.bucket = bucket
        headers = {"apikey": key}
        # 예전 형식의 service_role 키(JWT)는 Authorization 헤더도 함께 보내야 한다.
        if key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {key}"
        self.client = httpx.AsyncClient(
            base_url=url.rstrip("/"), headers=headers, timeout=60
        )

    async def _select(self, params: dict) -> list[dict]:
        response = await self.client.get("/rest/v1/messages", params=params)
        response.raise_for_status()
        return response.json()

    async def add_message(self, message: dict) -> dict:
        response = await self.client.post(
            "/rest/v1/messages",
            json=message,
            headers={"Prefer": "return=representation"},
        )
        response.raise_for_status()
        return response.json()[0]

    async def recent_messages(self, room: str, limit: int = 200) -> list[dict]:
        rows = await self._select(
            {"room": f"eq.{room}", "order": "id.desc", "limit": limit}
        )
        return rows[::-1]

    async def messages_after(self, room: str, after_id: int) -> list[dict]:
        return await self._select(
            {"room": f"eq.{room}", "id": f"gt.{after_id}", "order": "id.asc", "limit": 200}
        )

    async def get_message(self, message_id: int) -> dict | None:
        rows = await self._select({"id": f"eq.{message_id}"})
        return rows[0] if rows else None

    async def used_bytes(self) -> int:
        rows = await self._select({"select": "file_size", "file_size": "not.is.null"})
        return sum(row["file_size"] for row in rows)

    async def upload_file(self, path: str, data: bytes, content_type: str) -> None:
        response = await self.client.post(
            f"/storage/v1/object/{self.bucket}/{path}",
            content=data,
            headers={"Content-Type": content_type},
        )
        response.raise_for_status()

    async def download_file(
        self, path: str, byte_range: str | None = None
    ) -> tuple[int, bytes, dict]:
        """파일 내용을 받아온다. 동영상 탐색을 위해 Range 요청을 그대로 전달한다."""
        headers = {"Range": byte_range} if byte_range else {}
        response = await self.client.get(
            f"/storage/v1/object/authenticated/{self.bucket}/{path}", headers=headers
        )
        if response.status_code not in (200, 206, 416):
            response.raise_for_status()
        passed = {
            name: response.headers[name]
            for name in ("content-range", "accept-ranges")
            if name in response.headers
        }
        return response.status_code, response.content, passed

    async def ping(self) -> None:
        """DB를 가볍게 한 번 조회해서 Supabase가 비활동으로 멈추지 않게 한다."""
        await self._select({"select": "id", "limit": 1})

    async def close(self) -> None:
        await self.client.aclose()
