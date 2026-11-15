import asyncio
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import sync_routes
from app.config import AppConfig
from app.main import create_app
from app.sync.service import Bilan

from .conftest import BASE, TOKEN, Recorder

AUTH = {"Authorization": f"Bearer {TOKEN}", "X-Grist-Base-Url": BASE}


def grist_handler(r: httpx.Request) -> httpx.Response:
    if r.url.path.endswith("/tables"):
        return httpx.Response(200, json={"tables": [{"id": "LBL_Etat"}]})
    if r.url.path.endswith("/sql"):
        return httpx.Response(200, json={"records": [{"fields": {"demarche": 149930, "statut": "ok"}}]})
    return httpx.Response(404)


def make_client(config):
    app = create_app(config, dn_transport=Recorder(lambda r: httpx.Response(500)).transport(),
                     grist_transport=Recorder(grist_handler).transport())
    return TestClient(app, base_url="https://testserver")


@pytest.fixture
def faux_sync(monkeypatch):
    appels = []

    async def fake(dn, grist, d, mode, *, cle_schema, numeros=None, progression=None, maintenant=None):
        appels.append((d.numero, mode, numeros))
        if progression:
            progression.lus(3)
        if getattr(fake, "bloquer", None):
            await fake.bloquer.wait()
        return Bilan(d.numero, mode, dossiers_lus=3, dossiers_maj=1)

    monkeypatch.setattr(sync_routes, "synchroniser", fake)

    async def fausse_vidange(grist, d, jours, *, cle_schema, maintenant=None):
        appels.append(("vidange", d.numero, jours))
        return 2

    monkeypatch.setattr(sync_routes, "vidange_automatique", fausse_vidange)
    fake.appels = appels
    return fake


@pytest.mark.parametrize("body", [
    {"mode": "ciblee"},
    {"mode": "incrementale", "numeros": [1]},
    {"mode": "ciblee", "numeros": list(range(1, 502))},
    {"mode": "ciblee", "numeros": [0]},
    {"mode": "tout"},
    {"mode": "complete", "inconnu": 1},
])
def test_validation(config, faux_sync, body):
    with make_client(config) as c:
        assert c.post("/api/demarches/149930/synchro", headers=AUTH, json=body).status_code == 422


def test_lancer_puis_suivre(config, faux_sync):
    with make_client(config) as c:
        r = c.post("/api/demarches/149930/synchro", headers=AUTH, json={"mode": "ciblee", "numeros": [5, 6]})
        assert r.status_code == 202 and r.json()["tache"]["statut"] == "en_cours"
        for _ in range(50):
            etat = c.get("/api/demarches/149930/synchro", headers=AUTH).json()
            if etat["tache"]["statut"] != "en_cours":
                break
            time.sleep(0.01)
        assert etat["tache"]["statut"] == "ok" and etat["tache"]["bilan"]["dossiers_maj"] == 1
        assert etat["derniere"]["statut"] == "ok"
        assert faux_sync.appels == [(149930, "ciblee", [5, 6])]


def test_une_seule_synchro_a_la_fois(config, faux_sync):
    with make_client(config) as c:
        c.portal.call(lambda: setattr(faux_sync, "bloquer", asyncio.Event()))
        assert c.post("/api/demarches/149930/synchro", headers=AUTH, json={}).status_code == 202
        assert c.post("/api/demarches/149930/synchro", headers=AUTH, json={}).status_code == 409
        c.portal.call(faux_sync.bloquer.set)


def test_sans_jeton(config, faux_sync):
    with make_client(config) as c:
        assert c.post("/api/demarches/149930/synchro", json={}).status_code == 401
        assert faux_sync.appels == []


def test_tache_desactivee_sans_secret(config, faux_sync):
    with make_client(config) as c:
        assert c.post("/api/taches/synchro").status_code == 404


@pytest.fixture
def config_taches(config, monkeypatch):
    monkeypatch.setenv("LBL_TASK_TOKEN", "s3cret-n8n")
    return AppConfig.model_validate({**config.model_dump(mode="json"), "task_token": "LBL_TASK_TOKEN"})


def test_tache_secret_invalide(config_taches, faux_sync):
    with make_client(config_taches) as c:
        assert c.post("/api/taches/synchro", headers={"Authorization": "Bearer faux"}).status_code == 401
        assert c.post("/api/taches/synchro").status_code == 401
        assert faux_sync.appels == []


def test_tache_planifiee(config_taches, faux_sync):
    with make_client(config_taches) as c:
        r = c.post("/api/taches/synchro?mode=complete", headers={"Authorization": "Bearer s3cret-n8n"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] and body["resultats"][0]["statut"] == "ok"
        assert faux_sync.appels == [(149930, "complete", None), ("vidange", 149930, 30)]
        assert body["resultats"][0]["bilan"]["journal_purge"] == 2
        assert c.post("/api/taches/synchro?mode=ciblee", headers={"Authorization": "Bearer s3cret-n8n"}).status_code == 422
