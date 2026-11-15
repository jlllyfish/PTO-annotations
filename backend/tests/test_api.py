import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app

from .conftest import BASE, DOC, TOKEN, Recorder


@pytest.fixture
def api(config):
    grist = Recorder(lambda r: httpx.Response(200, json={"tables": []}))
    dn = Recorder(lambda r: httpx.Response(200, json={"data": {"demarche": {"labels": [
        {"id": "TGFiZWwtNTAzOTAy", "name": "Urgent", "color": "pink_macaron"}]}}}))
    app = create_app(config, dn_transport=dn.transport(), grist_transport=grist.transport())
    with TestClient(app, base_url="https://testserver") as c:
        c.dn = dn
        yield c


AUTH = {"Authorization": f"Bearer {TOKEN}", "X-Grist-Base-Url": BASE}


def test_health_et_entetes(api):
    r = api.get("/health")
    assert r.json() == {"ok": True}
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-type"] == "application/json; charset=utf-8"


def test_widget_csp(api):
    r = api.get("/widget/")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "frame-ancestors https://grist.numerique.gouv.fr" in csp
    assert "'unsafe-inline'" not in csp


def test_docs_desactivees(api):
    assert api.get("/docs").status_code == 404
    assert api.get("/openapi.json").status_code == 404


def test_contexte_sans_jeton(api):
    assert api.get("/api/contexte").status_code == 401


def test_contexte_document_inconnu(api):
    r = api.get("/api/contexte", headers={**AUTH, "X-Grist-Base-Url": BASE.replace(DOC, "AutreDoc1234")})
    assert r.status_code == 403


def test_contexte(api):
    r = api.get("/api/contexte", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["demarches"] == [{"numero": 149930, "nom": "Western Pony Club", "table": "Demarche_149930_dossiers"}]


def test_catalogue(api):
    r = api.get("/api/demarches/149930/catalogue", headers=AUTH)
    assert r.json()["labels"][0] == {"id": "TGFiZWwtNTAzOTAy", "nom": "Urgent", "couleur": "pink_macaron"}
    assert api.dn.requests[0].headers["authorization"] == "Bearer dn-secret"


def test_catalogue_demarche_hors_document(api):
    assert api.get("/api/demarches/150021/catalogue", headers=AUTH).status_code == 404
    assert api.dn.requests == []


def test_corps_trop_gros(api):
    r = api.post("/api/contexte", headers={**AUTH, "Content-Length": str(10**7)}, content=b"x")
    assert r.status_code == 413


@pytest.mark.parametrize("body", [
    {"action": "ajouter", "label_id": "TGFiZWwtNTAzOTAy", "numeros": []},
    {"action": "ajouter", "label_id": "TGFiZWwtNTAzOTAy", "numeros": list(range(1, 502))},
    {"action": "supprimer", "label_id": "TGFiZWwtNTAzOTAy", "numeros": [1]},
    {"action": "ajouter", "label_id": "x\"){ evil }", "numeros": [1]},
    {"action": "ajouter", "label_id": "TGFiZWwtNTAzOTAy", "numeros": [1], "source": "regle"},
])
def test_operations_validation(api, body):
    assert api.post("/api/demarches/149930/operations", headers=AUTH, json=body).status_code == 422
    assert api.dn.requests == []


def test_operations_sans_jeton(api):
    body = {"action": "ajouter", "label_id": "TGFiZWwtNTAzOTAy", "numeros": [1]}
    assert api.post("/api/demarches/149930/operations", json=body).status_code == 401


def test_apercu_label_inconnu(api):
    body = {"action": "ajouter", "label_id": "TGFiZWwtOTk5", "numeros": [1]}
    r = api.post("/api/demarches/149930/operations/apercu", headers=AUTH, json=body)
    assert r.status_code == 422 and "n'existe pas" in r.json()["detail"]
