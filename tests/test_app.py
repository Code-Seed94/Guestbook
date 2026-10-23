from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from main import create_app


@pytest.fixture
def client(tmp_path: Path):
    app = create_app(tmp_path / "guestbook-test.db")
    with TestClient(app) as test_client:
        yield test_client


def test_empty_home_page(client: TestClient):
    response = client.get("/")

    assert response.status_code == 200
    assert "우리의 방명록" in response.text
    assert "아직 작성된 글이 없습니다" in response.text


def test_page_does_not_use_javascript(client: TestClient):
    response = client.get("/")

    assert "<script" not in response.text.lower()


def test_create_entry_and_read_it(client: TestClient):
    created = client.post(
        "/entries",
        data={"name": "학생", "message": "반갑습니다!"},
        follow_redirects=False,
    )

    assert created.status_code == 303
    assert created.headers["location"] == "/"

    page = client.get("/")
    assert page.status_code == 200
    assert "학생" in page.text
    assert "반갑습니다!" in page.text


def test_newest_entry_is_first(client: TestClient):
    client.post("/entries", data={"name": "첫째", "message": "첫 글"})
    client.post("/entries", data={"name": "둘째", "message": "둘째 글"})

    page = client.get("/")
    assert page.text.index("둘째 글") < page.text.index("첫 글")


@pytest.mark.parametrize(
    "name, message",
    [
        ("", "메시지"),
        ("   ", "메시지"),
        ("이름", ""),
        ("이름", "   "),
        ("가" * 21, "메시지"),
        ("이름", "가" * 501),
    ],
)
def test_invalid_entry_is_rejected(client: TestClient, name: str, message: str):
    response = client.post("/entries", data={"name": name, "message": message})

    assert response.status_code == 422
    assert "입력해 주세요" in response.text
    assert client.get("/health").json()["entries"] == 0


def test_html_is_escaped(client: TestClient):
    client.post(
        "/entries",
        data={"name": "<b>이름</b>", "message": "<script>alert(1)</script>"},
    )

    page = client.get("/")
    assert "<script>" not in page.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text


def test_sqlite_data_survives_app_restart(tmp_path: Path):
    database_path = tmp_path / "persistent.db"

    with TestClient(create_app(database_path)) as first_client:
        first_client.post("/entries", data={"name": "저장", "message": "남아 있어요"})

    with TestClient(create_app(database_path)) as second_client:
        page = second_client.get("/")
        assert "남아 있어요" in page.text
        assert second_client.get("/health").json()["entries"] == 1


def test_database_has_one_user_table(tmp_path: Path):
    database_path = tmp_path / "schema.db"

    with TestClient(create_app(database_path)):
        pass

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()

    assert rows == [("entries",)]
