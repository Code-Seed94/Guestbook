"""비둘기 서비스의 사용자, 대화방 권한, 로그인 쿠키."""

import base64
import hashlib
import hmac
import time


USERS = ("홍록기", "허순태", "곽승현")

# 대화방마다 들어갈 수 있는 두 사람
ROOMS = {
    "room1": ("허순태", "홍록기"),
    "room2": ("곽승현", "홍록기"),
}

SESSION_COOKIE = "pigeon_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7


def check_login(name: str, password: str, expected_password: str) -> bool:
    """허용된 이름이고 비밀번호가 맞을 때만 True를 반환한다."""
    if name not in USERS or not expected_password:
        return False
    return hmac.compare_digest(password.encode(), expected_password.encode())


def rooms_for(user: str) -> list[str]:
    """사용자가 들어갈 수 있는 대화방 id 목록을 반환한다."""
    return [room_id for room_id, members in ROOMS.items() if user in members]


def can_enter(user: str, room_id: str) -> bool:
    return user in ROOMS.get(room_id, ())


def room_partner(user: str, room_id: str) -> str:
    """대화방에서 나를 뺀 상대방 이름을 반환한다."""
    return next(member for member in ROOMS[room_id] if member != user)


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_session(user: str, secret: str, now: float | None = None) -> str:
    """이름과 발급 시각에 서명을 붙인 쿠키 값을 만든다."""
    issued_at = int(time.time() if now is None else now)
    encoded_name = base64.urlsafe_b64encode(user.encode()).decode()
    payload = f"{encoded_name}.{issued_at}"
    return f"{payload}.{_sign(payload, secret)}"


def read_session(value: str, secret: str, now: float | None = None) -> str | None:
    """서명과 유효기간이 맞으면 사용자 이름을, 아니면 None을 반환한다."""
    try:
        encoded_name, issued_at, signature = value.split(".")
        expected = _sign(f"{encoded_name}.{issued_at}", secret)
        if not hmac.compare_digest(signature, expected):
            return None
        current = time.time() if now is None else now
        if current - int(issued_at) > SESSION_MAX_AGE:
            return None
        user = base64.urlsafe_b64decode(encoded_name).decode()
    except (ValueError, UnicodeDecodeError):
        return None
    return user if user in USERS else None
