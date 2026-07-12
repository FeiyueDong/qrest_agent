from __future__ import annotations

import urllib.error

import pytest

from qrest_agent.llm import clients


class FailingUrlOpen:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, request, timeout):  # type: ignore[no-untyped-def]
        self.calls += 1
        raise urllib.error.URLError("socket blocked")


def test_post_json_retries_and_reports_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    failing = FailingUrlOpen()
    monkeypatch.setattr(clients.urllib.request, "urlopen", failing)
    monkeypatch.setattr(clients.time, "sleep", lambda seconds: None)

    with pytest.raises(RuntimeError) as exc_info:
        clients._post_json("http://localhost:11434/api/chat", {"model": "x"}, retries=2, timeout=1)

    assert failing.calls == 3
    assert "attempt=3/3" in str(exc_info.value)
