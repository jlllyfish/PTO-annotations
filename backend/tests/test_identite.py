import pytest

from app.dn.client import GroupeInstructeur
from app.droits import CacheGroupes, calculer
from app.identite import Identification, IdentiteDouteuse
from app.security import Appelant
from app.sync import schema

from .conftest import BASE, TOKEN
from .fakes import FakeGrist
from .test_sync import D


@pytest.fixture(autouse=True)
def reset_schema_cache():
    schema._deja_verifie.clear()


def ident(config, g):
    return Identification(config, fabrique_service=lambda _doc: g)


def appelant(config, token=TOKEN):
    return Appelant(config.documents[0], BASE, token)


@pytest.mark.anyio
async def test_identite_certifiee_et_sonde_supprimee(config):
    g = FakeGrist()
    i = await ident(config, g).identifier(appelant(config), g)
    assert (i.email, i.user_id, i.role, i.proprietaire) == ("camille@agriculture.gouv.fr", 2949, "owners", True)
    assert g.rows("LBL_Sessions") == []
    # formules déclenchées auto-dépendantes posées à la création du schéma
    m = g.meta["LBL_Sessions"]["email"]
    assert m["formula"] == "user.Email" and m["recalcDeps"] == ["L", m["colRef"]]


@pytest.mark.anyio
async def test_role_pris_dans_les_membres_pas_dans_la_formule(config):
    g = FakeGrist()
    g.utilisateur = {"Email": "dominique@agriculture.gouv.fr", "UserID": 3000, "Access": "owners", "Name": "D"}
    i = await ident(config, g).identifier(appelant(config), g)
    assert i.role == "editors" and not i.proprietaire and i.editeur


@pytest.mark.anyio
async def test_lecture_seule_anonyme(config):
    g = FakeGrist()
    await schema.assurer_schema(g, "doc")
    g.lecture_seule = True
    assert await ident(config, g).identifier(appelant(config), g) is None


@pytest.mark.anyio
async def test_identite_incoherente_refusee(config):
    g = FakeGrist()
    g.utilisateur = {"Email": "camille@agriculture.gouv.fr", "UserID": 3000, "Access": "owners", "Name": "C"}
    with pytest.raises(IdentiteDouteuse):
        await ident(config, g).identifier(appelant(config), g)


@pytest.mark.anyio
async def test_formule_remplacee_par_une_constante(config):
    g = FakeGrist()
    await schema.assurer_schema(g, "doc")
    schema._deja_verifie.clear()
    # un éditeur remplace la formule par l'adresse d'un autre et retire l'auto-dépendance
    g.meta["LBL_Sessions"]["email"].update({"formula": '"chef@agriculture.gouv.fr"', "recalcDeps": None})
    schema._deja_verifie.add(config.documents[0].grist_doc_id)  # le cache de schéma ne repasse pas
    with pytest.raises(IdentiteDouteuse):
        await ident(config, g).identifier(appelant(config), g)
    assert g.meta["LBL_Sessions"]["email"]["formula"] == "user.Email"  # réparée


@pytest.mark.anyio
async def test_cache_par_jeton(config):
    g = FakeGrist()
    idf = ident(config, g)
    await idf.identifier(appelant(config), g)
    n = len(g.ecritures)
    await idf.identifier(appelant(config), g)
    assert len(g.ecritures) == n
    await idf.identifier(appelant(config, "tok_" + "b" * 40), g)
    assert len(g.ecritures) > n


class DNGroupes:
    def __init__(self):
        self.appels = 0

    async def groupes(self, n):
        self.appels += 1
        return [GroupeInstructeur(394762, "Spaghetti", False, frozenset({"camille@agriculture.gouv.fr"})),
                GroupeInstructeur(394761, "Classique", False, frozenset({"autre@agriculture.gouv.fr"}))]


@pytest.mark.anyio
async def test_droits_par_groupe(config):
    from app.identite import Identite
    dn, cache = DNGroupes(), CacheGroupes()
    camille = Identite("camille@agriculture.gouv.fr", 2949, "C", "editors")
    dr = await calculer(camille, dn, D, cache)
    assert dr.peut_agir and dr.perimetre == {394762} and not dr.proprietaire
    await calculer(camille, dn, D, cache)
    assert dn.appels == 1  # groupes en cache
    inconnu = await calculer(Identite("x@y.fr", 1, "X", "owners"), dn, D, cache)
    assert not inconnu.peut_agir and inconnu.proprietaire and "aucun groupe" in inconnu.raison_refus()
    assert not (await calculer(None, dn, D, cache)).peut_agir
    lecteur = await calculer(Identite("camille@agriculture.gouv.fr", 2949, "C", "viewers"), dn, D, cache)
    assert not lecteur.peut_agir
    sans = await calculer(camille, dn, D.model_copy(update={"controle_instructeurs": False}), cache)
    assert sans.peut_agir and sans.perimetre is None
