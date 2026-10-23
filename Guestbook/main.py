"""FastAPI와 SQLite로 만든 최소 구성 방명록 웹앱."""

from contextlib import asynccontextmanager
import os
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from database import count_entries, create_entry, initialize_database, list_entries
from models import GuestbookCreate
from templates import render_page


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DEFAULT_DATABASE_PATH = BASE_DIR / "data" / "guestbook.db"


def create_app(database_path: str | Path | None = None) -> FastAPI:
    """실행용 또는 테스트용 데이터베이스 경로로 앱을 만든다."""
    selected_path = Path(
        database_path
        or os.getenv("GUESTBOOK_DB_PATH", str(DEFAULT_DATABASE_PATH))
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        initialize_database(selected_path)
        yield

    application = FastAPI(
        title="우리의 방명록",
        description="DAY 1부터 DAY 8까지 학습한 파이썬과 FastAPI로 만든 방명록",
        lifespan=lifespan,
    )
    application.state.database_path = selected_path
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @application.get("/", response_class=HTMLResponse)
    def home() -> HTMLResponse:
        entries = list_entries(application.state.database_path)
        return HTMLResponse(render_page(entries))

    @application.post("/entries", response_class=HTMLResponse)
    async def submit_entry(request: Request):
        raw_body = (await request.body()).decode("utf-8", errors="replace")
        form = parse_qs(raw_body, keep_blank_values=True)
        submitted = {
            "name": form.get("name", [""])[0],
            "message": form.get("message", [""])[0],
        }

        try:
            entry = GuestbookCreate.model_validate(submitted)
        except ValidationError:
            entries = list_entries(application.state.database_path)
            html = render_page(
                entries,
                error="이름은 1~20자, 메시지는 1~500자로 입력해 주세요.",
                form_name=submitted["name"],
                form_message=submitted["message"],
            )
            return HTMLResponse(html, status_code=422)

        create_entry(
            application.state.database_path,
            name=entry.name,
            message=entry.message,
        )
        return RedirectResponse(url="/", status_code=303)

    @application.get("/health")
    def health() -> dict[str, int | str]:
        return {
            "status": "ok",
            "entries": count_entries(application.state.database_path),
        }

    return application


app = create_app()
