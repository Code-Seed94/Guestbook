"""별도 템플릿 라이브러리 없이 비둘기 서비스 화면을 만드는 함수."""

from datetime import datetime, timedelta, timezone
from html import escape


KST = timezone(timedelta(hours=9))

ERROR_MESSAGES = {
    "empty": "메시지를 입력하거나 파일을 골라 주세요.",
    "too_long": "메시지는 1000자까지 보낼 수 있어요.",
    "too_large": "파일은 {limit}까지 보낼 수 있어요.",
    "blocked": "실행 파일은 보낼 수 없어요.",
    "empty_file": "빈 파일은 보낼 수 없어요.",
    "storage_full": "저장 공간이 가득 찼어요.",
}

STATUS_MESSAGES = {
    401: "로그인이 필요해요.",
    403: "이 대화방에는 들어갈 수 없어요.",
    404: "찾는 페이지가 없어요.",
}

LOGO = '<span class="logo" aria-hidden="true">🕊️</span>'


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


def _bubble(message: dict, user: str) -> str:
    mine = message["sender"] == user
    sender = "" if mine else f'<span class="sender">{escape(message["sender"])}</span>'
    parts = []
    if message.get("file_path"):
        parts.append(_attachment(message))
    if message.get("body"):
        text = escape(message["body"]).replace("\r\n", "\n").replace("\n", "<br>")
        parts.append(f"<p>{text}</p>")
    return f"""<article class="msg {'mine' if mine else 'theirs'}" data-id="{int(message['id'])}">
  {sender}
  <div class="msg-row">
    <div class="bubble">{''.join(parts)}</div>
    <time datetime="{escape(message['created_at'], quote=True)}">{_time_label(message['created_at'])}</time>
  </div>
</article>
"""


def render_messages(messages: list[dict], user: str) -> str:
    """말풍선 HTML 조각. 첫 화면과 3초 새로고침에서 함께 쓴다."""
    return "".join(_bubble(message, user) for message in messages)


def render_login(users: tuple[str, ...], *, error: str | None = None, selected: str = "") -> str:
    error_html = f'<p class="alert" role="alert">{escape(error)}</p>' if error else ""
    placeholder = "" if selected in users else " selected"
    options = "".join(
        f'<option value="{escape(name, quote=True)}"{" selected" if name == selected else ""}>{escape(name)}</option>'
        for name in users
    )
    body = f"""<main class="center">
  <section class="card">
    <div class="brand">{LOGO}<h1>비둘기 서비스</h1></div>
    <p class="tagline">우리끼리 주고받는 작은 편지함</p>
    {error_html}
    <form class="form" action="/login" method="post">
      <label for="name">이름</label>
      <select id="name" name="name" required>
        <option value="" disabled{placeholder}>이름을 선택하세요</option>
        {options}
      </select>
      <label for="password">비밀번호</label>
      <input id="password" name="password" type="password" inputmode="numeric"
             autocomplete="current-password" required>
      <button class="btn-primary" type="submit">들어가기</button>
    </form>
  </section>
</main>"""
    return _page("로그인", body)


def render_rooms(user: str, rooms: list[tuple[str, str]]) -> str:
    items = "".join(
        f"""<li><a href="/rooms/{escape(room_id, quote=True)}">
          <span class="avatar">{escape(partner[0])}</span>
          <span><strong>{escape(partner)}</strong><small>{escape(user)} ↔ {escape(partner)}</small></span>
        </a></li>"""
        for room_id, partner in rooms
    )
    body = f"""<main class="center">
  <section class="card">
    <div class="brand">{LOGO}<h1>비둘기 서비스</h1></div>
    <p class="tagline">{escape(user)}님, 어느 대화방으로 갈까요?</p>
    <ul class="room-list">{items}</ul>
    <form class="card-footer" action="/logout" method="post">
      <span>{escape(user)}님으로 접속 중</span>
      <button class="text-btn" type="submit">로그아웃</button>
    </form>
  </section>
</main>"""
    return _page("대화방 목록", body)


def render_chat(
    user: str,
    room_id: str,
    partner: str,
    messages: list[dict],
    *,
    used_bytes: int,
    storage_limit: int,
    max_upload_bytes: int,
    can_go_back: bool,
    error: str | None = None,
) -> str:
    error_html = ""
    if error in ERROR_MESSAGES:
        text = ERROR_MESSAGES[error].format(limit=_size(max_upload_bytes))
        error_html = f'<p class="alert" role="alert">{escape(text)}</p>'

    back = '<a class="icon-btn" href="/rooms" aria-label="대화방 목록">‹</a>' if can_go_back else ""
    message_html = render_messages(messages, user) or '<p class="empty">아직 주고받은 메시지가 없어요.<br>첫 소식을 날려 보세요 🕊️</p>'
    safe_room = escape(room_id, quote=True)

    body = f"""<div class="chat-app">
  <header class="chat-header">
    {back}
    <span class="avatar">{escape(partner[0])}</span>
    <div class="chat-title"><strong>{escape(partner)}</strong><span>{escape(user)}님으로 접속 중</span></div>
    <form action="/logout" method="post"><button class="text-btn" type="submit">로그아웃</button></form>
  </header>

  <section id="messages" class="messages" data-room="{safe_room}" aria-live="polite">
    {message_html}
  </section>

  <form class="composer" action="/rooms/{safe_room}/messages" method="post" enctype="multipart/form-data">
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
  </form>
</div>"""
    return _page(f"{partner}님과의 대화", body, with_script=True)


def render_error(status_code: int) -> str:
    message = STATUS_MESSAGES.get(status_code, "잠시 후 다시 시도해 주세요.")
    body = f"""<main class="center">
  <section class="card">
    <div class="brand">{LOGO}<h1>비둘기 서비스</h1></div>
    <p class="tagline">{escape(message)}</p>
    <a class="btn-primary" href="/">처음으로</a>
  </section>
</main>"""
    return _page("안내", body)
