"""비둘기 서비스: 멤버·게스트·운영진이 쓰는 대화방 웹앱."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import secrets
import time
from typing import Annotated
from urllib.parse import quote
import uuid

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from auth import (
    GUEST_ROOM,
    KICK_MINUTES,
    MUTE_MINUTES,
    ROOMS,
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    Identity,
    can_delete_room,
    can_rename_room,
    can_see,
    check_login,
    is_custom_room,
    make_session,
    new_guest,
    read_session,
    room_access,
    room_partner,
    rooms_for,
)
from models import MessageCreate
from store import MemoryStore, SupabaseStore
from templates import (
    render_admin,
    render_chat,
    render_error,
    render_login,
    render_messages,
    render_rooms,
)


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
STORAGE_LIMIT_BYTES = 1024 * 1024 * 1024
ONLINE_SECONDS = 60  # 이 시간 안에 요청한 게스트를 "접속 중"으로 본다.
KICKED_MESSAGE = "운영진에 의해 퇴장되었습니다. 잠시 뒤에 다시 입장할 수 있어요."

# 실행 파일과 스크립트는 받지 않는다.
BLOCKED_EXTENSIONS = {
    ".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".pif", ".cpl", ".dll",
    ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".hta", ".jar",
    ".lnk", ".reg", ".sh", ".apk", ".app", ".dmg", ".deb", ".rpm",
}

# 화면에 바로 보여줘도 안전한 형식만 고른다. 나머지는 다운로드로만 제공한다.
INLINE_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp",
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".wav": "audio/wav",
    ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
}
DOWNLOAD_TYPE = "application/octet-stream"


def _store_from_env() -> MemoryStore | SupabaseStore:
    """Supabase 설정이 있으면 Supabase를, 없으면 로컬 확인용 메모리 저장소를 쓴다."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if url and key:
        return SupabaseStore(url, key)
    if os.getenv("RENDER"):
        raise RuntimeError("Render에서는 SUPABASE_URL과 SUPABASE_SERVICE_KEY 환경변수가 필요합니다.")
    return MemoryStore()


def _required_env(value: str | None, name: str) -> str:
    """Render에서는 꼭 필요한 값이 없으면 앱을 시작하지 않는다."""
    value = value or os.getenv(name, "")
    if not value and os.getenv("RENDER"):
        raise RuntimeError(f"Render에서는 {name} 환경변수가 필요합니다.")
    return value


def create_app(
    store: MemoryStore | SupabaseStore | None = None,
    *,
    password: str | None = None,
    master_password: str | None = None,
    secret: str | None = None,
    max_upload_bytes: int = MAX_UPLOAD_BYTES,
) -> FastAPI:
    """실행용 또는 테스트용 저장소와 설정으로 앱을 만든다."""
    app_password = _required_env(password, "APP_PASSWORD")
    master_pw = _required_env(master_password, "MASTER_PASSWORD")
    session_secret = _required_env(secret, "SESSION_SECRET") or secrets.token_hex(32)
    message_store = store if store is not None else _store_from_env()

    # 구조: 접속 중 게스트를 메모리 dict로 관리 / 이유: 테이블·정리 작업 없이 마지막 요청 시각만 비교
    # 지금 접속 중인 게스트: {uid: (이름, 마지막 요청 시각)}. 서버를 다시 켜면 비워지고, 곧 다시 채워진다.
    last_seen: dict[str, tuple[str, float]] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await message_store.close()

    application = FastAPI(title="비둘기 서비스", lifespan=lifespan)
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # ---- 접속 중인 게스트와 제재 ----

    def online_guests(exclude: str | None = None) -> list[tuple[str, str]]:
        """(uid, 이름) 목록."""
        cutoff = time.time() - ONLINE_SECONDS
        for uid in [uid for uid, (_, seen) in last_seen.items() if seen < cutoff]:
            del last_seen[uid]
        return [(uid, name) for uid, (name, _) in last_seen.items() if uid != exclude]

    # 구조: 강퇴·채팅 금지를 한 함수와 한 테이블로 처리 / 이유: 차이가 kind 값 하나뿐
    async def seconds_left(who: Identity, kind: str) -> int:
        """게스트에게 걸린 제재가 끝나기까지 남은 초. 쿠키(uid) 또는 같은 이름이면 걸린 것으로 본다."""
        now = datetime.now(timezone.utc)
        left = [
            (s["until"] - now).total_seconds()
            for s in await message_store.active_sanctions()
            if s["kind"] == kind and (s["uid"] == who.uid or s["name"] == who.name)
        ]
        return int(max(left)) + 1 if left else 0

    # ---- 로그인 확인과 권한 ----

    async def current_identity(request: Request) -> Identity | None:
        """로그인한 사람. 강퇴 중인 게스트는 로그인하지 않은 것으로 본다."""
        who = read_session(request.cookies.get(SESSION_COOKIE, ""), session_secret)
        if who is None or who.role != "guest":
            return who
        if await seconds_left(who, "kick"):
            request.state.kicked = True
            return None
        last_seen[who.uid] = (who.name, time.time())
        return who

    async def require_identity(request: Request) -> Identity:
        who = await current_identity(request)
        if who is None:
            raise HTTPException(status_code=401, detail="kicked" if getattr(request.state, "kicked", False) else "login")
        return who

    async def require_master(request: Request) -> Identity:
        who = await require_identity(request)
        if who.role != "master":
            raise HTTPException(status_code=403)
        return who

    # 구조: 모든 방 주소가 이 함수를 거침 / 이유: 권한 확인을 복사하지 않아 빠뜨릴 수 없음
    async def room_context(who: Identity, room_id: str) -> tuple[str, dict | None]:
        """대화방 권한을 서버에서 확인한다. ("write" 또는 "read", 개인·단체방 정보)를 반환한다."""
        room = None
        if is_custom_room(room_id):
            room = await message_store.get_room(room_id)
            if room is None:
                raise HTTPException(status_code=404)
        access = room_access(who, room_id, room)
        if access is None:
            raise HTTPException(status_code=403)
        return access, room

    def room_titles(who: Identity, room_id: str, room: dict | None) -> tuple[str, str]:
        """대화방 화면에 보여줄 (제목, 설명)."""
        if room is not None:
            return room["name"], ", ".join(member["name"] for member in room["members"])
        if room_id == GUEST_ROOM:
            return "게스트방", "운영진 열람 중" if who.role == "master" else f"{who.name}님으로 접속 중"
        return room_partner(who.name, room_id), f"{who.name}님으로 접속 중"

    # ---- 공통 응답 ----

    def back_to_room(room_id: str, error: str | None = None, wait: int | None = None) -> RedirectResponse:
        query = f"?error={error}" if error else ""
        if wait:
            query += f"&wait={wait}"
        return RedirectResponse(url=f"/rooms/{room_id}{query}", status_code=303)

    def start_session(request: Request, who: Identity) -> RedirectResponse:
        response = RedirectResponse(url="/rooms", status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            make_session(who, session_secret),
            max_age=SESSION_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https",
        )
        return response

    @application.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> HTMLResponse:
        kicked = exc.detail == "kicked"
        return HTMLResponse(
            render_error(exc.status_code, KICKED_MESSAGE if kicked else None),
            status_code=exc.status_code,
            headers={"X-Reason": "kicked"} if kicked else None,
        )

    @application.middleware("http")
    async def reject_large_upload(request: Request, call_next):
        """파일 전체를 받기 전에 요청 크기로 먼저 거른다."""
        length = request.headers.get("content-length", "")
        path = request.url.path
        if (
            request.method == "POST"
            and path.startswith("/rooms/")
            and length.isdigit()
            and int(length) > max_upload_bytes + 1024 * 1024
        ):
            room_id = path.removeprefix("/rooms/").removesuffix("/messages")
            return back_to_room(room_id, "too_large")
        return await call_next(request)

    # ---- 로그인 ----

    @application.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        if await current_identity(request):
            return RedirectResponse(url="/rooms", status_code=303)
        return HTMLResponse(render_login())

    @application.post("/login")
    async def login(
        request: Request,
        name: Annotated[str, Form()] = "",
        password: Annotated[str, Form()] = "",
    ):
        who = check_login(name.strip(), password, app_password, master_pw)
        if who is None:
            html = render_login(error="아이디 또는 비밀번호가 맞지 않습니다.", name=name)
            return HTMLResponse(html, status_code=401)
        return start_session(request, who)

    @application.post("/guest")
    async def guest_login(request: Request, name: Annotated[str, Form()] = ""):
        name = name.strip()[:20]
        if not name:
            return HTMLResponse(render_login(error="이름을 입력해 주세요."), status_code=401)

        # 이미 게스트로 들어온 적이 있으면 같은 uid를 이어 써서 쿠키 기준 제재가 유지되게 한다.
        earlier = read_session(request.cookies.get(SESSION_COOKIE, ""), session_secret)
        uid = earlier.uid if earlier and earlier.role == "guest" else new_guest(name).uid
        who = Identity("guest", name, uid)

        left = await seconds_left(who, "kick")
        if left:
            error = f"지금은 입장할 수 없어요. {(left + 59) // 60}분 뒤에 다시 시도해 주세요."
            return HTMLResponse(render_login(error=error), status_code=403)
        return start_session(request, who)

    @application.post("/logout")
    def logout():
        response = RedirectResponse(url="/", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return response

    # ---- 대화방 목록과 개인·단체방 ----

    @application.get("/rooms", response_class=HTMLResponse)
    async def room_list(request: Request):
        who = await current_identity(request)
        if who is None:
            return RedirectResponse(url="/", status_code=303)

        if who.role == "guest":
            entries = [(GUEST_ROOM, "게스트방", "모든 게스트가 함께 쓰는 방")]
            for room in await message_store.list_rooms():
                if any(member["uid"] == who.uid for member in room["members"]):
                    names = ", ".join(member["name"] for member in room["members"])
                    entries.append((room["id"], room["name"], names))
            return HTMLResponse(render_rooms(who, entries, online=online_guests(exclude=who.uid)))

        my_rooms = rooms_for(who.name)
        if len(my_rooms) == 1:
            return RedirectResponse(url=f"/rooms/{my_rooms[0]}", status_code=303)
        entries = [
            (room_id, room_partner(who.name, room_id), f"{who.name} ↔ {room_partner(who.name, room_id)}")
            for room_id in my_rooms
        ]
        return HTMLResponse(render_rooms(who, entries, show_admin=who.role == "master"))

    @application.post("/rooms")
    async def create_room(
        request: Request,
        name: Annotated[str, Form()] = "",
        members: Annotated[list[str], Form()] = [],
    ):
        who = await require_identity(request)
        if who.role != "guest":
            raise HTTPException(status_code=403)

        # 지금 접속 중인 게스트만 초대할 수 있다.
        online = dict(online_guests(exclude=who.uid))
        invited = [uid for uid in dict.fromkeys(members) if uid in online]
        if not invited:
            return RedirectResponse(url="/rooms", status_code=303)

        people = [{"uid": who.uid, "name": who.name}] + [
            {"uid": uid, "name": online[uid]} for uid in invited
        ]
        room_id = "r" + uuid.uuid4().hex[:12]
        room_name = name.strip() or ", ".join(person["name"] for person in people)
        await message_store.create_room(
            {"id": room_id, "name": room_name[:30], "owner_id": who.uid, "members": people}
        )
        return RedirectResponse(url=f"/rooms/{room_id}", status_code=303)

    @application.post("/rooms/{room_id}/rename")
    async def rename_room(request: Request, room_id: str, name: Annotated[str, Form()] = ""):
        who = await require_identity(request)
        room = await message_store.get_room(room_id)
        if room is None:
            raise HTTPException(status_code=404)
        if not can_rename_room(who, room):
            raise HTTPException(status_code=403)
        new_name = name.strip()[:30]
        if not new_name:
            return back_to_room(room_id, "bad_name")
        await message_store.rename_room(room_id, new_name)
        return back_to_room(room_id)

    @application.post("/rooms/{room_id}/delete")
    async def delete_room(request: Request, room_id: str):
        who = await require_identity(request)
        room = await message_store.get_room(room_id)
        if room is None:
            raise HTTPException(status_code=404)
        if not can_delete_room(who, room):
            raise HTTPException(status_code=403)
        await message_store.delete_room(room_id)
        return RedirectResponse(url="/admin" if who.role == "master" else "/rooms", status_code=303)

    # ---- 대화방 ----

    @application.get("/rooms/{room_id}", response_class=HTMLResponse)
    async def room_page(request: Request, room_id: str, error: str | None = None, wait: int = 0):
        who = await current_identity(request)
        if who is None:
            return RedirectResponse(url="/", status_code=303)
        access, room = await room_context(who, room_id)
        messages = [m for m in await message_store.recent_messages(room_id) if can_see(who, m)]
        title, subtitle = room_titles(who, room_id, room)
        notice = None
        if error == "muted":
            wait = max(wait, 0)
            notice = f"채팅이 금지되었습니다. 남은 시간: {wait // 60}분 {wait % 60}초"
        html = render_chat(
            who,
            room_id,
            title,
            subtitle,
            messages,
            used_bytes=await message_store.used_bytes(),
            storage_limit=STORAGE_LIMIT_BYTES,
            max_upload_bytes=max_upload_bytes,
            can_go_back=who.role != "member",
            can_write=access == "write",
            can_rename=room is not None and can_rename_room(who, room),
            can_delete=room is not None and can_delete_room(who, room),
            error=error,
            notice=notice,
        )
        return HTMLResponse(html)

    @application.get("/rooms/{room_id}/messages", response_class=HTMLResponse)
    async def new_messages(request: Request, room_id: str, after: int = 0):
        """화면이 3초마다 부르는 주소. after 이후의 새 메시지만 HTML 조각으로 준다."""
        who = await require_identity(request)
        await room_context(who, room_id)
        messages = [m for m in await message_store.messages_after(room_id, after) if can_see(who, m)]
        return HTMLResponse(render_messages(messages, who.uid), headers={"Cache-Control": "no-store"})

    @application.post("/rooms/{room_id}/messages")
    async def send_message(
        request: Request,
        room_id: str,
        body: Annotated[str, Form()] = "",
        # 파일을 고르지 않으면 브라우저가 빈 문자열을 보내므로 str도 받는다.
        upload: Annotated[UploadFile | str | None, File()] = None,
    ):
        who = await require_identity(request)
        access, _ = await room_context(who, room_id)
        if access != "write":
            raise HTTPException(status_code=403)
        if who.role == "guest":
            muted_for = await seconds_left(who, "mute")
            if muted_for:
                return back_to_room(room_id, "muted", wait=muted_for)

        try:
            text = MessageCreate(body=body).body
        except ValidationError:
            return back_to_room(room_id, "too_long")

        message = {"room": room_id, "sender": who.name, "sender_id": who.uid, "body": text}

        if upload and not isinstance(upload, str) and upload.filename:
            extension = Path(upload.filename).suffix.lower()
            if extension in BLOCKED_EXTENSIONS:
                return back_to_room(room_id, "blocked")
            data = await upload.read(max_upload_bytes + 1)
            if len(data) > max_upload_bytes:
                return back_to_room(room_id, "too_large")
            if not data:
                return back_to_room(room_id, "empty_file")
            if await message_store.used_bytes() + len(data) > STORAGE_LIMIT_BYTES:
                return back_to_room(room_id, "storage_full")

            # 저장 이름은 무작위로 만들고, 원래 이름은 표시용으로만 보관한다.
            safe_extension = extension if extension[1:].isascii() and extension[1:].isalnum() else ""
            file_path = f"{room_id}/{uuid.uuid4().hex}{safe_extension}"
            file_type = INLINE_TYPES.get(extension, DOWNLOAD_TYPE)
            await message_store.upload_file(file_path, data, file_type)
            message.update(
                file_path=file_path,
                file_name=Path(upload.filename).name[:120],
                file_type=file_type,
                file_size=len(data),
            )
        elif not text:
            return back_to_room(room_id, "empty")

        await message_store.add_message(message)
        return back_to_room(room_id)

    @application.get("/files/{message_id}")
    async def download_file(request: Request, message_id: int):
        who = await require_identity(request)
        message = await message_store.get_message(message_id)
        if message is None or not message.get("file_path"):
            raise HTTPException(status_code=404)
        await room_context(who, message["room"])
        if not can_see(who, message):
            raise HTTPException(status_code=403)

        status, data, extra_headers = await message_store.download_file(
            message["file_path"], request.headers.get("range")
        )
        file_type = message.get("file_type") or DOWNLOAD_TYPE
        disposition = "attachment" if file_type == DOWNLOAD_TYPE else "inline"
        # 파일은 바뀌지 않으므로 브라우저가 한 번만 받게 한다(Supabase 전송량 절약).
        # 개인·단체방 파일은 방을 지우면 사라져야 하므로 브라우저에 남기지 않는다.
        cache = "private, no-store" if is_custom_room(message["room"]) else "private, max-age=31536000, immutable"
        headers = {
            **extra_headers,
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(message['file_name'])}",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
            "Cache-Control": cache,
        }
        return Response(content=data, status_code=status, media_type=file_type, headers=headers)

    # ---- 운영진(마스터) ----

    @application.get("/admin", response_class=HTMLResponse)
    async def admin_page(request: Request):
        who = await current_identity(request)
        if who is None:
            return RedirectResponse(url="/", status_code=303)
        if who.role != "master":
            raise HTTPException(status_code=403)
        fixed_rooms = [(room_id, f"{room_partner('홍록기', room_id)}님과의 대화") for room_id in ROOMS]
        fixed_rooms.append((GUEST_ROOM, "게스트방"))
        html = render_admin(online_guests(), await message_store.list_rooms(), fixed_rooms)
        return HTMLResponse(html)

    # 구조: 비밀 메시지는 메시지에 private_to 칸 하나 추가 / 이유: 별도 테이블·화면 없이 can_see로 필터
    @application.post("/admin/secret")
    async def send_secret(
        request: Request,
        uid: Annotated[str, Form()] = "",
        body: Annotated[str, Form()] = "",
    ):
        who = await require_master(request)
        try:
            text = MessageCreate(body=body).body
        except ValidationError:
            text = ""
        if text and uid in dict(online_guests()):
            await message_store.add_message(
                {"room": GUEST_ROOM, "sender": who.name, "sender_id": who.uid, "body": text, "private_to": uid}
            )
        return RedirectResponse(url="/admin", status_code=303)

    @application.post("/admin/sanction")
    async def sanction_guest(
        request: Request,
        uid: Annotated[str, Form()] = "",
        action: Annotated[str, Form()] = "",
    ):
        await require_master(request)
        name = dict(online_guests()).get(uid)
        if name is None:
            return RedirectResponse(url="/admin", status_code=303)

        if action == "kick":
            kind, minutes = "kick", KICK_MINUTES
        elif action.startswith("mute:") and action[5:].isdigit() and int(action[5:]) in MUTE_MINUTES:
            kind, minutes = "mute", int(action[5:])
        else:
            raise HTTPException(status_code=400)

        until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        await message_store.add_sanction({"uid": uid, "name": name, "kind": kind, "until": until})
        if kind == "kick":
            last_seen.pop(uid, None)
        return RedirectResponse(url="/admin", status_code=303)

    @application.api_route("/health", methods=["GET", "HEAD"])
    async def health() -> dict[str, str]:
        """UptimeRobot이 5분마다 부르는 주소. DB도 가볍게 한 번 조회한다."""
        await message_store.ping()
        return {"status": "ok"}

    return application


app = create_app()
