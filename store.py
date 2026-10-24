"""대화 기록과 파일 저장소.

배포 환경은 Supabase(DB + Storage)를 쓰고, 로컬 확인과 테스트는 메모리 저장소를 쓴다.
두 클래스는 같은 메서드를 가지므로 main.py는 어느 쪽인지 신경 쓰지 않는다.

개인·단체방 한 개는 {"id", "name", "owner_id", "members": [{"uid", "name"}, ...]} 모양이다.
제재 한 개는 {"uid", "name", "kind": "kick" | "mute", "until": datetime} 모양이다.
"""

from datetime import datetime, timezone

import httpx


def _now() -> datetime:
    return datetime.now(timezone.utc)


# 구조: 두 저장소가 같은 메서드 이름을 가짐 / 이유: main.py가 구분할 필요 없고 테스트에 DB 불필요
class MemoryStore:
    """서버를 끄면 사라지는 저장소. 로컬 확인과 테스트용."""

    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.files: dict[str, bytes] = {}
        self.rooms: dict[str, dict] = {}
        self.sanctions: list[dict] = []
        self._next_id = 1

    async def add_message(self, message: dict) -> dict:
        saved = {
            **message,
            "id": self._next_id,
            "created_at": _now().isoformat(),
        }
        self._next_id += 1
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

    async def create_room(self, room: dict) -> None:
        self.rooms[room["id"]] = room

    async def get_room(self, room_id: str) -> dict | None:
        return self.rooms.get(room_id)

    async def list_rooms(self) -> list[dict]:
        return list(self.rooms.values())

    async def rename_room(self, room_id: str, name: str) -> None:
        self.rooms[room_id]["name"] = name

    async def delete_room(self, room_id: str) -> None:
        """파일을 먼저 지우고 방을 지운다. 중간에 실패해도 방이 남아 있으니 다시 지우면 된다."""
        for message in self.messages:
            if message["room"] == room_id and message.get("file_path"):
                self.files.pop(message["file_path"], None)
        self.messages = [m for m in self.messages if m["room"] != room_id]
        self.rooms.pop(room_id, None)

    async def add_sanction(self, sanction: dict) -> None:
        self.sanctions.append(sanction)

    async def active_sanctions(self) -> list[dict]:
        now = _now()
        return [s for s in self.sanctions if s["until"] > now]

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


class SupabaseStore:
    """Supabase REST API로 DB 테이블과 비공개 버킷을 다룬다."""

    def __init__(self, url: str, key: str, bucket: str = "pigeon-files") -> None:
        self.bucket = bucket
        headers = {"apikey": key}
        # 예전 형식의 service_role 키(JWT)는 Authorization 헤더도 함께 보내야 한다.
        if key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {key}"
        self.client = httpx.AsyncClient(
            base_url=url.rstrip("/"), headers=headers, timeout=60
        )

    async def _select(self, params: dict, table: str = "messages") -> list[dict]:
        response = await self.client.get(f"/rest/v1/{table}", params=params)
        response.raise_for_status()
        return response.json()

    async def _insert(self, table: str, rows: dict | list[dict]) -> None:
        response = await self.client.post(f"/rest/v1/{table}", json=rows)
        response.raise_for_status()

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

    @staticmethod
    def _room(row: dict) -> dict:
        members = row.pop("room_members")
        return {**row, "members": members}

    async def create_room(self, room: dict) -> None:
        await self._insert(
            "rooms", {"id": room["id"], "name": room["name"], "owner_id": room["owner_id"]}
        )
        await self._insert(
            "room_members",
            [{"room_id": room["id"], **member} for member in room["members"]],
        )

    async def get_room(self, room_id: str) -> dict | None:
        rows = await self._select(
            {"id": f"eq.{room_id}", "select": "*,room_members(uid,name)"}, "rooms"
        )
        return self._room(rows[0]) if rows else None

    async def list_rooms(self) -> list[dict]:
        rows = await self._select(
            {"select": "*,room_members(uid,name)", "order": "created_at.desc"}, "rooms"
        )
        return [self._room(row) for row in rows]

    async def rename_room(self, room_id: str, name: str) -> None:
        response = await self.client.patch(
            "/rest/v1/rooms", params={"id": f"eq.{room_id}"}, json={"name": name}
        )
        response.raise_for_status()

    # 구조: 파일→메시지→방 행 순서로 삭제 / 이유: 상태 칸·재시도 작업 없이 실패하면 다시 누르면 끝
    async def delete_room(self, room_id: str) -> None:
        """파일 → 메시지 → 방 순서로 지운다. 방 행을 마지막에 지우므로 실패하면 다시 지우면 된다.

        room_members는 방 행을 지우면 함께 지워진다(DB 설정).
        """
        rows = await self._select(
            {"room": f"eq.{room_id}", "file_path": "not.is.null", "select": "file_path"}
        )
        if rows:
            response = await self.client.request(
                "DELETE",
                f"/storage/v1/object/{self.bucket}",
                json={"prefixes": [row["file_path"] for row in rows]},
            )
            response.raise_for_status()
        for table, column in (("messages", "room"), ("rooms", "id")):
            response = await self.client.delete(
                f"/rest/v1/{table}", params={column: f"eq.{room_id}"}
            )
            response.raise_for_status()

    async def add_sanction(self, sanction: dict) -> None:
        await self._insert("sanctions", {**sanction, "until": sanction["until"].isoformat()})

    # 구조: 유효한 제재를 모두 가져와 파이썬에서 거름 / 이유: 복잡한 DB 필터 없이 반복문 한 줄
    async def active_sanctions(self) -> list[dict]:
        rows = await self._select({"until": f"gt.{_now().isoformat()}"}, "sanctions")
        return [{**row, "until": datetime.fromisoformat(row["until"])} for row in rows]

    async def ping(self) -> None:
        """DB를 가볍게 한 번 조회해서 Supabase가 비활동으로 멈추지 않게 한다."""
        await self._select({"select": "id", "limit": 1})

    async def close(self) -> None:
        await self.client.aclose()
