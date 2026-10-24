"""비둘기 서비스의 사용자, 대화방 권한, 로그인 쿠키.

누가 어디에 들어갈 수 있고 무엇을 할 수 있는지는 모두 이 파일에서 정한다.
"""

import base64
from dataclasses import dataclass
import hashlib
import hmac
import secrets
import time


MASTER = "홍록기"
MEMBERS = ("허순태", "곽승현")
USERS = (MASTER, *MEMBERS)

# 정해진 대화방마다 들어갈 수 있는 두 사람
ROOMS = {
    "room1": ("허순태", "홍록기"),
    "room2": ("곽승현", "홍록기"),
}

# 게스트 전원이 함께 쓰는 방
GUEST_ROOM = "guest"

# 마스터가 게스트에게 줄 수 있는 제재 시간
KICK_MINUTES = 60
MUTE_MINUTES = (1, 5, 10, 30)

SESSION_COOKIE = "pigeon_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7


# 구조: 사람을 role·name·uid 한 값으로 표현 / 이유: 클래스를 나누지 않아 분기가 role 비교 한 줄
@dataclass(frozen=True)
class Identity:
    """로그인한 사람. uid는 메시지 주인을 구분하는 값이다(게스트는 이름이 같아도 uid가 다르다)."""

    role: str  # "member" | "master" | "guest"
    name: str
    uid: str


def new_guest(name: str) -> Identity:
    return Identity("guest", name, "g_" + secrets.token_hex(8))


def check_login(
    name: str, password: str, app_password: str, master_password: str
) -> Identity | None:
    """아이디와 비밀번호가 맞으면 Identity를, 아니면 None을 반환한다."""
    if name == MASTER:
        expected, role = master_password, "master"
    elif name in MEMBERS:
        expected, role = app_password, "member"
    else:
        return None
    if not expected or not hmac.compare_digest(password.encode(), expected.encode()):
        return None
    return Identity(role, name, name)


def rooms_for(user: str) -> list[str]:
    """정해진 대화방 중 사용자가 들어갈 수 있는 방 id 목록을 반환한다."""
    return [room_id for room_id, members in ROOMS.items() if user in members]


def room_partner(user: str, room_id: str) -> str:
    """정해진 대화방에서 나를 뺀 상대방 이름을 반환한다."""
    return next(member for member in ROOMS[room_id] if member != user)


def is_custom_room(room_id: str) -> bool:
    """게스트가 만든 개인·단체방인지 여부. 이 방만 삭제할 수 있다."""
    return room_id not in ROOMS and room_id != GUEST_ROOM


# 구조: 방 접근 규칙을 이 함수 하나에 모음 / 이유: 규칙이 흩어지지 않고 DB 없이 테스트 가능
def room_access(who: Identity, room_id: str, room: dict | None = None) -> str | None:
    """"write"(읽고 쓰기), "read"(읽기만), None(들어갈 수 없음).

    room은 개인·단체방일 때만 필요하다: {"owner_id": ..., "members": [{"uid": ...}, ...]}
    """
    if room_id in ROOMS:
        return "write" if who.uid in ROOMS[room_id] else None
    if room_id == GUEST_ROOM:
        return {"guest": "write", "master": "read"}.get(who.role)
    if room is None:
        return None
    if who.uid in [member["uid"] for member in room["members"]]:
        return "write"
    return "read" if who.role == "master" else None


# 구조: 나머지 권한도 한 줄짜리 함수로 나열 / 이유: 함수 이름만 읽으면 규칙을 알 수 있음
def can_see(who: Identity, message: dict) -> bool:
    """비밀 메시지는 받는 사람과 마스터에게만 보인다."""
    target = message.get("private_to")
    return not target or who.role == "master" or who.uid == target


def can_delete_room(who: Identity, room: dict) -> bool:
    """마스터는 모든 개인·단체방을, 게스트는 자기가 만든 방만 삭제할 수 있다."""
    return who.role == "master" or who.uid == room["owner_id"]


def can_rename_room(who: Identity, room: dict) -> bool:
    return who.uid == room["owner_id"]


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


# 구조: 쿠키에 정보를 hmac 서명해서 담음 / 이유: 세션 테이블·새 라이브러리 없이 위조 방지
def make_session(who: Identity, secret: str, now: float | None = None) -> str:
    """역할·이름·uid와 발급 시각에 서명을 붙인 쿠키 값을 만든다."""
    issued_at = int(time.time() if now is None else now)
    payload = f"{who.role}.{_encode(who.name)}.{_encode(who.uid)}.{issued_at}"
    return f"{payload}.{_sign(payload, secret)}"


def read_session(value: str, secret: str, now: float | None = None) -> Identity | None:
    """서명과 유효기간이 맞으면 Identity를, 아니면 None을 반환한다."""
    try:
        role, name, uid, issued_at, signature = value.split(".")
        if not hmac.compare_digest(signature, _sign(f"{role}.{name}.{uid}.{issued_at}", secret)):
            return None
        current = time.time() if now is None else now
        if current - int(issued_at) > SESSION_MAX_AGE:
            return None
        who = Identity(
            role, base64.urlsafe_b64decode(name).decode(), base64.urlsafe_b64decode(uid).decode()
        )
    except (ValueError, UnicodeDecodeError):
        return None
    if who.role == "guest":
        return who if who.uid.startswith("g_") else None
    if who.role == "master":
        return who if who.name == who.uid == MASTER else None
    return who if who.role == "member" and who.name == who.uid and who.name in MEMBERS else None
