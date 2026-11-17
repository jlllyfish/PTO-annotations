import json
from datetime import UTC, datetime, timedelta

import pytest

from app.config import DemarcheConfig
from app.dn.client import DNError
from app.grist.client import GristError
from app.sync import schema
from app.sync.service import Mode, Progression, champs_otp, synchroniser

from .fakes import CATALOGUE, FakeDN, FakeGrist

D = DemarcheConfig(numero=149930, nom="Test", dn_token="DN_TOKEN_TEST")
T = D.table
T0 = datetime(2026, 11, 15, 16, 0, tzinfo=UTC)
CAT = {l.id: l for l in CATALOGUE}


@pytest.fixture(autouse=True)
def reset_schema_cache():
    schema._deja_verifie.clear()


def otp(ids):
    """Valeurs telles qu'OTP les écrit."""
    f = champs_otp(ids, CAT)
    return f["label_names"], f["labels_json"]


def grist_initial():
    g = FakeGrist()
    g.creer_otp(149930, [
        ("1", *otp(["LA"])),          # inchangé
        ("2", "", ""),                 # DN : Urgent ajouté
        ("3", *otp(["LA", "LR"])),    # DN : À relancer retiré
        ("4", "x", "pas du json"),     # illisible → réécrit
    ])
    return g


async def run(dn, g, mode, **kw):
    return await synchroniser(dn, g, D, mode, cle_schema="doc", maintenant=kw.pop("maintenant", T0), **kw)


@pytest.mark.anyio
async def test_premiere_synchro_complete_ecrit_seulement_les_ecarts():
    g = grist_initial()
    dn = FakeDN({1: {"LA"}, 2: {"LU"}, 3: {"LA"}, 4: set(), 99: {"LA"}})
    prog = Progression()
    bilan = await run(dn, g, Mode.INCREMENTALE, progression=prog)  # pas d'état → bascule en complète

    assert bilan.mode == Mode.COMPLETE and dn.appels == [("complete",)]
    assert sorted(bilan.numeros_maj) == ["2", "3", "4"]
    assert bilan.absents_grist == 1  # dossier 99 pas encore importé par OTP
    assert prog.dossiers_lus == 5 and prog.etape == "terminé"
    assert [e for e in g.ecritures if e[1] == T] == [("maj", T, 3)]

    lignes = {r["dossier_number"]: r for r in g.rows(T)}
    assert lignes["2"]["label_names"] == "Urgent"
    assert json.loads(lignes["2"]["labels_json"]) == [{"id": "LU", "name": "Urgent", "color": "pink_macaron"}]
    assert (lignes["3"]["label_names"], lignes["4"]["labels_json"]) == ("À examiner", "")

    etat = g.rows("LBL_Etat")[0]
    assert etat["statut"] == "ok" and etat["curseur"] == T0.timestamp() and etat["derniere_complete"] == T0.timestamp()
    assert len(g.rows("LBL_Catalogue")) == 3


@pytest.mark.anyio
async def test_format_identique_a_otp():
    names, js = otp(["LA", "LU"])
    assert names == "À examiner, Urgent"
    assert js == ('[{"id": "LA", "name": "À examiner", "color": "purple_glycine"}, '
                  '{"id": "LU", "name": "Urgent", "color": "pink_macaron"}]')


@pytest.mark.anyio
async def test_incrementale_depuis_le_curseur_avec_marge():
    g = grist_initial()
    dn = FakeDN({1: {"LA"}, 2: {"LU"}, 3: {"LA"}, 4: set()})
    await run(dn, g, Mode.COMPLETE)
    dn.etat[1] = {"LA", "LR"}
    dn.modifies = [1]
    bilan = await run(dn, g, Mode.INCREMENTALE, maintenant=T0 + timedelta(minutes=5))
    assert dn.appels[-1] == ("incrementale", T0 - timedelta(minutes=2))
    assert bilan.mode == Mode.INCREMENTALE and bilan.numeros_maj == ["1"]
    assert g.rows("LBL_Etat")[0]["curseur"] == (T0 + timedelta(minutes=5)).timestamp()


@pytest.mark.anyio
async def test_ordre_different_non_reecrit():
    g = FakeGrist()
    g.creer_otp(149930, [("1", *otp(["LU", "LA"]))])  # ordre différent du catalogue
    bilan = await run(FakeDN({1: {"LA", "LU"}}), g, Mode.COMPLETE)
    assert bilan.dossiers_maj == 0


@pytest.mark.anyio
async def test_ciblee_ne_deplace_pas_le_curseur():
    g = grist_initial()
    dn = FakeDN({1: {"LA"}, 2: {"LU"}, 3: {"LA"}, 4: set()})
    await run(dn, g, Mode.COMPLETE)
    dn.etat[2] = set()
    bilan = await run(dn, g, Mode.CIBLEE, numeros=[2, 777], maintenant=T0 + timedelta(hours=1))
    assert dn.appels[-1] == ("ciblee", (2, 777)) and bilan.numeros_maj == ["2"]
    assert g.rows("LBL_Etat")[0]["curseur"] == T0.timestamp()


@pytest.mark.anyio
async def test_label_supprime_dans_dn_desactive_au_catalogue():
    g = grist_initial()
    dn = FakeDN({1: {"LA"}})
    await run(dn, g, Mode.COMPLETE)
    dn.cat = CATALOGUE[:2]
    await run(dn, g, Mode.COMPLETE)
    actifs = {r["label_id"]: r["actif"] for r in g.rows("LBL_Catalogue")}
    assert actifs == {"LA": 1, "LR": 1, "LU": 0}


@pytest.mark.anyio
async def test_erreur_dn_enregistree():
    g = grist_initial()
    dn = FakeDN({})
    dn.erreur = DNError("Accès refusé par DN (HTTP 403)")
    with pytest.raises(DNError):
        await run(dn, g, Mode.COMPLETE)
    etat = g.rows("LBL_Etat")[0]
    assert etat["statut"] == "erreur" and "403" in etat["message"]


@pytest.mark.anyio
async def test_table_otp_absente():
    with pytest.raises(GristError, match="OTP"):
        await run(FakeDN({}), FakeGrist(), Mode.COMPLETE)


@pytest.mark.anyio
async def test_schema_complete_colonnes_manquantes():
    g = grist_initial()
    await g.creer_table("LBL_Etat", [("demarche", "Int")])
    await run(FakeDN({1: {"LA"}}), g, Mode.COMPLETE)
    assert "curseur" in g.types["LBL_Etat"]


@pytest.mark.anyio
async def test_groupes_instructeurs_memorises():
    g = grist_initial()
    dn = FakeDN({1: {"LA"}, 2: set(), 3: set()})
    dn.groupe_de = {1: 394761}
    b = await run(dn, g, Mode.COMPLETE)
    groupes = {r["dossier_number"]: (r["groupe"], r["groupe_libelle"]) for r in g.rows("LBL_Groupes_Dossiers")}
    assert b.groupes_maj == 3 and groupes["1"] == (394761, "G394761") and groupes["2"] == (394762, "G394762")
    # réaffectation d'un dossier, disparition d'un autre : seuls les écarts sont écrits
    dn.groupe_de = {1: 394762}
    del dn.etat[3]
    b = await run(dn, g, Mode.COMPLETE)
    groupes = {r["dossier_number"]: r["groupe"] for r in g.rows("LBL_Groupes_Dossiers")}
    assert b.groupes_maj == 1 and groupes == {"1": 394762, "2": 394762}
