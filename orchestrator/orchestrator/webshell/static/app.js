// Every tile below is a thin wrapper around submitPrompt() -- clicking
// "Claude 연결" and typing "/llm claude" + Enter produce the exact same
// POST /api/prompt request. There is no separate click-handling API; that
// unification is the point (see docs/DECISIONS.md).

const state = { status: { connected: false } };
let pollTimer = null;

const COMMAND_TILES = [
  { id: "llm-claude", label: "Claude 연결", command: "/llm claude", submit: true, kind: "llm", providerId: "claude" },
  { id: "llm-grok", label: "Grok 연결", command: "/llm grok", submit: true, kind: "llm", providerId: "grok" },
  { id: "llm-ollama", label: "로컬 모델 (Ollama)", command: "/llm ollama", submit: true, kind: "llm", providerId: "ollama" },
  { id: "llm-custom", label: "기타 LLM 연결", command: "/llm custom ", submit: false, kind: "llm", providerId: "custom" },
  { id: "system", label: "시스템 설정", command: "/system", submit: true, kind: "system" },
  { id: "cli", label: "CLI 터미널", command: "/cli", submit: true, kind: "cli" },
];

async function fetchJSON(url, opts) {
  const res = await fetch(url, opts);
  return res.json();
}

function makeTile(kind, providerId, label, onClick) {
  const el = document.createElement("div");
  el.className = `tile tile-${kind}`;
  if (providerId) el.dataset.providerId = providerId;
  el.innerHTML = `<div class="tile-thumb"><span>${label.slice(0, 1)}</span></div><div class="tile-label">${label}</div>`;
  el.addEventListener("click", onClick);
  return el;
}

function renderCommandTiles() {
  const grid = document.getElementById("command-tiles");
  grid.innerHTML = "";
  for (const tile of COMMAND_TILES) {
    grid.appendChild(
      makeTile(tile.kind, tile.providerId, tile.label, () => onTileClick(tile))
    );
  }
  applyStatusToTiles();
}

function onTileClick(tile) {
  if (tile.submit) {
    submitPrompt(tile.command);
  } else {
    const input = document.getElementById("prompt-input");
    input.value = tile.command;
    input.focus();
  }
}

async function loadApps() {
  const data = await fetchJSON("/api/apps");
  const grid = document.getElementById("app-tiles");
  grid.innerHTML = "";
  if (data.apps.length === 0) {
    const empty = document.createElement("p");
    empty.className = "tile-empty";
    empty.textContent = "아직 설치된 프로그램이 없습니다.";
    grid.appendChild(empty);
    return;
  }
  for (const app of data.apps) {
    const tile = makeTile("app", null, app.name, () => submitPrompt(app.name));
    tile.title = app.description;
    grid.appendChild(tile);
  }
}

function applyStatusToTiles() {
  document.querySelectorAll(".tile-llm").forEach((el) => {
    const id = el.dataset.providerId;
    el.classList.toggle("connected", state.status.connected && state.status.choice_id === id);
    el.classList.toggle("connecting", state.status.connecting === id);
  });
}

function setPromptStatus() {
  const el = document.getElementById("prompt-status");
  if (state.status.connected) {
    el.textContent = `연결됨: ${state.status.choice_id}`;
  } else if (state.status.connecting) {
    el.textContent = `연결 중: ${state.status.connecting}...`;
  } else if (state.status.error) {
    el.textContent = `연결 실패: ${state.status.error}`;
  } else {
    el.textContent = "연결된 LLM 없음 -- /llm 으로 연결하세요";
  }
}

async function poll() {
  const status = await fetchJSON("/api/status");
  state.status = status;
  applyStatusToTiles();
  setPromptStatus();

  if (status.connecting && !pollTimer) {
    pollTimer = setInterval(poll, 1500);
  } else if (!status.connecting && pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function showResult(data) {
  const resultEl = document.getElementById("result");
  resultEl.hidden = false;
  if (data.status === "needs_clarification") {
    resultEl.textContent = "추가 정보가 필요합니다: " + data.questions.join(", ");
  } else if (data.status === "error") {
    resultEl.textContent = "오류: " + data.message;
  } else {
    resultEl.textContent = data.message;
  }
}

async function submitPrompt(rawText) {
  const text = rawText.trim();
  if (!text) return;
  document.getElementById("prompt-input").value = "";
  const data = await fetchJSON("/api/prompt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  showResult(data);
  poll();
}

document.getElementById("prompt-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  submitPrompt(document.getElementById("prompt-input").value);
});

document.getElementById("prompt-input").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) {
    ev.preventDefault();
    document.getElementById("prompt-form").requestSubmit();
  }
});

renderCommandTiles();
loadApps();
poll();
