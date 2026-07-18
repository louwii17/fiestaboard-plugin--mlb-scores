from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def fixture():
    def load(name: str):
        path = Path(__file__).parent / "fixtures" / f"{name}.json"
        return json.loads(path.read_text())

    return load


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return FakeResponse(payload)


@pytest.fixture
def fake_session():
    return FakeSession
