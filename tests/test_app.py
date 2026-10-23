import pytest
from fastapi.testclient import TestClient

from auth import SESSION_COOKIE, SESSION_MAX_AGE, make_session, read_session
from main import create_app
from store import MemoryStore


PASSWORD = "test-pass"
SECRET = "test-secret"


@pytest.fixture
def store():
    return MemoryStore()


@pytest.fixture
def make_client(store):
    """같은 저장소를 쓰는 클라이언트를 사용자별로 만든다."""
    clients = []

    def _make(user: str | None = None, **options) -> TestClient:
        app = create_app(store, password=PASSWORD, secret=SECRET, **options)
        client = TestClient(app)
        if user:
            client.cookies.set(SESSION_COOKIE, make_session(user, SECRET))
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.close()


def send(client: TestClient, room: str, body: str = "", file=None):
    files = {"upload": file} if file else None
    return client.post(
        f"/rooms/{room}/messages", data={"body": body}, files=files, follow_redirects=False
    )


# 로그인

def test_first_screen_is_login(make_client):
    page = make_client().get("/")

    assert page.status_code == 200
    assert "비둘기 서비스" in page.text
    assert 'name="password"' in page.text


def test_login_success_sets_session_cookie(make_client):
    response = make_client().post(
        "/login", data={"name": "홍록기", "password": PASSWORD}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/rooms"
    assert SESSION_COOKIE in response.cookies


@pytest.mark.parametrize(
    "name, password",
    [("홍록기", "0000"), ("모르는사람", PASSWORD), ("", "")],
)
def test_login_failure(make_client, name, password):
    response = make_client().post("/login", data={"name": name, "password": password})

    assert response.status_code == 401
    assert "맞지 않습니다" in response.text
    assert SESSION_COOKIE not in response.cookies


def test_forged_cookie_is_ignored(make_client):
    client = make_client()
    client.cookies.set(SESSION_COOKIE, make_session("홍록기", "wrong-secret"))

    response = client.get("/rooms", follow_redirects=False)
    assert response.headers["location"] == "/"


def test_session_expires():
    value = make_session("홍록기", SECRET, now=0)

    assert read_session(value, SECRET, now=SESSION_MAX_AGE) == "홍록기"
    assert read_session(value, SECRET, now=SESSION_MAX_AGE + 1) is None


def test_logout_clears_cookie(make_client):
    response = make_client("홍록기").post("/logout", follow_redirects=False)

    assert response.headers["location"] == "/"
    assert SESSION_COOKIE in response.headers["set-cookie"]


# 대화방 접근 제한

def test_hong_sees_both_rooms(make_client):
    page = make_client("홍록기").get("/rooms")

    assert "허순태" in page.text
    assert "곽승현" in page.text


@pytest.mark.parametrize("user, room", [("허순태", "room1"), ("곽승현", "room2")])
def test_others_go_straight_to_their_room(make_client, user, room):
    response = make_client(user).get("/rooms", follow_redirects=False)

    assert response.headers["location"] == f"/rooms/{room}"


@pytest.mark.parametrize("user, blocked_room", [("허순태", "room2"), ("곽승현", "room1")])
def test_server_blocks_other_room(make_client, store, user, blocked_room):
    client = make_client(user)

    assert client.get(f"/rooms/{blocked_room}").status_code == 403
    assert client.get(f"/rooms/{blocked_room}/messages").status_code == 403
    assert send(client, blocked_room, "몰래 보내기").status_code == 403
    assert store.messages == []


def test_logged_out_user_cannot_read_or_send(make_client, store):
    client = make_client()

    assert client.get("/rooms/room1", follow_redirects=False).headers["location"] == "/"
    assert client.get("/rooms/room1/messages").status_code == 401
    assert send(client, "room1", "hi").status_code == 401
    assert store.messages == []


def test_unknown_room_is_404(make_client):
    assert make_client("홍록기").get("/rooms/room9").status_code == 404


# 메시지

def test_message_is_mine_on_right_and_theirs_on_left(make_client):
    hur = make_client("허순태")
    hong = make_client("홍록기")

    response = send(hur, "room1", "안녕하세요")
    assert response.status_code == 303
    assert response.headers["location"] == "/rooms/room1"

    assert 'class="msg mine"' in hur.get("/rooms/room1").text
    hong_page = hong.get("/rooms/room1").text
    assert 'class="msg theirs"' in hong_page
    assert "안녕하세요" in hong_page


def test_polling_returns_only_new_messages(make_client):
    client = make_client("홍록기")
    send(client, "room1", "첫째")
    send(client, "room1", "둘째")

    everything = client.get("/rooms/room1/messages?after=0").text
    assert everything.index("첫째") < everything.index("둘째")

    newer = client.get("/rooms/room1/messages?after=1").text
    assert "둘째" in newer
    assert "첫째" not in newer
    assert client.get("/rooms/room1/messages?after=2").text.strip() == ""


def test_rooms_do_not_mix(make_client):
    hong = make_client("홍록기")
    send(hong, "room1", "순태에게")

    assert "순태에게" not in make_client("곽승현").get("/rooms/room2").text


def test_message_html_is_escaped(make_client):
    client = make_client("홍록기")
    send(client, "room1", "<script>alert(1)</script>")

    page = client.get("/rooms/room1").text
    assert "<script>alert" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


@pytest.mark.parametrize("body, error", [("   ", "empty"), ("가" * 1001, "too_long")])
def test_invalid_message_is_rejected(make_client, store, body, error):
    response = send(make_client("홍록기"), "room1", body)

    assert response.headers["location"] == f"/rooms/room1?error={error}"
    assert store.messages == []


def test_text_with_empty_file_input_is_sent(make_client, store):
    response = send(make_client("홍록기"), "room1", "글만", ("", b"", "application/octet-stream"))

    assert response.headers["location"] == "/rooms/room1"
    assert store.messages[0]["body"] == "글만"
    assert store.files == {}


# 파일

def test_image_upload_and_download(make_client):
    hur = make_client("허순태")
    response = send(hur, "room1", "", ("사진.png", b"fake-png" * 256, "image/png"))
    assert response.headers["location"] == "/rooms/room1"

    page = hur.get("/rooms/room1").text
    assert '<img src="/files/1"' in page
    assert "사용량 2.0KB" in page

    file = hur.get("/files/1")
    assert file.status_code == 200
    assert file.content == b"fake-png" * 256
    assert file.headers["content-type"] == "image/png"
    assert file.headers["content-disposition"].startswith("inline")
    assert file.headers["x-content-type-options"] == "nosniff"
    assert "immutable" in file.headers["cache-control"]


@pytest.mark.parametrize("filename", ["setup.exe", "SETUP.EXE", "run.bat", "script.ps1"])
def test_executable_is_blocked(make_client, store, filename):
    response = send(make_client("홍록기"), "room1", "", (filename, b"MZ", "application/octet-stream"))

    assert response.headers["location"] == "/rooms/room1?error=blocked"
    assert store.files == {}


def test_file_over_limit_is_blocked(make_client, store):
    response = send(make_client("홍록기", max_upload_bytes=10), "room1", "", ("big.zip", b"x" * 11, "application/zip"))

    assert response.headers["location"] == "/rooms/room1?error=too_large"
    assert store.files == {}


def test_huge_request_is_blocked_before_reading(make_client, store):
    client = make_client("홍록기", max_upload_bytes=10)
    response = send(client, "room1", "", ("huge.zip", b"x" * (2 * 1024 * 1024), "application/zip"))

    assert response.headers["location"] == "/rooms/room1?error=too_large"
    assert store.files == {}


def test_html_file_is_download_only(make_client):
    client = make_client("홍록기")
    send(client, "room1", "", ("page.html", b"<script>alert(1)</script>", "text/html"))

    file = client.get("/files/1")
    assert file.headers["content-type"] == "application/octet-stream"
    assert file.headers["content-disposition"].startswith("attachment")


def test_other_room_file_is_forbidden(make_client):
    send(make_client("허순태"), "room1", "", ("비밀.png", b"secret", "image/png"))

    assert make_client("곽승현").get("/files/1").status_code == 403
    assert make_client().get("/files/1").status_code == 401
    assert make_client("홍록기").get("/files/1").status_code == 200


# 서버 깨어 있게 하기

def test_health_supports_get_and_head(make_client):
    client = make_client()

    assert client.get("/health").json() == {"status": "ok"}
    assert client.head("/health").status_code == 200
