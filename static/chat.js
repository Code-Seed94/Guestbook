// 3초마다 새 메시지만 받아와 목록 끝에 붙인다. 화면 전체를 새로고침하지 않아 깜빡이지 않는다.
(() => {
  const list = document.getElementById("messages");
  const form = document.querySelector(".composer");
  if (!list || !form) return;

  const room = list.dataset.room;
  const textarea = form.querySelector("textarea");
  const fileInput = form.querySelector('input[type="file"]');
  const fileName = document.getElementById("file-name");
  let stick = true; // 사용자가 맨 아래를 보고 있으면 새 메시지가 올 때 따라 내려간다.

  const toBottom = () => { list.scrollTop = list.scrollHeight; };
  const lastId = () => {
    const items = list.querySelectorAll(".msg[data-id]");
    return items.length ? items[items.length - 1].dataset.id : 0;
  };

  list.addEventListener("scroll", () => {
    stick = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
  });
  // 사진이 늦게 로드되어 높이가 바뀌어도 맨 아래를 유지한다.
  list.addEventListener("load", () => { if (stick) toBottom(); }, true);

  async function poll() {
    if (!document.hidden) {
      try {
        const response = await fetch(`/rooms/${room}/messages?after=${lastId()}`, { cache: "no-store" });
        if (response.status === 401) {
          location.href = "/";
          return;
        }
        const html = response.ok ? (await response.text()).trim() : "";
        if (html) {
          list.querySelector(".empty")?.remove();
          const follow = stick;
          list.insertAdjacentHTML("beforeend", html);
          if (follow) toBottom();
        }
      } catch {
        // 잠깐 연결이 끊겨도 다음 주기에 다시 시도한다.
      }
    }
    setTimeout(poll, 3000);
  }

  // Enter는 전송, Shift+Enter는 줄바꿈. 한글 조합 중에는 전송하지 않는다.
  textarea.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    if (textarea.value.trim() || fileInput.files.length) form.requestSubmit();
  });

  fileInput.addEventListener("change", () => {
    fileName.textContent = fileInput.files[0] ? `📎 ${fileInput.files[0].name}` : "";
  });

  // 전송 버튼을 두 번 눌러 같은 메시지가 두 번 가는 것을 막는다.
  form.addEventListener("submit", () => {
    form.querySelector(".send").disabled = true;
  });

  toBottom();
  setTimeout(poll, 3000);
})();
