import json

import httpx
import pytest

from app.config import AppConfig

DOC = "AbCdEfGh1234"
BASE = f"https://grist.numerique.gouv.fr/o/mon-organisation/api/docs/{DOC}"
TOKEN = "tok_" + "a" * 40


@pytest.fixture(autouse=True)
def secrets(monkeypatch):
    monkeypatch.setenv("DN_TOKEN_TEST", "dn-secret")
    monkeypatch.setenv("GRIST_SERVICE_KEY", "grist-secret")


@pytest.fixture
def config() -> AppConfig:
    return AppConfig.model_validate({
        "documents": [{
            "grist_doc_id": DOC,
            "nom": "Test",
            "demarches": [{"numero": 149930, "nom": "Western Pony Club", "dn_token": "DN_TOKEN_TEST"}],
        }]
    })


class Recorder:
    """Transport httpx factice qui enregistre les requêtes et délègue à un handler."""

    def __init__(self, handler):
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def _h(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self.handler(request)
        return httpx.MockTransport(_h)

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.content]


@pytest.fixture
def anyio_backend():
    return "asyncio"
