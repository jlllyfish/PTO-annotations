import json

import pytest

from app.regles import service
from app.regles.moteur import Condition, DefinitionRegle, RegleInvalide, champs_disponibles, compiler
from app.sync import schema
from app.sync.service import champs_otp

from .fakes import CATALOGUE, FakeDN, FakeGrist
from .test_sync import D

JOUR = 86400
NOW = 2_000_000_000
CAT = {l.id: l for l in CATALOGUE}


@pytest.fixture(autouse=True)
def reset_schema_cache():
    schema._deja_verifie.clear()


def js(ids):
    return champs_otp(ids, CAT)["labels_json"]


def document():
    g = FakeGrist()
    g.creer_table_otp("Demarche_149930_dossiers", [
        ("dossier_number", "Text"), ("state", "Choice"), ("date_depot", "DateTime:Europe/Paris"),
        ("label_names", "Text"), ("labels_json", "Text")], [
        {"dossier_number": "1", "state": "en_construction", "date_depot": NOW - 40 * JOUR, "labels_json": js(["LA"])},
        {"dossier_number": "2", "state": "en_construction", "date_depot": NOW - 5 * JOUR, "labels_json": ""},
        {"dossier_number": "3", "state": "accepte", "date_depot": NOW - 90 * JOUR, "labels_json": js(["LU"])},
        {"dossier_number": "4", "state": "en_instruction", "date_depot": NOW - 60 * JOUR, "labels_json": ""},
    ])
    g.creer_table_otp("Demarche_149930_champs", [("dossier_number", "Text"), ("commune", "Text"), ("budget", "Numeric")], [
        {"dossier_number": "1", "commune": "Auch", "budget": 1500}, {"dossier_number": "2", "commune": "100%_bio", "budget": 0},
        {"dossier_number": "3", "commune": "Albi", "budget": 9000}, {"dossier_number": "4", "commune": None, "budget": None},
    ])
    g.creer_table_otp("Demarche_149930_annotations", [("dossier_number", "Text"), ("relance", "Bool"), ("pj", "Attachments")], [
        {"dossier_number": "4", "relance": 1},
    ])
    return g


def regle(*groupes, action="ajouter", label="LR", **kw):
    return DefinitionRegle(nom="Test", action=action, label_id=label,
                           groupes=[[Condition(champ=c, operateur=o, valeur=v) for c, o, v in g] for g in groupes], **kw)


async def numeros(g, r):
    champs = await champs_disponibles(g, D)
    sql, args = compiler(D, r, champs, NOW)
    return sorted(row["dossier_number"] for row in await g.sql(sql, args))


@pytest.mark.anyio
async def test_schema_des_champs():
    champs = await champs_disponibles(document(), D)
    assert {"d.state", "d.date_depot", "c.commune", "c.budget", "a.relance", "labels"} <= set(champs)
    assert "a.pj" not in champs and "d.labels_json" not in champs        # pièces jointes et colonnes techniques exclues
    assert champs["d.date_depot"].famille == "date" and champs["a.relance"].famille == "booleen"


@pytest.mark.anyio
@pytest.mark.parametrize(("groupes", "attendu"), [
    ([[("d.state", "egal", "en_construction"), ("d.date_depot", "plus_ancien_que", 30)]], ["1"]),
    ([[("d.state", "egal", "en_construction"), ("d.date_depot", "plus_ancien_que", 30)], [("a.relance", "coche", None)]], ["1", "4"]),
    ([[("c.budget", "sup", "1000")]], ["1", "3"]),
    ([[("c.budget", "vide", None)]], ["4"]),
    ([[("c.commune", "contient", "%_")]], ["2"]),                     # % et _ pris littéralement
    ([[("c.commune", "egal", "x' OR '1'='1")]], []),                  # injection neutralisée
    ([[("c.commune", "ne_contient_pas", "Al")]], ["1", "2", "4"]),
    ([[("labels", "a_le_label", "LA")]], ["1"]),
    ([[("labels", "n_a_pas_le_label", "LA"), ("d.state", "different", "accepte")]], ["2", "4"]),
    ([[("d.date_depot", "avant", "2033-04-01")]], ["3", "4"]),
    ([[("a.relance", "non_coche", None)]], ["1", "2", "3"]),
])
async def test_conditions(groupes, attendu):
    assert await numeros(document(), regle(*groupes)) == attendu


@pytest.mark.anyio
@pytest.mark.parametrize("groupe", [
    [("d.inconnu", "egal", "x")],
    [("c.commune", "coche", None)],                 # opérateur incompatible avec le type
    [("d.date_depot", "avant", "15/11/2026")],
    [("d.date_depot", "plus_ancien_que", "trente")],
    [("c.budget", "sup", "beaucoup")],
    [("labels", "a_le_label", "x\" OR 1")],
])
async def test_regles_invalides(groupe):
    with pytest.raises(RegleInvalide):
        await numeros(document(), regle(groupe))


def test_modele_refuse_les_extras():
    with pytest.raises(ValueError):
        DefinitionRegle.model_validate({"nom": "x", "action": "ajouter", "label_id": "LRLR", "groupes": [[]]})
    with pytest.raises(ValueError):
        DefinitionRegle.model_validate({"nom": "x", "action": "supprimer", "label_id": "LRLR",
                                        "groupes": [[{"champ": "d.state", "operateur": "egal", "valeur": "a"}]]})


@pytest.mark.anyio
async def test_cycle_complet_avec_verrou():
    g = document()
    dn = FakeDN({1: {"LA"}, 2: set(), 3: {"LU"}, 4: set()})
    r = regle([("d.state", "different", "accepte")], label="LR", mode="auto")
    rid = await service.enregistrer(dn, g, D, r, cle_schema="doc")
    [stockee] = await service.lister(g, D, cle_schema="doc")
    assert stockee["definition"]["groupes"][0][0]["champ"] == "d.state" and stockee["label"] == "À relancer"

    ev = await service.evaluer(g, D, r, cle_schema="doc", regle_id=rid)
    assert (ev["correspondants"], ev["a_faire"]) == (3, 3)

    bilan = await service.appliquer(dn, g, D, rid, cle_schema="doc")
    assert bilan.appliques == 3 and dn.etat[2] == {"LR"}
    assert {r["dossier_number"] for r in g.rows("LBL_Regles_Traces")} == {"1", "2", "4"}
    assert g.rows("LBL_Regles")[0]["dernier_resultat"].startswith("3 appliqué")
    journal = g.rows("LBL_Operations")
    assert {j["source"] for j in journal} == {"regle:Test"}

    # Une instructrice retire « À relancer » du dossier 2 (DN puis Grist via la synchro)
    dn.etat[2] = set()
    g.db.execute('UPDATE "Demarche_149930_dossiers" SET labels_json = \'\' WHERE dossier_number = \'2\'')
    ev = await service.evaluer(g, D, r, cle_schema="doc", regle_id=rid)
    assert (ev["a_faire"], ev["verrouilles"]) == (0, 1)
    assert await service.appliquer(dn, g, D, rid, cle_schema="doc") is None
    assert dn.etat[2] == set()                                         # la règle ne le remet pas

    # Sans verrou, la règle le remettrait
    await service.enregistrer(dn, g, D, regle([("d.state", "different", "accepte")], label="LR", verrou=False),
                              cle_schema="doc", regle_id=rid)
    ev = await service.evaluer(g, D, (await service._definition(g, D, rid)), cle_schema="doc", regle_id=rid)
    assert ev["a_faire"] == 1


@pytest.mark.anyio
async def test_regles_auto_seulement():
    g = document()
    dn = FakeDN({1: {"LA"}, 2: set(), 3: {"LU"}, 4: set()})
    await service.enregistrer(dn, g, D, regle([("labels", "a_le_label", "LU")], action="retirer", label="LU", mode="auto"),
                              cle_schema="doc")
    await service.enregistrer(dn, g, D, regle([("d.state", "egal", "en_construction")], mode="simulation"), cle_schema="doc")
    res = await service.appliquer_regles_auto(dn, g, D, cle_schema="doc")
    assert [r["regle"] for r in res] == ["Test"] and res[0]["bilan"]["appliques"] == 1
    assert dn.etat[3] == set() and dn.etat[2] == set()                 # la règle en simulation n'a rien fait


@pytest.mark.anyio
async def test_label_hors_catalogue_et_suppression():
    g = document()
    dn = FakeDN({})
    with pytest.raises(RegleInvalide):
        await service.enregistrer(dn, g, D, regle([("d.state", "egal", "x")], label="ZZZZ"), cle_schema="doc")
    rid = await service.enregistrer(dn, g, D, regle([("d.state", "egal", "x")]), cle_schema="doc")
    g.db.execute('INSERT INTO "LBL_Regles_Traces" (regle, dossier_number) VALUES (?, ?)', [rid, "1"])
    await service.supprimer(g, D, rid)
    assert g.rows("LBL_Regles") == [] and g.rows("LBL_Regles_Traces") == []
    with pytest.raises(RegleInvalide):
        await service.supprimer(g, D, rid)


@pytest.mark.anyio
async def test_conditions_stockees_en_json_lisible():
    g = document()
    rid = await service.enregistrer(FakeDN({}), g, D, regle([("c.commune", "contient", "Auch")]), cle_schema="doc")
    stocke = json.loads(g.rows("LBL_Regles")[0]["conditions"])
    assert stocke == [[{"champ": "c.commune", "operateur": "contient", "valeur": "Auch"}]] and rid == 1
