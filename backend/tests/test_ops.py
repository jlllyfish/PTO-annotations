import pytest

from app.dn.client import Action
from app.ops.service import (
    LabelInconnu,
    apercu,
    envoyer_file,
    executer,
    mettre_en_file,
    vidange_automatique,
    vider_journal,
)
from app.sync import schema

from .fakes import FakeDN, FakeGrist
from .test_sync import D, T, otp


@pytest.fixture(autouse=True)
def reset_schema_cache():
    schema._deja_verifie.clear()


def setup():
    g = FakeGrist()
    g.creer_otp(149930, [("1", *otp(["LA"])), ("2", "", ""), ("3", *otp(["LR"])), ("4", "", "")])
    dn = FakeDN({1: {"LA"}, 2: set(), 3: {"LR"}, 4: set(), 50: set()})
    dn.autre_demarche = {50}
    return g, dn


def journal(g):
    return {r["dossier_number"]: r for r in g.rows("LBL_Operations")}


@pytest.mark.anyio
async def test_apercu_selon_l_etat_dn():
    _, dn = setup()
    a = await apercu(dn, D, Action.AJOUTER, "LA", [1, 2, 3, 50, 99])
    assert (a["a_faire"], a["deja"], a["introuvables"]) == (2, 1, 2)
    assert a["numeros_a_faire"] == [2, 3] and a["label"]["nom"] == "À examiner"


@pytest.mark.anyio
async def test_label_hors_catalogue_refuse():
    g, dn = setup()
    with pytest.raises(LabelInconnu):
        await executer(dn, g, D, Action.AJOUTER, "INCONNU", [1], source="manuel", cle_schema="doc")
    assert dn.appels == []


@pytest.mark.anyio
async def test_ajout_en_masse():
    g, dn = setup()
    dn.en_erreur = {3}
    b = await executer(dn, g, D, Action.AJOUTER, "LA", [1, 2, 3, 50, 2], source="manuel", cle_schema="doc")
    assert (b.appliques, b.deja, b.erreurs, b.introuvables) == (1, 1, 1, 1)
    assert ("appliquer", Action.AJOUTER, 2) in dn.appels           # 1 déjà présent : pas envoyé
    assert dn.etat[50] == set()                                     # autre démarche : jamais touché
    lignes = {r["dossier_number"]: r for r in g.rows(T)}
    assert lignes["2"]["label_names"] == "À examiner"               # Grist mis à jour au format OTP
    assert lignes["3"]["label_names"] == "À relancer"               # erreur DN : inchangé
    j = journal(g)
    assert {n: j[n]["statut"] for n in j} == {"1": "deja_applique", "2": "applique", "3": "erreur", "50": "erreur"}
    assert j["50"]["message"] == "Dossier introuvable dans cette démarche"
    assert j["2"]["source"] == "manuel" and j["2"]["label"] == "À examiner"


@pytest.mark.anyio
async def test_retrait_et_grist_en_retard_corrige():
    g, dn = setup()
    dn.etat[4] = {"LU"}  # posé dans DN, Grist pas encore synchronisé
    b = await executer(dn, g, D, Action.RETIRER, "LR", [3, 4], source="manuel", cle_schema="doc")
    assert (b.appliques, b.deja) == (1, 1)
    lignes = {r["dossier_number"]: r for r in g.rows(T)}
    assert lignes["3"]["label_names"] == "" and lignes["4"]["label_names"] == "Urgent"


@pytest.mark.anyio
async def test_file_puis_envoi():
    g, dn = setup()
    b = await mettre_en_file(dn, g, D, Action.AJOUTER, "LU", [1, 2], source="manuel", cle_schema="doc")
    assert b.en_file == 2 and dn.etat[1] == {"LA"}
    await mettre_en_file(dn, g, D, Action.RETIRER, "LA", [1], source="regle:Nettoyage", cle_schema="doc")
    assert {r["statut"] for r in g.rows("LBL_Operations")} == {"en_attente"}

    bilans = await envoyer_file(dn, g, D, cle_schema="doc")
    assert len(bilans) == 2
    assert dn.etat[1] == {"LU"} and dn.etat[2] == {"LU"}
    assert {r["statut"] for r in g.rows("LBL_Operations")} == {"applique"}
    assert len(g.rows("LBL_Operations")) == 3                       # mises à jour, pas de doublons
    assert await envoyer_file(dn, g, D, cle_schema="doc") == []     # file vide


@pytest.mark.anyio
async def test_vider_journal_conserve_la_file():
    g, dn = setup()
    await executer(dn, g, D, Action.AJOUTER, "LA", [1, 2], source="manuel", cle_schema="doc")
    await mettre_en_file(dn, g, D, Action.AJOUTER, "LU", [3], source="manuel", cle_schema="doc")
    g.db.execute('''INSERT INTO "LBL_Operations" (demarche, dossier_number, statut) VALUES (999, "7", "applique")''')
    assert await vider_journal(g, D, cle_schema="doc") == 2
    restant = {(r["demarche"], r["statut"]) for r in g.rows("LBL_Operations")}
    assert restant == {(149930, "en_attente"), (999, "applique")}   # file et autres démarches intactes


@pytest.mark.anyio
async def test_vidange_automatique_par_anciennete():
    g, dn = setup()
    await mettre_en_file(dn, g, D, Action.AJOUTER, "LU", [3], source="manuel", cle_schema="doc")
    jour = 86400
    now = 2_000_000_000
    for num, statut, age in [("1", "applique", 40), ("2", "erreur", 31), ("4", "applique", 5), ("5", "en_attente", 90)]:
        g.db.execute('''INSERT INTO "LBL_Operations" (demarche, dossier_number, statut, cree_le, traite_le)
                        VALUES (149930, ?, ?, ?, ?)''', [num, statut, now - age * jour, now - age * jour])
    assert await vidange_automatique(g, D, 0, cle_schema="doc", maintenant=now) == 0   # désactivée
    assert await vidange_automatique(g, D, 30, cle_schema="doc", maintenant=now) == 2
    restant = sorted((r["dossier_number"], r["statut"]) for r in g.rows("LBL_Operations"))
    assert restant == [("3", "en_attente"), ("4", "applique"), ("5", "en_attente")]
