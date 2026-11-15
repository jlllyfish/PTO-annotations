import json
from datetime import UTC, datetime

import httpx
import pytest

from app.dn.client import Action, DNClient, DNError, Operation, Statut

from .conftest import Recorder

URL = "https://demarche.numerique.gouv.fr/api/v2/graphql"


def node(n, labels=()):
    return {"id": f"RG9zc2llci0{n}", "number": n, "dateDerniereModification": "2026-11-15T16:05:35+01:00",
            "labels": [{"id": l} for l in labels]}


def page(nodes, next_cursor=None):
    return {"data": {"demarche": {"dossiers": {
        "pageInfo": {"hasNextPage": next_cursor is not None, "endCursor": next_cursor},
        "nodes": nodes}}}}


def client(handler, **kw):
    rec = Recorder(handler)
    return DNClient(URL, "secret", transport=rec.transport(), delai_base=0, **kw), rec


@pytest.mark.anyio
async def test_pagination_incrementale():
    def h(req):
        v = json.loads(req.content)["variables"]
        assert v["since"].startswith("2026-11-15")
        return httpx.Response(200, json=page([node(1), node(2, ["L1"])], "c1") if v["after"] is None
                              else page([node(3)]))
    dn, rec = client(h)
    res = await dn.dossiers_modifies(149930, datetime(2026, 11, 15, tzinfo=UTC))
    assert [d.numero for d in res] == [1, 2, 3]
    assert res[1].labels == {"L1"}
    assert [b["variables"]["after"] for b in rec.bodies()] == [None, "c1"]
    assert rec.requests[0].headers["authorization"] == "Bearer secret"


@pytest.mark.anyio
async def test_relecture_complete_par_etat_dedoublonnee():
    def h(req):
        etat = json.loads(req.content)["variables"]["state"]
        return httpx.Response(200, json=page([node(1)] if etat == "accepte" else [node(1), node(2)] if etat == "refuse" else []))
    dn, rec = client(h)
    res = await dn.tous_les_dossiers(1)
    assert sorted(d.numero for d in res) == [1, 2]
    assert len(rec.requests) == 5


@pytest.mark.anyio
async def test_lecture_ciblee_par_lots_de_25():
    def h(req):
        v = json.loads(req.content)["variables"]
        data = {f"d{k[1:]}": node(n) for k, n in v.items() if n != 999}
        return httpx.Response(200, json={"data": data})
    dn, rec = client(h)
    res = await dn.dossiers(list(range(1, 30)) + [999, 1])
    assert len(rec.requests) == 2
    assert sorted(d.numero for d in res) == list(range(1, 30))  # 999 introuvable ignoré, doublon retiré


@pytest.mark.anyio
async def test_mutations_statuts_par_operation():
    def h(req):
        body = json.loads(req.content)
        assert "dossierAjouterLabel" in body["query"]
        assert "D0" not in body["query"]  # les identifiants ne passent que par les variables
        return httpx.Response(200, json={
            "data": {
                "m0": {"dossier": {"labels": [{"id": "L"}]}, "errors": None},
                "m1": {"dossier": None, "errors": [{"message": "Ce label est déjà associé au dossier"}]},
                "m2": None,
                "m3": {"dossier": None, "errors": [{"message": "Dossier archivé"}]},
            },
            "errors": [{"message": "DossierAjouterLabelPayload not found", "path": ["m2"]}],
        })
    dn, _ = client(h)
    ops = [Operation(f"D{k}", "L") for k in range(4)]
    res = await dn.appliquer(Action.AJOUTER, ops)
    assert [r.statut for r in res] == [Statut.APPLIQUE, Statut.DEJA_APPLIQUE, Statut.ERREUR, Statut.ERREUR]
    assert res[0].labels_apres == {"L"}
    assert "not found" in res[2].message
    assert res[3].message == "Dossier archivé"


@pytest.mark.anyio
async def test_retrait_deja_absent():
    def h(req):
        return httpx.Response(200, json={"data": {"m0": {"dossier": None, "errors": [
            {"message": "Ce label n’est pas associé au dossier"}]}}})
    dn, _ = client(h)
    res = await dn.appliquer(Action.RETIRER, [Operation("D", "L")])
    assert res[0].statut == Statut.DEJA_APPLIQUE


@pytest.mark.anyio
async def test_mutations_par_lots_de_50():
    def h(req):
        n = len(json.loads(req.content)["variables"])
        return httpx.Response(200, json={"data": {f"m{k}": {"dossier": {"labels": []}, "errors": None} for k in range(n)}})
    dn, rec = client(h)
    res = await dn.appliquer(Action.RETIRER, [Operation(f"D{k}", "L") for k in range(120)])
    assert len(res) == 120 and all(r.statut == Statut.APPLIQUE for r in res)
    assert sorted(len(b["variables"]) for b in rec.bodies()) == [20, 50, 50]


@pytest.mark.anyio
async def test_nouvelle_tentative_sur_429():
    calls = iter([httpx.Response(429, headers={"retry-after": "0"}),
                  httpx.Response(200, json={"data": {"demarche": {"labels": [{"id": "L", "name": "Urgent", "color": "pink_macaron"}]}}})])
    dn, rec = client(lambda req: next(calls))
    labels = await dn.catalogue(1)
    assert labels[0].nom == "Urgent" and len(rec.requests) == 2


@pytest.mark.anyio
async def test_acces_refuse():
    dn, _ = client(lambda req: httpx.Response(403, json={"errors": [{"message": "forbidden network"}]}))
    with pytest.raises(DNError) as e:
        await dn.catalogue(1)
    assert e.value.status == 403 and "forbidden network" in str(e.value)
    assert "secret" not in str(e.value)


@pytest.mark.anyio
async def test_erreur_reseau_lot_ne_bloque_pas():
    dn, _ = client(lambda req: httpx.Response(500), tentatives=1)
    res = await dn.appliquer(Action.AJOUTER, [Operation("D", "L")])
    assert res[0].statut == Statut.ERREUR
