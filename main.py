"""비둘기 서비스: 정해진 두 사람만 들어가는 대화방 웹앱."""

from contextlib import asynccontextmanager
import os
from pathlib import Path
import secrets
from typing import Annotated
from urllib.parse import quote
import uuid

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from auth import (
    ROOMS,
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    USERS,
    can_enter,
    check_login,
    make_session,
    read_session,
    room_partner,
    rooms_for,
)
from models import MessageCreate
from store import MemoryStore, SupabaseStore
from templates import render_chat, render_error, render_login, render_messages, render_rooms


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
STORAGE_LIMIT_BYTES = 1024 * 1024 * 1024

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


def create_app(
    store: MemoryStore | SupabaseStore | None = None,
    *,
    password: str | None = None,
    secret: str | None = None,
    max_upload_bytes: int = MAX_UPLOAD_BYTES,
) -> FastAPI:
    """실행용 또는 테스트용 저장소와 설정으로 앱을 만든다."""
    app_password = password or os.getenv("APP_PASSWORD", "")
    if not app_password and os.getenv("RENDER"):
        raise RuntimeError("Render에서는 APP_PASSWORD 환경변수가 필요합니다.")
    session_secret = secret or os.getenv("SESSION_SECRET") or secrets.token_hex(32)
    message_store = store if store is not None else _store_from_env()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await message_store.close()

    application = FastAPI(title="비둘기 서비스", lifespan=lifespan)
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def current_user(request: Request) -> str | None:
        return read_session(request.cookies.get(SESSION_COOKIE, ""), session_secret)

    def require_member(request: Request, room_id: str) -> str:
        """로그인 여부와 대화방 권한을 서버에서 확인한다."""
        user = current_user(request)
        if user is None:
            raise HTTPException(status_code=401)
        if room_id not in ROOMS:
            raise HTTPException(status_code=404)
        if not can_enter(user, room_id):
            raise HTTPException(status_code=403)
        return user

    def back_to_room(room_id: str, error: str | None = None) -> RedirectResponse:
        query = f"?error={error}" if error else ""
        return RedirectResponse(url=f"/rooms/{room_id}{query}", status_code=303)

    @application.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> HTMLResponse:
        return HTMLResponse(render_error(exc.status_code), status_code=exc.status_code)

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

    @application.get("/", response_class=HTMLResponse)
    def home(request: Request):
        if current_user(request):
            return RedirectResponse(url="/rooms", status_code=303)
        return HTMLResponse(render_login(USERS))

    @application.post("/login")
    def login(
        request: Request,
        name: Annotated[str, Form()] = "",
        password: Annotated[str, Form()] = "",
    ):
        if not check_login(name, password, app_password):
            html = render_login(USERS, error="이름 또는 비밀번호가 맞지 않습니다.", selected=name)
            return HTMLResponse(html, status_code=401)

        response = RedirectResponse(url="/rooms", status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            make_session(name, session_secret),
            max_age=SESSION_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https",
        )
        return response

    @application.post("/logout")
    def logout():
        response = RedirectResponse(url="/", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return response

    @application.get("/rooms", response_class=HTMLResponse)
    def room_list(request: Request):
        user = current_user(request)
        if user is None:
            return RedirectResponse(url="/", status_code=303)
        my_rooms = rooms_for(user)
        if len(my_rooms) == 1:
            return RedirectResponse(url=f"/rooms/{my_rooms[0]}", status_code=303)
        rooms = [(room_id, room_partner(user, room_id)) for room_id in my_rooms]
        return HTMLResponse(render_rooms(user, rooms))

    @application.get("/rooms/{room_id}", response_class=HTMLResponse)
    async def room_page(request: Request, room_id: str, error: str | None = None):
        if current_user(request) is None:
            return RedirectResponse(url="/", status_code=303)
        user = require_member(request, room_id)
        messages = await message_store.recent_messages(room_id)
        html = render_chat(
            user,
            room_id,
            room_partner(user, room_id),
            messages,
            used_bytes=await message_store.used_bytes(),
            storage_limit=STORAGE_LIMIT_BYTES,
            max_upload_bytes=max_upload_bytes,
            can_go_back=len(rooms_for(user)) > 1,
            error=error,
        )
        return HTMLResponse(html)

    @application.get("/rooms/{room_id}/messages", response_class=HTMLResponse)
    async def new_messages(request: Request, room_id: str, after: int = 0):
        """화면이 3초마다 부르는 주소. after 이후의 새 메시지만 HTML 조각으로 준다."""
        user = require_member(request, room_id)
        messages = await message_store.messages_after(room_id, after)
        return HTMLResponse(render_messages(messages, user), headers={"Cache-Control": "no-store"})

    @application.post("/rooms/{room_id}/messages")
    async def send_message(
        request: Request,
        room_id: str,
        body: Annotated[str, Form()] = "",
        # 파일을 고르지 않으면 브라우저가 빈 문자열을 보내므로 str도 받는다.
        upload: Annotated[UploadFile | str | None, File()] = None,
    ):
        user = require_member(request, room_id)
        try:
            text = MessageCreate(body=body).body
        except ValidationError:
            return back_to_room(room_id, "too_long")

        message = {"room": room_id, "sender": user, "body": text}

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
        user = current_user(request)
        if user is None:
            raise HTTPException(status_code=401)
        message = await message_store.get_message(message_id)
        if message is None or not message.get("file_path"):
            raise HTTPException(status_code=404)
        if not can_enter(user, message["room"]):
            raise HTTPException(status_code=403)

        status, data, extra_headers = await message_store.download_file(
            message["file_path"], request.headers.get("range")
        )
        file_type = message.get("file_type") or DOWNLOAD_TYPE
        disposition = "attachment" if file_type == DOWNLOAD_TYPE else "inline"
        headers = {
            **extra_headers,
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(message['file_name'])}",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
            # 파일은 바뀌지 않으므로 브라우저가 한 번만 받게 한다(Supabase 전송량 절약).
            "Cache-Control": "private, max-age=31536000, immutable",
        }
        return Response(content=data, status_code=status, media_type=file_type, headers=headers)

    @application.api_route("/health", methods=["GET", "HEAD"])
    async def health() -> dict[str, str]:
        """UptimeRobot이 5분마다 부르는 주소. DB도 가볍게 한 번 조회한다."""
        await message_store.ping()
        return {"status": "ok"}

    return application


app = create_app()
