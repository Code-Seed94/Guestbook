"""별도 템플릿 라이브러리 없이 HTML을 만드는 함수."""

from html import escape


def _entry_card(entry: dict) -> str:
    safe_name = escape(str(entry["name"]), quote=True)
    safe_message = escape(str(entry["message"]), quote=True).replace("\n", "<br>")
    safe_created_at = escape(str(entry["created_at"]).replace("T", " ")[:19])
    return f"""
    <article class="entry">
      <div class="entry-header">
        <strong>{safe_name}</strong>
        <time>{safe_created_at}</time>
      </div>
      <p>{safe_message}</p>
    </article>
    """


def render_page(
    entries: list[dict],
    *,
    error: str | None = None,
    form_name: str = "",
    form_message: str = "",
) -> str:
    """작성 폼과 방명록 목록을 하나의 HTML 문서로 반환한다."""
    error_html = ""
    if error:
        error_html = f'<p class="error" role="alert">{escape(error)}</p>'

    entry_html = "".join(_entry_card(entry) for entry in entries)
    if not entry_html:
        entry_html = '<p class="empty">아직 작성된 글이 없습니다. 첫 인사를 남겨주세요.</p>'

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>우리의 방명록</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <main class="container">
    <header class="hero">
      <p class="eyebrow">DAY 1—8 PROJECT</p>
      <h1>우리의 방명록</h1>
      <p>짧은 이름과 따뜻한 메시지를 남겨주세요.</p>
    </header>

    <section class="panel" aria-labelledby="write-title">
      <h2 id="write-title">글 남기기</h2>
      {error_html}
      <form action="/entries" method="post" accept-charset="utf-8">
        <label for="name">이름</label>
        <input id="name" name="name" type="text" minlength="1" maxlength="20"
               value="{escape(form_name, quote=True)}" required>

        <label for="message">메시지</label>
        <textarea id="message" name="message" rows="5" minlength="1"
                  maxlength="500" required>{escape(form_message)}</textarea>

        <button type="submit">방명록 남기기</button>
      </form>
    </section>

    <section class="entries" aria-labelledby="entries-title">
      <div class="section-title">
        <h2 id="entries-title">남겨진 이야기</h2>
        <span>{len(entries)}개 표시</span>
      </div>
      {entry_html}
    </section>
  </main>
</body>
</html>
"""
