from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from auth import SESSION_COOKIE, SESSION_MAX_AGE, Identity, make_session, read_session
from main import create_app
from store import MemoryStore


PASSWORD = "test-pass"
MASTER_PASSWORD = "master-pass"
SECRET = "test-secret"

HONG = Identity("master", "홍록기", "홍록기")
HUR = Identity("member", "허순태", "허순태")
KWAK = Identity("member", "곽승현", "곽승현")


def guest(name: str) -> Identity:
    return Identity("guest", name, f"g_{name}")


@pytest.fixture
def store():
    return MemoryStore()


@pytest.fixture
def make_client(store):
    """같은 저장소를 쓰는 클라이언트를 사용자별로 만든다. 클라이언트마다 앱이 따로다."""
    clients = []

    def _make(user: Identity | None = None, **options) -> TestClient:
        app = create_app(
            store, password=PASSWORD, master_password=MASTER_PASSWORD, secret=SECRET, **options
        )
        client = TestClient(app)
        if user:
            client.cookies.set(SESSION_COOKIE, make_session(user, SECRET))
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.close()


@pytest.fixture
def make_shared(store):
    """앱 하나를 여러 사용자가 함께 쓴다. 접속 중인 게스트 목록은 앱 안에 있으므로 필요하다."""
    app = create_app(store, password=PASSWORD, master_password=MASTER_PASSWORD, secret=SECRET)
    clients = []

    def _make(user: Identity | None = None) -> TestClient:
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


def go_online(*clients: TestClient) -> None:
    """게스트가 화면을 열어 둔 상태로 만든다."""
    for client in clients:
        client.get("/rooms")


def create_room(client: TestClient, *members: Identity, name: str = "") -> str:
    response = client.post(
        "/rooms", data={"members": [m.uid for m in members], "name": name}, follow_redirects=False
    )
    assert response.status_code == 303
    return response.headers["location"].removeprefix("/rooms/")


# 로그인

def test_first_screen_is_login(make_client):
    page = make_client().get("/")

    assert page.status_code == 200
    assert "비둘기 서비스" in page.text
    assert 'name="password"' in page.text
    assert "Guest 입장" in page.text
    assert 'placeholder="본인의 이름을 입력해 주세요"' in page.text
    assert "운영진은 채팅방 내용을 확인할 수 있습니다" in page.text


@pytest.mark.parametrize("name, password", [("홍록기", MASTER_PASSWORD), ("허순태", PASSWORD)])
def test_login_success_sets_session_cookie(make_client, name, password):
    response = make_client().post(
        "/login", data={"name": name, "password": password}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/rooms"
    assert SESSION_COOKIE in response.cookies


@pytest.mark.parametrize(
    "name, password",
    [
        ("홍록기", "0000"),
        ("홍록기", PASSWORD),  # 홍록기는 마스터 비밀번호로만 들어간다
        ("허순태", MASTER_PASSWORD),
        ("모르는사람", PASSWORD),
        ("", ""),
    ],
)
def test_login_failure(make_client, name, password):
    response = make_client().post("/login", data={"name": name, "password": password})

    assert response.status_code == 401
    assert "맞지 않습니다" in response.text
    assert SESSION_COOKIE not in response.cookies


def test_forged_cookie_is_ignored(make_client):
    client = make_client()
    client.cookies.set(SESSION_COOKIE, make_session(HONG, "wrong-secret"))

    response = client.get("/rooms", follow_redirects=False)
    assert response.headers["location"] == "/"


def test_session_expires():
    value = make_session(HONG, SECRET, now=0)

    assert read_session(value, SECRET, now=SESSION_MAX_AGE) == HONG
    assert read_session(value, SECRET, now=SESSION_MAX_AGE + 1) is None


def test_guest_cannot_pose_as_master_in_cookie():
    fake = Identity("master", "아무개", "아무개")

    assert read_session(make_session(fake, SECRET), SECRET) is None


def test_logout_clears_cookie(make_client):
    response = make_client(HONG).post("/logout", follow_redirects=False)

    assert response.headers["location"] == "/"
    assert SESSION_COOKIE in response.headers["set-cookie"]


# 게스트 입장

def test_guest_login_sets_guest_session(make_client):
    client = make_client()
    response = client.post("/guest", data={"name": "  민수  "}, follow_redirects=False)

    assert response.headers["location"] == "/rooms"
    who = read_session(response.cookies[SESSION_COOKIE], SECRET)
    assert who.role == "guest"
    assert who.name == "민수"
    assert who.uid.startswith("g_")


def test_guest_login_requires_name(make_client):
    response = make_client().post("/guest", data={"name": "   "})

    assert response.status_code == 401
    assert SESSION_COOKIE not in response.cookies


def test_guest_named_hong_has_no_master_power(make_client, make_shared):
    client = make_client()
    client.post("/guest", data={"name": "홍록기"})

    assert client.get("/admin").status_code == 403
    assert client.get("/rooms/room1").status_code == 403
    assert client.get("/rooms/room2").status_code == 403


def test_guest_room_list_has_guest_room_and_create_form(make_client):
    page = make_client(guest("민수")).get("/rooms")

    assert 'href="/rooms/guest"' in page.text
    assert "새 대화방" in page.text


# 대화방 접근 제한

def test_hong_sees_both_rooms(make_client):
    page = make_client(HONG).get("/rooms")

    assert "허순태" in page.text
    assert "곽승현" in page.text
    assert 'href="/admin"' in page.text


@pytest.mark.parametrize("user, room", [(HUR, "room1"), (KWAK, "room2")])
def test_others_go_straight_to_their_room(make_client, user, room):
    response = make_client(user).get("/rooms", follow_redirects=False)

    assert response.headers["location"] == f"/rooms/{room}"


@pytest.mark.parametrize("user, blocked_room", [(HUR, "room2"), (KWAK, "room1")])
def test_server_blocks_other_room(make_client, store, user, blocked_room):
    client = make_client(user)

    assert client.get(f"/rooms/{blocked_room}").status_code == 403
    assert client.get(f"/rooms/{blocked_room}/messages").status_code == 403
    assert send(client, blocked_room, "몰래 보내기").status_code == 403
    assert store.messages == []


@pytest.mark.parametrize("user", [HUR, KWAK, guest("민수")])
def test_members_and_guests_are_kept_apart(make_client, store, user):
    client = make_client(user)
    blocked = "guest" if user.role == "member" else "room1"

    assert client.get(f"/rooms/{blocked}").status_code == 403
    assert send(client, blocked, "섞이면 안 돼요").status_code == 403
    assert store.messages == []


def test_logged_out_user_cannot_read_or_send(make_client, store):
    client = make_client()

    assert client.get("/rooms/room1", follow_redirects=False).headers["location"] == "/"
    assert client.get("/rooms/room1/messages").status_code == 401
    assert send(client, "room1", "hi").status_code == 401
    assert store.messages == []


def test_unknown_room_is_404(make_client):
    assert make_client(HONG).get("/rooms/room9").status_code == 404


# 메시지

def test_message_is_mine_on_right_and_theirs_on_left(make_client):
    hur = make_client(HUR)
    hong = make_client(HONG)

    response = send(hur, "room1", "안녕하세요")
    assert response.status_code == 303
    assert response.headers["location"] == "/rooms/room1"

    assert 'class="msg mine"' in hur.get("/rooms/room1").text
    hong_page = hong.get("/rooms/room1").text
    assert 'class="msg theirs"' in hong_page
    assert "안녕하세요" in hong_page


def test_guests_with_same_name_are_told_apart(make_client):
    first = Identity("guest", "민수", "g_one")
    second = Identity("guest", "민수", "g_two")
    send(make_client(first), "guest", "나는 첫째")

    assert 'class="msg mine"' in make_client(first).get("/rooms/guest").text
    assert 'class="msg theirs"' in make_client(second).get("/rooms/guest").text


def test_all_guests_share_one_room(make_client):
    send(make_client(guest("민수")), "guest", "다들 안녕")

    assert "다들 안녕" in make_client(guest("영희")).get("/rooms/guest").text


def test_polling_returns_only_new_messages(make_client):
    client = make_client(HONG)
    send(client, "room1", "첫째")
    send(client, "room1", "둘째")

    everything = client.get("/rooms/room1/messages?after=0").text
    assert everything.index("첫째") < everything.index("둘째")

    newer = client.get("/rooms/room1/messages?after=1").text
    assert "둘째" in newer
    assert "첫째" not in newer
    assert client.get("/rooms/room1/messages?after=2").text.strip() == ""


def test_rooms_do_not_mix(make_client):
    hong = make_client(HONG)
    send(hong, "room1", "순태에게")

    assert "순태에게" not in make_client(KWAK).get("/rooms/room2").text


def test_message_html_is_escaped(make_client):
    client = make_client(HONG)
    send(client, "room1", "<script>alert(1)</script>")

    page = client.get("/rooms/room1").text
    assert "<script>alert" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


@pytest.mark.parametrize("body, error", [("   ", "empty"), ("가" * 1001, "too_long")])
def test_invalid_message_is_rejected(make_client, store, body, error):
    response = send(make_client(HONG), "room1", body)

    assert response.headers["location"] == f"/rooms/room1?error={error}"
    assert store.messages == []


def test_text_with_empty_file_input_is_sent(make_client, store):
    response = send(make_client(HONG), "room1", "글만", ("", b"", "application/octet-stream"))

    assert response.headers["location"] == "/rooms/room1"
    assert store.messages[0]["body"] == "글만"
    assert store.files == {}


# 파일

def test_image_upload_and_download(make_client):
    hur = make_client(HUR)
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
    response = send(make_client(HONG), "room1", "", (filename, b"MZ", "application/octet-stream"))

    assert response.headers["location"] == "/rooms/room1?error=blocked"
    assert store.files == {}


def test_file_over_limit_is_blocked(make_client, store):
    response = send(make_client(HONG, max_upload_bytes=10), "room1", "", ("big.zip", b"x" * 11, "application/zip"))

    assert response.headers["location"] == "/rooms/room1?error=too_large"
    assert store.files == {}


def test_huge_request_is_blocked_before_reading(make_client, store):
    client = make_client(HONG, max_upload_bytes=10)
    response = send(client, "room1", "", ("huge.zip", b"x" * (2 * 1024 * 1024), "application/zip"))

    assert response.headers["location"] == "/rooms/room1?error=too_large"
    assert store.files == {}


def test_html_file_is_download_only(make_client):
    client = make_client(HONG)
    send(client, "room1", "", ("page.html", b"<script>alert(1)</script>", "text/html"))

    file = client.get("/files/1")
    assert file.headers["content-type"] == "application/octet-stream"
    assert file.headers["content-disposition"].startswith("attachment")


def test_other_room_file_is_forbidden(make_client):
    send(make_client(HUR), "room1", "", ("비밀.png", b"secret", "image/png"))

    assert make_client(KWAK).get("/files/1").status_code == 403
    assert make_client().get("/files/1").status_code == 401
    assert make_client(HONG).get("/files/1").status_code == 200


# 개인·단체방

def test_guest_creates_personal_room_for_online_guest(make_shared, store):
    mina, yuri = guest("민아"), guest("유리")
    mina_client, yuri_client = make_shared(mina), make_shared(yuri)
    go_online(mina_client, yuri_client)

    room_id = create_room(mina_client, yuri)

    assert room_id in yuri_client.get("/rooms").text
    assert send(yuri_client, room_id, "초대 고마워요").status_code == 303
    assert "초대 고마워요" in mina_client.get(f"/rooms/{room_id}").text
    assert store.rooms[room_id]["owner_id"] == mina.uid


def test_cannot_invite_guest_who_is_not_online(make_shared, store):
    mina = make_shared(guest("민아"))
    go_online(mina)

    response = mina.post("/rooms", data={"members": ["g_없는사람"]}, follow_redirects=False)

    assert response.headers["location"] == "/rooms"
    assert store.rooms == {}


def test_outsiders_cannot_enter_custom_room(make_shared):
    mina, yuri, other = guest("민아"), guest("유리"), guest("제삼자")
    mina_client, yuri_client, other_client = make_shared(mina), make_shared(yuri), make_shared(other)
    go_online(mina_client, yuri_client)
    room_id = create_room(mina_client, yuri)
    send(mina_client, room_id, "둘만의 대화")

    assert other_client.get(f"/rooms/{room_id}").status_code == 403
    assert other_client.get(f"/rooms/{room_id}/messages").status_code == 403
    assert send(other_client, room_id, "끼어들기").status_code == 403
    assert make_shared(HUR).get(f"/rooms/{room_id}").status_code == 403


def test_only_creator_renames_room(make_shared, store):
    mina, yuri = guest("민아"), guest("유리")
    mina_client, yuri_client = make_shared(mina), make_shared(yuri)
    go_online(mina_client, yuri_client)
    room_id = create_room(mina_client, yuri, name="처음 이름")

    assert yuri_client.post(f"/rooms/{room_id}/rename", data={"name": "내가 바꿈"}).status_code == 403
    assert store.rooms[room_id]["name"] == "처음 이름"

    mina_client.post(f"/rooms/{room_id}/rename", data={"name": "새 이름"})
    assert store.rooms[room_id]["name"] == "새 이름"


def test_custom_room_files_are_not_cached_by_browser(make_shared):
    mina, yuri = guest("민아"), guest("유리")
    mina_client, yuri_client = make_shared(mina), make_shared(yuri)
    go_online(mina_client, yuri_client)
    room_id = create_room(mina_client, yuri)
    send(mina_client, room_id, "", ("사진.png", b"img", "image/png"))

    assert mina_client.get("/files/1").headers["cache-control"] == "private, no-store"


# 방 삭제

def test_creator_deletes_room_with_messages_and_files(make_shared, store):
    mina, yuri = guest("민아"), guest("유리")
    mina_client, yuri_client = make_shared(mina), make_shared(yuri)
    go_online(mina_client, yuri_client)
    room_id = create_room(mina_client, yuri)
    send(mina_client, room_id, "곧 사라질 대화")
    send(mina_client, room_id, "", ("사진.png", b"img", "image/png"))
    send(mina_client, "guest", "게스트방 대화")
    assert len(store.files) == 1

    response = mina_client.post(f"/rooms/{room_id}/delete", follow_redirects=False)

    assert response.headers["location"] == "/rooms"
    assert store.rooms == {}
    assert store.files == {}
    assert [m["body"] for m in store.messages] == ["게스트방 대화"]


def test_participant_sees_deleted_room_as_404(make_shared):
    mina, yuri = guest("민아"), guest("유리")
    mina_client, yuri_client = make_shared(mina), make_shared(yuri)
    go_online(mina_client, yuri_client)
    room_id = create_room(mina_client, yuri)
    mina_client.post(f"/rooms/{room_id}/delete")

    assert yuri_client.get(f"/rooms/{room_id}/messages?after=0").status_code == 404
    assert room_id not in yuri_client.get("/rooms").text


def test_only_creator_or_master_can_delete(make_shared, store):
    mina, yuri = guest("민아"), guest("유리")
    mina_client, yuri_client, hong = make_shared(mina), make_shared(yuri), make_shared(HONG)
    go_online(mina_client, yuri_client)
    room_id = create_room(mina_client, yuri)

    assert yuri_client.post(f"/rooms/{room_id}/delete").status_code == 403
    assert room_id in store.rooms

    response = hong.post(f"/rooms/{room_id}/delete", follow_redirects=False)
    assert response.headers["location"] == "/admin"
    assert store.rooms == {}


@pytest.mark.parametrize("room_id", ["room1", "room2", "guest"])
def test_fixed_rooms_cannot_be_deleted(make_client, store, room_id):
    send(make_client(HONG), "room1", "남아야 해요")

    assert make_client(HONG).post(f"/rooms/{room_id}/delete").status_code == 404
    assert len(store.messages) == 1


# 운영진(마스터)

def test_dashboard_is_master_only(make_shared):
    assert make_shared(guest("민아")).get("/admin").status_code == 403
    assert make_shared(HUR).get("/admin").status_code == 403
    assert make_shared().get("/admin", follow_redirects=False).headers["location"] == "/"


def test_dashboard_lists_online_guests_and_rooms(make_shared):
    mina, yuri = guest("민아"), guest("유리")
    mina_client, yuri_client, hong = make_shared(mina), make_shared(yuri), make_shared(HONG)
    go_online(mina_client, yuri_client)
    create_room(mina_client, yuri, name="비밀 모임")

    page = hong.get("/admin").text

    assert "민아" in page
    assert "유리" in page
    assert "비밀 모임" in page
    assert "개인" in page


def test_master_reads_every_room_but_cannot_write_in_others(make_shared, store):
    mina, yuri = guest("민아"), guest("유리")
    mina_client, yuri_client, hong = make_shared(mina), make_shared(yuri), make_shared(HONG)
    go_online(mina_client, yuri_client)
    room_id = create_room(mina_client, yuri)
    send(mina_client, room_id, "개인방 내용")
    send(mina_client, "guest", "게스트방 내용")

    assert "개인방 내용" in hong.get(f"/rooms/{room_id}").text
    assert "게스트방 내용" in hong.get("/rooms/guest").text
    assert "읽기 전용" in hong.get("/rooms/guest").text
    assert send(hong, "guest", "운영진 끼어들기").status_code == 403
    assert send(hong, room_id, "운영진 끼어들기").status_code == 403
    assert len(store.messages) == 2


def test_viewing_leaves_no_trace_for_participants(make_shared):
    mina, yuri = guest("민아"), guest("유리")
    mina_client, yuri_client, hong = make_shared(mina), make_shared(yuri), make_shared(HONG)
    go_online(mina_client, yuri_client)
    room_id = create_room(mina_client, yuri)
    hong.get(f"/rooms/{room_id}")

    assert mina_client.get(f"/rooms/{room_id}/messages?after=0").text.strip() == ""


def test_secret_message_reaches_only_its_recipient(make_shared, store):
    mina, yuri = guest("민아"), guest("유리")
    mina_client, yuri_client, hong = make_shared(mina), make_shared(yuri), make_shared(HONG)
    go_online(mina_client, yuri_client)

    hong.post("/admin/secret", data={"uid": mina.uid, "body": "민아에게만"})

    mina_view = mina_client.get("/rooms/guest/messages?after=0").text
    assert "민아에게만" in mina_view
    assert "secret" in mina_view
    assert "민아에게만" not in yuri_client.get("/rooms/guest").text
    assert "민아에게만" not in yuri_client.get("/rooms/guest/messages?after=0").text
    assert "민아에게만" in hong.get("/rooms/guest").text


def test_secret_message_needs_master_and_online_guest(make_shared, store):
    mina = make_shared(guest("민아"))
    hong = make_shared(HONG)
    go_online(mina)

    assert mina.post("/admin/secret", data={"uid": "g_민아", "body": "hi"}).status_code == 403
    hong.post("/admin/secret", data={"uid": "g_없는사람", "body": "hi"})
    assert store.messages == []


def test_muted_guest_is_rejected_with_remaining_time(make_shared, store):
    mina = guest("민아")
    mina_client, hong = make_shared(mina), make_shared(HONG)
    go_online(mina_client)

    hong.post("/admin/sanction", data={"uid": mina.uid, "action": "mute:5"})
    response = send(mina_client, "guest", "금지인데 보냄")

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/rooms/guest?error=muted&wait=")
    wait = int(location.rsplit("=", 1)[1])
    assert 290 <= wait <= 300
    assert store.messages == []

    page = mina_client.get(location).text
    assert "data-notice=" in page
    assert f"채팅이 금지되었습니다. 남은 시간: {wait // 60}분 {wait % 60}초" in page


def test_mute_applies_to_same_name_with_new_cookie(make_shared, store):
    mina = guest("민아")
    mina_client, hong = make_shared(mina), make_shared(HONG)
    go_online(mina_client)
    hong.post("/admin/sanction", data={"uid": mina.uid, "action": "mute:1"})

    returned = make_shared(Identity("guest", "민아", "g_new_cookie"))

    assert "error=muted" in send(returned, "guest", "이름만 같아요").headers["location"]
    assert send(make_shared(guest("다른사람")), "guest", "괜찮아요").headers["location"] == "/rooms/guest"


def test_mute_ends_when_time_is_over(make_shared, store):
    mina = guest("민아")
    mina_client, hong = make_shared(mina), make_shared(HONG)
    go_online(mina_client)
    hong.post("/admin/sanction", data={"uid": mina.uid, "action": "mute:1"})
    store.sanctions[0]["until"] = datetime.now(timezone.utc) - timedelta(seconds=1)

    assert send(mina_client, "guest", "이제 괜찮아").headers["location"] == "/rooms/guest"


def test_kicked_guest_is_sent_out_and_cannot_reenter(make_shared, make_client):
    mina = guest("민아")
    mina_client, hong = make_shared(mina), make_shared(HONG)
    go_online(mina_client)

    hong.post("/admin/sanction", data={"uid": mina.uid, "action": "kick"})

    poll = mina_client.get("/rooms/guest/messages?after=0")
    assert poll.status_code == 401
    assert poll.headers["x-reason"] == "kicked"
    assert mina_client.get("/rooms", follow_redirects=False).headers["location"] == "/"

    # 쿠키를 지우고 같은 이름으로 다시 들어오려 해도 막힌다.
    again = make_client().post("/guest", data={"name": "민아"})
    assert again.status_code == 403
    assert "다시 시도" in again.text
    assert make_client().post("/guest", data={"name": "다른이름"}, follow_redirects=False).status_code == 303


def test_kicked_guest_is_gone_from_dashboard(make_shared):
    mina = guest("민아")
    mina_client, hong = make_shared(mina), make_shared(HONG)
    go_online(mina_client)
    hong.post("/admin/sanction", data={"uid": mina.uid, "action": "kick"})

    assert "민아" not in hong.get("/admin").text


def test_sanctions_are_master_only_and_validated(make_shared, store):
    mina = guest("민아")
    mina_client, hong = make_shared(mina), make_shared(HONG)
    go_online(mina_client)

    assert mina_client.post("/admin/sanction", data={"uid": mina.uid, "action": "kick"}).status_code == 403
    assert make_shared(HUR).post("/admin/sanction", data={"uid": mina.uid, "action": "kick"}).status_code == 403
    assert hong.post("/admin/sanction", data={"uid": mina.uid, "action": "mute:7"}).status_code == 400
    assert hong.post("/admin/sanction", data={"uid": mina.uid, "action": "ban"}).status_code == 400
    assert store.sanctions == []


def test_members_are_never_sanctioned_through_guest_list(make_shared, store):
    hong = make_shared(HONG)
    make_shared(HUR).get("/rooms")

    hong.post("/admin/sanction", data={"uid": "허순태", "action": "kick"})

    assert store.sanctions == []


# 서버 깨어 있게 하기

def test_health_supports_get_and_head(make_client):
    client = make_client()

    assert client.get("/health").json() == {"status": "ok"}
    assert client.head("/health").status_code == 200
