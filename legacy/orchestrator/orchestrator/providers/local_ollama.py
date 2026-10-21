"""Local model provider backed by Ollama (docs/DECISIONS.md: "로컬 LLM을
선택하면 바로 필요한 로컬 LLM을 다운로드받고 설치되게 해줘야함").

Uses Ollama's HTTP API (http://localhost:11434 -- Ollama's documented
default) for listing installed models and generating completions, and the
`ollama pull` CLI command for installation, since pulling is a long-running
streamed operation the CLI already handles well.

This is real, working logic -- not a stub -- but it needs an actual Ollama
install to exercise, which this dev sandbox doesn't have (see
docs/LOCAL_SETUP.md). `http_get`/`http_post`/`run` are injected so the
control flow (not-installed -> pull -> ready, daemon-unreachable, etc.) can
still be unit tested without one.
"""

from __future__ import annotations

import json
import subprocess
import urllib.request
from typing import Callable

from .base import LLMProvider, ModelNotInstalled, ProviderNotReady, ProviderStatus

_DEFAULT_BASE_URL = "http://localhost:11434"

HttpGet = Callable[[str], dict]
HttpPost = Callable[[str, dict], dict]
Runner = Callable[[list[str]], subprocess.CompletedProcess]


def _real_http_get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 - fixed localhost endpoint
        return json.loads(resp.read().decode())


def _real_http_post(url: str, body: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - fixed localhost endpoint
        return json.loads(resp.read().decode())


def _real_run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, check=False)


class OllamaProvider(LLMProvider):
    provider_id = "ollama"

    def __init__(
        self,
        model_id: str,
        base_url: str = _DEFAULT_BASE_URL,
        http_get: HttpGet = _real_http_get,
        http_post: HttpPost = _real_http_post,
        run: Runner = _real_run,
        log: Callable[[str], None] | None = None,
    ):
        self.model_id = model_id
        self._base_url = base_url
        self._http_get = http_get
        self._http_post = http_post
        self._run = run
        self._log: Callable[[str], None] = log or (lambda _msg: None)

    def status(self) -> ProviderStatus:
        try:
            tags = self._http_get(f"{self._base_url}/api/tags")
        except Exception:  # noqa: BLE001 - daemon not reachable/installed
            return ProviderStatus.ERROR

        installed = {m.get("name", "") for m in tags.get("models", [])}
        if any(name == self.model_id or name.startswith(f"{self.model_id}:") for name in installed):
            return ProviderStatus.READY
        return ProviderStatus.MODEL_NOT_INSTALLED

    def ensure_ready(self) -> None:
        current = self.status()
        if current is ProviderStatus.READY:
            return

        if current is ProviderStatus.ERROR:
            self._log(f"[ollama] 데몬에 연결할 수 없음 ({self._base_url})")
            raise ModelNotInstalled(
                self.provider_id,
                self.model_id,
                detail=(
                    f"Ollama daemon not reachable at {self._base_url}. "
                    "Is it installed and running? See docs/LOCAL_SETUP.md."
                ),
            )

        self._log(f"[ollama] 모델 다운로드 중: ollama pull {self.model_id} (시간이 걸릴 수 있습니다)")
        result = self._run(["ollama", "pull", self.model_id])
        if result.returncode != 0:
            self._log(f"[ollama] pull 실패 (종료 코드 {result.returncode})")
            raise ModelNotInstalled(
                self.provider_id,
                self.model_id,
                detail=f"'ollama pull {self.model_id}' failed: {result.stderr.strip()}",
            )

        if self.status() is not ProviderStatus.READY:
            self._log("[ollama] pull은 성공했지만 모델이 목록에 안 보임")
            raise ModelNotInstalled(
                self.provider_id,
                self.model_id,
                detail="pull reported success but model still not visible in 'ollama list'",
            )
        self._log(f"[ollama] 준비 완료: {self.model_id}")

    def complete_json(self, prompt: str, schema: dict) -> dict:
        if self.status() is not ProviderStatus.READY:
            raise ProviderNotReady(f"{self.provider_id}: call ensure_ready() first")

        schema_instruction = (
            "\n\nRespond with ONLY valid JSON matching this schema, no other text:\n"
            + json.dumps(schema)
        )
        resp = self._http_post(
            f"{self._base_url}/api/generate",
            {
                "model": self.model_id,
                "prompt": prompt + schema_instruction,
                "format": "json",
                "stream": False,
            },
        )
        return json.loads(resp["response"])
