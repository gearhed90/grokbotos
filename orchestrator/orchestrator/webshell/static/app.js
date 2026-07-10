const state = {
  choices: [],
  status: { connected: false },
};

let pollTimer = null;

async function fetchJSON(url, opts) {
  const res = await fetch(url, opts);
  return res.json();
}

async function loadChoices() {
  const data = await fetchJSON('/api/choices');
  state.choices = data.choices;
  renderLlmIcons();
}

async function loadApps() {
  const data = await fetchJSON('/api/apps');
  const row = document.getElementById('app-icons');
  row.innerHTML = '';
  if (data.apps.length === 0) {
    const empty = document.createElement('span');
    empty.className = 'icon-empty';
    empty.textContent = '아직 설치된 프로그램이 없습니다';
    row.appendChild(empty);
    return;
  }
  for (const app of data.apps) {
    const el = document.createElement('div');
    el.className = 'icon app-icon';
    el.title = app.description;
    el.innerHTML = `<div class="icon-glyph">${app.name.slice(0, 1)}</div><div class="icon-label">${app.name}</div>`;
    row.appendChild(el);
  }
}

function renderLlmIcons() {
  const row = document.getElementById('llm-icons');
  row.innerHTML = '';
  for (const choice of state.choices) {
    const el = document.createElement('div');
    el.className = 'icon llm-icon';
    el.dataset.id = choice.id;
    el.innerHTML = `<div class="icon-glyph">${choice.label.slice(0, 1)}</div><div class="icon-label">${choice.label}</div>`;
    el.addEventListener('click', () => onLlmIconClick(choice));
    row.appendChild(el);
  }
  applyStatusToIcons();
}

function applyStatusToIcons() {
  document.querySelectorAll('.llm-icon').forEach((el) => {
    const id = el.dataset.id;
    el.classList.toggle('connected', state.status.connected && state.status.choice_id === id);
    el.classList.toggle('connecting', state.status.connecting === id);
  });
}

function onLlmIconClick(choice) {
  if (state.status.connected || state.status.connecting) return;
  if (choice.id === 'custom') {
    document.getElementById('connect-panel').hidden = false;
    document.getElementById('custom-panel').hidden = false;
    document.getElementById('token-panel').hidden = true;
    document.getElementById('connect-status').textContent = '연결할 CLI 정보를 입력하세요.';
    return;
  }
  startConnect(choice.id);
}

async function startConnect(providerId, extra) {
  document.getElementById('connect-panel').hidden = false;
  document.getElementById('custom-panel').hidden = true;
  document.getElementById('token-panel').hidden = true;
  document.getElementById('connect-status').textContent = '연결 중... 브라우저 로그인이 열리면 완료해주세요.';
  await fetchJSON('/api/connect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider: providerId, ...extra }),
  });
  poll();
}

document.getElementById('custom-submit').addEventListener('click', () => {
  const cliBinary = document.getElementById('custom-cli').value.trim();
  if (!cliBinary) return;
  const loginCommand = document.getElementById('custom-login').value.trim() || `${cliBinary} login`;
  const installRaw = document.getElementById('custom-install').value.trim();
  startConnect('custom', {
    cli_binary: cliBinary,
    login_command: loginCommand,
    install_argv: installRaw ? installRaw.split(/\s+/) : null,
  });
});

document.getElementById('token-submit').addEventListener('click', async () => {
  const token = document.getElementById('token-input').value.trim();
  if (!token) return;
  document.getElementById('connect-status').textContent = '토큰 확인 중...';
  await fetchJSON('/api/connect-token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider: 'claude', token }),
  });
  poll();
});

async function poll() {
  const status = await fetchJSON('/api/status');
  state.status = status;
  applyStatusToIcons();

  const promptInput = document.getElementById('prompt-input');
  const promptSubmit = document.getElementById('prompt-submit');
  const connectPanel = document.getElementById('connect-panel');
  const connectStatus = document.getElementById('connect-status');
  const tokenPanel = document.getElementById('token-panel');

  if (status.connected) {
    promptInput.disabled = false;
    promptSubmit.disabled = false;
    promptInput.placeholder = '무엇을 도와드릴까요?';
    connectPanel.hidden = true;
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    return;
  }

  promptInput.disabled = true;
  promptSubmit.disabled = true;
  promptInput.placeholder = 'LLM 연결 후 사용할 수 있습니다';

  if (status.error) {
    connectPanel.hidden = false;
    connectStatus.textContent = `연결 실패: ${status.error}`;
    tokenPanel.hidden = !status.needs_token;
  } else if (status.connecting) {
    connectPanel.hidden = false;
    connectStatus.textContent = '연결 중... 브라우저 로그인이 열리면 완료해주세요.';
  }

  if (!pollTimer) {
    pollTimer = setInterval(poll, 1500);
  }
}

document.getElementById('prompt-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const input = document.getElementById('prompt-input');
  const text = input.value.trim();
  if (!text) return;
  const resultEl = document.getElementById('result');
  resultEl.textContent = '처리 중...';
  const data = await fetchJSON('/api/prompt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
  if (data.status === 'needs_clarification') {
    resultEl.textContent = '추가 정보가 필요합니다: ' + data.questions.join(', ');
  } else if (data.status === 'error') {
    resultEl.textContent = '오류: ' + data.message;
  } else {
    resultEl.textContent = data.message;
  }
  input.value = '';
});

loadChoices();
loadApps();
poll();
