"""별도 템플릿 라이브러리 없이 비둘기 서비스 화면을 만드는 함수."""

from datetime import datetime, timedelta, timezone
from html import escape

from auth import Identity, MUTE_MINUTES


KST = timezone(timedelta(hours=9))

ERROR_MESSAGES = {
    "empty": "메시지를 입력하거나 파일을 골라 주세요.",
    "too_long": "메시지는 1000자까지 보낼 수 있어요.",
    "too_large": "파일은 {limit}까지 보낼 수 있어요.",
    "blocked": "실행 파일은 보낼 수 없어요.",
    "empty_file": "빈 파일은 보낼 수 없어요.",
    "storage_full": "저장 공간이 가득 찼어요.",
    "bad_name": "방 이름은 1~30자로 입력해 주세요.",
}

STATUS_MESSAGES = {
    401: "로그인이 필요해요.",
    403: "이 대화방에는 들어갈 수 없어요.",
    404: "찾는 페이지가 없어요.",
}

LOGO = '<span class="logo" aria-hidden="true">🕊️</span>'
CONFIRM_DELETE = "return confirm('삭제하면 복구할 수 없습니다.')"


# 구조: 문자열 조립 함수로 화면 생성 / 이유: 의존성이 없고 함수 하나가 화면 하나
def _page(title: str, body: str, *, with_script: bool = False) -> str:
    script = '<script src="/static/chat.js" defer></script>' if with_script else ""
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{escape(title)} · 비둘기 서비스</title>
  <link rel="stylesheet" href="/static/style.css">
  {script}
</head>
<body>
{body}
</body>
</html>
"""


def _size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes}B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f}KB"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / 1024 / 1024:.1f}MB"
    return f"{num_bytes / 1024 / 1024 / 1024:.1f}GB"


def _time_label(created_at: str) -> str:
    """UTC 저장 시각을 한국 시간 '10.23 오후 3:05' 형식으로 바꾼다."""
    moment = datetime.fromisoformat(created_at).astimezone(KST)
    period = "오전" if moment.hour < 12 else "오후"
    hour = moment.hour % 12 or 12
    return f"{moment.month}.{moment.day} {period} {hour}:{moment.minute:02d}"


def _attachment(message: dict) -> str:
    url = f"/files/{int(message['id'])}"
    name = escape(message.get("file_name") or "첨부 파일", quote=True)
    kind = (message.get("file_type") or "").split("/")[0]
    if kind == "image":
        return f'<a href="{url}" target="_blank" rel="noopener"><img src="{url}" alt="{name}" loading="lazy"></a>'
    if kind == "audio":
        return f'<audio controls preload="none" src="{url}"></audio>'
    if kind == "video":
        return f'<video controls preload="metadata" src="{url}"></video>'
    size = _size(message.get("file_size") or 0)
    return f'<a class="file" href="{url}"><span class="file-icon">📎</span><span class="file-name">{name}</span><small>{size}</small></a>'


def _bubble(message: dict, uid: str) -> str:
    mine = message.get("sender_id") == uid
    secret = bool(message.get("private_to"))
    sender = "" if mine else f'<span class="sender">{escape(message["sender"])}</span>'
    parts = []
    if secret:
        parts.append('<small class="secret-tag">🔒 비밀 메시지</small>')
    if message.get("file_path"):
        parts.append(_attachment(message))
    if message.get("body"):
        text = escape(message["body"]).replace("\r\n", "\n").replace("\n", "<br>")
        parts.append(f"<p>{text}</p>")
    classes = f"msg {'mine' if mine else 'theirs'}{' secret' if secret else ''}"
    return f"""<article class="{classes}" data-id="{int(message['id'])}">
  {sender}
  <div class="msg-row">
    <div class="bubble">{''.join(parts)}</div>
    <time datetime="{escape(message['created_at'], quote=True)}">{_time_label(message['created_at'])}</time>
  </div>
</article>
"""


# 구조: 첫 화면과 3초 새로고침이 같은 함수 사용 / 이유: 말풍선을 한 곳만 고치면 됨
def render_messages(messages: list[dict], uid: str) -> str:
    """말풍선 HTML 조각. 첫 화면과 3초 새로고침에서 함께 쓴다."""
    return "".join(_bubble(message, uid) for message in messages)


def _alert(error: str | None) -> str:
    return f'<p class="alert" role="alert">{escape(error)}</p>' if error else ""


def render_login(*, error: str | None = None, name: str = "") -> str:
    body = f"""<main class="center">
  <section class="card">
    <div class="brand">{LOGO}<h1>비둘기 서비스</h1></div>
    <p class="tagline">우리끼리 주고받는 작은 편지함</p>
    {_alert(error)}
    <form class="form" action="/login" method="post">
      <label for="name">아이디</label>
      <input id="name" name="name" type="text" value="{escape(name, quote=True)}"
             autocomplete="username" required>
      <label for="password">비밀번호</label>
      <input id="password" name="password" type="password"
             autocomplete="current-password" required>
      <button class="btn-primary" type="submit">입장하기</button>
    </form>
    <button class="btn-secondary" type="button" id="guest-open">Guest 입장</button>
    <p class="fine-print">운영진은 채팅방 내용을 확인할 수 있습니다</p>
  </section>
</main>

<dialog id="guest-dialog" class="dialog">
  <form class="form" action="/guest" method="post">
    <label for="guest-name">Guest 입장</label>
    <input id="guest-name" name="name" type="text" maxlength="20"
           placeholder="본인의 이름을 입력해 주세요" autocomplete="off" required>
    <div class="dialog-actions">
      <button class="text-btn" type="button" id="guest-cancel">취소</button>
      <button class="btn-primary" type="submit">입장</button>
    </div>
  </form>
</dialog>
<script>
  const dialog = document.getElementById("guest-dialog");
  document.getElementById("guest-open").addEventListener("click", () => dialog.showModal());
  document.getElementById("guest-cancel").addEventListener("click", () => dialog.close());
</script>"""
    return _page("로그인", body)


def render_rooms(
    who: Identity,
    rooms: list[tuple[str, str, str]],
    *,
    online: list[tuple[str, str]] | None = None,
    show_admin: bool = False,
) -> str:
    """rooms는 (방 id, 제목, 설명) 목록. online을 주면 새 대화방 만들기 칸을 함께 보여준다."""
    items = "".join(
        f"""<li><a href="/rooms/{escape(room_id, quote=True)}">
          <span class="avatar">{escape(title[0])}</span>
          <span><strong>{escape(title)}</strong><small>{escape(subtitle)}</small></span>
        </a></li>"""
        for room_id, title, subtitle in rooms
    )
    admin = '<a class="btn-secondary" href="/admin">운영진 대시보드</a>' if show_admin else ""
    return _page("대화방 목록", f"""<main class="center">
  <section class="card">
    <div class="brand">{LOGO}<h1>비둘기 서비스</h1></div>
    <p class="tagline">{escape(who.name)}님, 어느 대화방으로 갈까요?</p>
    <ul class="room-list">{items}</ul>
    {admin}
    {_create_room_form(online) if online is not None else ""}
    <form class="card-footer" action="/logout" method="post">
      <span>{escape(who.name)}님으로 접속 중</span>
      <button class="text-btn" type="submit">로그아웃</button>
    </form>
  </section>
</main>""")


def _create_room_form(online: list[tuple[str, str]]) -> str:
    if online:
        choices = "".join(
            f'<label class="check"><input type="checkbox" name="members" value="{escape(uid, quote=True)}"> {escape(name)}</label>'
            for uid, name in online
        )
        action = '<button class="btn-primary" type="submit">만들기</button>'
    else:
        choices = '<p class="fine-print">지금 접속 중인 다른 게스트가 없어요.</p>'
        action = ""
    return f"""<form class="form create-room" action="/rooms" method="post">
      <h2>새 대화방</h2>
      <p class="fine-print">1명을 고르면 개인방, 2명 이상 고르면 단체방이에요.</p>
      {choices}
      <label for="room-name">방 이름 (비워 두면 참여자 이름)</label>
      <input id="room-name" name="name" type="text" maxlength="30">
      {action}
    </form>"""


def render_chat(
    who: Identity,
    room_id: str,
    title: str,
    subtitle: str,
    messages: list[dict],
    *,
    used_bytes: int,
    storage_limit: int,
    max_upload_bytes: int,
    can_go_back: bool,
    can_write: bool = True,
    can_rename: bool = False,
    can_delete: bool = False,
    error: str | None = None,
    notice: str | None = None,
) -> str:
    error_html = ""
    if error in ERROR_MESSAGES:
        text = ERROR_MESSAGES[error].format(limit=_size(max_upload_bytes))
        error_html = f'<p class="alert" role="alert">{escape(text)}</p>'

    back = '<a class="icon-btn" href="/rooms" aria-label="대화방 목록">‹</a>' if can_go_back else ""
    message_html = render_messages(messages, who.uid) or '<p class="empty">아직 주고받은 메시지가 없어요.<br>첫 소식을 날려 보세요 🕊️</p>'
    safe_room = escape(room_id, quote=True)
    notice_attr = f' data-notice="{escape(notice, quote=True)}"' if notice else ""

    menu = ""
    if can_rename or can_delete:
        rename = f"""<form action="/rooms/{safe_room}/rename" method="post">
        <input name="name" type="text" maxlength="30" value="{escape(title, quote=True)}" aria-label="방 이름" required>
        <button class="text-btn" type="submit">이름 변경</button>
      </form>""" if can_rename else ""
        delete = f"""<form action="/rooms/{safe_room}/delete" method="post" onsubmit="{CONFIRM_DELETE}">
        <button class="text-btn danger" type="submit">방 삭제</button>
      </form>""" if can_delete else ""
        menu = f"""<details class="room-menu">
      <summary aria-label="방 설정">⋯</summary>
      <div class="menu-panel">{rename}{delete}</div>
    </details>"""

    if can_write:
        footer = f"""<form class="composer" action="/rooms/{safe_room}/messages" method="post" enctype="multipart/form-data">
    {error_html}
    <div class="composer-row">
      <label class="attach" title="파일 첨부">
        <span aria-hidden="true">📎</span>
        <input class="visually-hidden" type="file" name="upload" aria-label="파일 첨부">
      </label>
      <textarea name="body" rows="1" maxlength="1000" placeholder="메시지를 입력하세요"></textarea>
      <button class="send" type="submit">전송</button>
    </div>
    <p class="composer-meta">
      <span id="file-name"></span>
      <span>파일당 {_size(max_upload_bytes)} · 사용량 {_size(used_bytes)} / {_size(storage_limit)}</span>
    </p>
  </form>"""
    else:
        footer = '<p class="read-only">읽기 전용으로 보고 있어요.</p>'

    body = f"""<div class="chat-app"{notice_attr}>
  <header class="chat-header">
    {back}
    <span class="avatar">{escape(title[0])}</span>
    <div class="chat-title"><strong>{escape(title)}</strong><span>{escape(subtitle)}</span></div>
    {menu}
    <form action="/logout" method="post"><button class="text-btn" type="submit">로그아웃</button></form>
  </header>

  <section id="messages" class="messages" data-room="{safe_room}" aria-live="polite">
    {message_html}
  </section>

  {footer}
</div>"""
    return _page(f"{title}", body, with_script=True)


def render_admin(
    guests: list[tuple[str, str]],
    rooms: list[dict],
    fixed_rooms: list[tuple[str, str]],
) -> str:
    """마스터 대시보드. guests는 접속 중인 게스트 (uid, 이름), fixed_rooms는 열람 링크 (방 id, 제목)."""
    sanction_buttons = (
        '<button class="text-btn danger" name="action" value="kick" type="submit">강퇴 1시간</button>'
        + "".join(
            f'<button class="text-btn" name="action" value="mute:{minutes}" type="submit">채팅 금지 {minutes}분</button>'
            for minutes in MUTE_MINUTES
        )
    )
    guest_items = "".join(
        f"""<li class="admin-item">
        <strong>{escape(name)}</strong>
        <form class="inline-form" action="/admin/secret" method="post">
          <input type="hidden" name="uid" value="{escape(uid, quote=True)}">
          <input name="body" type="text" maxlength="1000" placeholder="비밀 메시지" required>
          <button class="text-btn" type="submit">보내기</button>
        </form>
        <form class="inline-form" action="/admin/sanction" method="post">
          <input type="hidden" name="uid" value="{escape(uid, quote=True)}">
          {sanction_buttons}
        </form>
      </li>"""
        for uid, name in guests
    ) or '<li class="fine-print">지금 접속 중인 게스트가 없어요.</li>'

    fixed_items = "".join(
        f'<li class="admin-item"><a href="/rooms/{escape(room_id, quote=True)}">{escape(title)}</a></li>'
        for room_id, title in fixed_rooms
    )
    room_items = "".join(
        f"""<li class="admin-item">
        <a href="/rooms/{escape(room['id'], quote=True)}">{escape(room['name'])}</a>
        <small>{'개인' if len(room['members']) == 2 else '단체'} · {escape(', '.join(m['name'] for m in room['members']))}</small>
        <form action="/rooms/{escape(room['id'], quote=True)}/delete" method="post" onsubmit="{CONFIRM_DELETE}">
          <button class="text-btn danger" type="submit">방 삭제</button>
        </form>
      </li>"""
        for room in rooms
    ) or '<li class="fine-print">만들어진 개인·단체방이 없어요.</li>'

    body = f"""<main class="admin">
  <header class="admin-header">
    <a class="icon-btn" href="/rooms" aria-label="대화방 목록">‹</a>
    <h1>운영진 대시보드</h1>
    <form action="/logout" method="post"><button class="text-btn" type="submit">로그아웃</button></form>
  </header>
  <section class="card wide"><h2>접속 중인 게스트</h2><ul class="admin-list">{guest_items}</ul></section>
  <section class="card wide"><h2>대화방 열람 (읽기 전용)</h2><ul class="admin-list">{fixed_items}</ul></section>
  <section class="card wide"><h2>개인·단체방</h2><ul class="admin-list">{room_items}</ul></section>
</main>"""
    return _page("운영진 대시보드", body)


def render_error(status_code: int, message: str | None = None) -> str:
    message = message or STATUS_MESSAGES.get(status_code, "잠시 후 다시 시도해 주세요.")
    body = f"""<main class="center">
  <section class="card">
    <div class="brand">{LOGO}<h1>비둘기 서비스</h1></div>
    <p class="tagline">{escape(message)}</p>
    <a class="btn-primary" href="/">처음으로</a>
  </section>
</main>"""
    return _page("안내", body)
