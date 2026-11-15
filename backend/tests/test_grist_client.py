import json

import httpx
import pytest

from app.grist.client import GristClient, GristError, ident

from .conftest import BASE, TOKEN, Recorder


@pytest.mark.parametrize("bad", ['x"; DROP TABLE y; --', "1abc", "", "a b", "a" * 101])
def test_ident_refuse(bad):
    with pytest.raises(ValueError):
        ident(bad)


def test_ident_ok():
    assert ident("Demarche_149930_dossiers") == '"Demarche_149930_dossiers"'


@pytest.mark.anyio
async def test_upsert_par_lots_avec_cles():
    rec = Recorder(lambda r: httpx.Response(200, json={}))
    async with GristClient.par_cle("grist.numerique.gouv.fr", "AbCdEfGh1234", "k", transport=rec.transport()) as g:
        n = await g.upsert("LBL_Operations", [{"dossier_number": str(i), "label_id": "L", "statut": "x"} for i in range(1200)],
                           ["dossier_number", "label_id"])
    assert n == 1200
    assert [len(b["records"]) for b in rec.bodies()] == [500, 500, 200]
    first = rec.bodies()[0]["records"][0]
    assert first == {"require": {"dossier_number": "0", "label_id": "L"}, "fields": {"statut": "x"}}
    assert rec.requests[0].method == "PUT"
    assert rec.requests[0].headers["authorization"] == "Bearer k"


@pytest.mark.anyio
async def test_sql_parametre_et_jeton_en_parametre():
    def h(r):
        assert r.url.params["auth"] == TOKEN
        body = json.loads(r.content)
        assert body["args"] == ["en_instruction"]
        return httpx.Response(200, json={"records": [{"fields": {"n": 3}}]})
    rec = Recorder(h)
    async with GristClient.par_jeton(BASE, TOKEN, transport=rec.transport()) as g:
        rows = await g.sql('SELECT COUNT(*) AS n FROM "T" WHERE state = ?', ["en_instruction"])
    assert rows == [{"n": 3}]


@pytest.mark.anyio
async def test_erreur_grist():
    rec = Recorder(lambda r: httpx.Response(400, json={"error": "only select statements are supported"}))
    async with GristClient.par_jeton(BASE, TOKEN, transport=rec.transport()) as g:
        with pytest.raises(GristError) as e:
            await g.sql("DELETE FROM x")
    assert e.value.status == 400
    assert TOKEN not in str(e.value)


@pytest.mark.anyio
async def test_supprimer_par_lots():
    rec = Recorder(lambda r: httpx.Response(200, json={}))
    async with GristClient.par_jeton(BASE, TOKEN, transport=rec.transport()) as g:
        assert await g.supprimer("LBL_Operations", list(range(1, 1101))) == 1100
    assert [b[0][0] for b in rec.bodies()] == ["BulkRemoveRecord"] * 3
    assert [len(b[0][2]) for b in rec.bodies()] == [500, 500, 100]
    with pytest.raises(ValueError):
        await GristClient.par_jeton(BASE, TOKEN).supprimer('x"; --', [1])
