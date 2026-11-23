from datetime import UTC, datetime

import pytest

from app.annotations import service as S
from app.annotations import valeurs as V
from app.dn import annotations as dn_ann
from app.dn.annotations import DescripteurAnnotation, DossierAnnotations
from app.dn.client import GroupeInstructeur
from app.sync import schema

from .fakes import FakeGrist
from .test_sync import D, T


def epoch(j: str) -> float:
    return datetime.fromisoformat(j).replace(tzinfo=UTC).timestamp()


CATALOGUE = [
    DescripteurAnnotation("A0", "Commission", "HeaderSectionChampDescriptor"),
    DescripteurAnnotation("A1", "Avis technique", "TextChampDescriptor"),
    DescripteurAnnotation("A2", "Date de visite", "DateChampDescriptor"),
    DescripteurAnnotation("A3", "Montant retenu", "DecimalNumberChampDescriptor"),
    DescripteurAnnotation("A4", "Dossier complet", "CheckboxChampDescriptor"),
    DescripteurAnnotation("A5", "Filière", "DropDownListChampDescriptor", ("Ovins", "Bovins")),
    DescripteurAnnotation("A6", "Motivation", "TextChampDescriptor"),
]


class FakeDNAnnotations:
    """DN simulé : annotation absente → « ok » sans écrire ; mauvais type → erreur, le reste est écrit."""

    def __init__(self):
        self.etat = {
            1: {"A1": None, "A2": "2026-11-18", "A3": 11900.0, "A4": False, "A5": "Ovins"},   # pas de Motivation
            2: {"A1": "Déjà", "A2": None, "A3": None, "A4": True, "A5": None, "A6": None},
            3: {"A1": None, "A2": None, "A3": None, "A4": False, "A5": None, "A6": None},
        }
        self.groupe = {1: 394762, 2: 394762, 3: 394761}
        self.envois = []

    async def catalogue(self, dn, demarche, *, frais=False):
        return CATALOGUE

    async def dossiers(self, dn, numeros, demarche):
        return [DossierAnnotations(n, f"D{n}", 149930, self.groupe[n], dict(self.etat[n]))
                for n in dict.fromkeys(numeros) if n in self.etat]

    async def modifier(self, dn, instructeur_id, envois):
        out = []
        descs = {a.id: a for a in CATALOGUE}
        for e in envois:
            self.envois.append((instructeur_id, e))
            n = int(e.dossier_id[1:])
            errs = []
            for aid, cle, v in e.annotations:
                if descs[aid].cle != cle:
                    errs.append(f"L'annotation \"{aid}\" n'est pas de type attendu")
                elif aid in self.etat[n]:
                    self.etat[n][aid] = tuple(v) if isinstance(v, list) else v
            out.append(errs)
        return out


@pytest.fixture(autouse=True)
def reset_schema_cache():
    schema._deja_verifie.clear()


@pytest.fixture
def dn(monkeypatch):
    f = FakeDNAnnotations()
    monkeypatch.setattr(dn_ann, "catalogue", f.catalogue)
    monkeypatch.setattr(dn_ann, "dossiers", f.dossiers)
    monkeypatch.setattr(dn_ann, "modifier", f.modifier)
    return f


@pytest.fixture
def g():
    g = FakeGrist()
    g.creer_table_otp(T, [("dossier_number", "Text"), ("label_names", "Text"), ("labels_json", "Text"),
                          ("avis_technique", "Text"), ("date_visite", "Date"), ("montant_calcule", "Numeric"),
                          ("complet", "Bool"), ("filiere", "Text"), ("motivation_saisie", "Text")], [
        {"dossier_number": "1", "avis_technique": "Favorable", "date_visite": epoch("2026-11-18"),
         "montant_calcule": 12480.0, "complet": None, "filiere": "Ovin lait", "motivation_saisie": "Bien"},
        {"dossier_number": "2", "avis_technique": "Déjà", "date_visite": epoch("2026-11-20"),
         "montant_calcule": 100.0, "complet": 0, "filiere": "Bovins", "motivation_saisie": ""},
        {"dossier_number": "3", "avis_technique": "Réservé", "date_visite": None,
         "montant_calcule": None, "complet": 1, "filiere": None, "motivation_saisie": "Motif"},
    ])
    # Copie OTP des annotations (dossier_number en entier, colonnes nommées d'après les libellés)
    g.creer_table_otp("Demarche_149930_annotations", [
        ("dossier_number", "Int"), ("avis_technique", "Text"), ("date_de_visite", "Date"),
        ("montant_retenu", "Numeric"), ("dossier_complet", "Bool"), ("filiere", "Text"), ("motivation", "Text"),
        ("avis_technique_id", "Text")], [
        {"dossier_number": 1, "avis_technique": None, "date_de_visite": epoch("2026-11-18"),
         "montant_retenu": 12000.0, "dossier_complet": 0, "filiere": "Ovins"},     # montant changé depuis dans DN
        {"dossier_number": 2, "avis_technique": "Déjà", "dossier_complet": 1},
        {"dossier_number": 3, "dossier_complet": 0},
    ])
    return g


CHOIX = {"A1": "d.avis_technique", "A2": "d.date_visite", "A3": "d.montant_calcule", "A4": "d.complet",
         "A5": "d.filiere", "A6": "d.motivation_saisie"}


async def configurer(dn, g):
    return await S.enregistrer_correspondances(None, g, D, CHOIX, cle_schema="doc", auteur="camille@x.fr")


def par_annotation(lignes):
    return {L["annotation_id"]: L for L in lignes}


@pytest.mark.anyio
async def test_vue_et_enregistrement(dn, g):
    vue = await S.vue_correspondances(None, g, D, cle_schema="doc")
    assert [e["libelle"] for e in vue["exclues"]] == ["Commission"]
    refs = {s["ref"] for s in vue["sources"]}
    assert "d.avis_technique" in refs and "a.montant_retenu" in refs
    assert "a.avis_technique_id" not in refs and "d.labels_json" not in refs
    assert await configurer(dn, g) == 6
    vue = await S.vue_correspondances(None, g, D, cle_schema="doc")
    a = {x["id"]: x for x in vue["annotations"]}
    assert a["A1"]["compatibilite"]["niveau"] == "ok" and a["A1"]["copie_otp"]
    assert a["A5"]["compatibilite"]["niveau"] == "avertissement"
    assert "« Ovin lait »" in a["A5"]["compatibilite"]["message"]
    # Ré-enregistrer remplace (pas de doublons)
    assert await S.enregistrer_correspondances(None, g, D, {"A1": "d.avis_technique", "A2": None},
                                               cle_schema="doc") == 1
    assert len(g.rows("ANN_Correspondances")) == 1


@pytest.mark.anyio
@pytest.mark.parametrize(("choix", "motif"), [
    ({"A2": "d.complet"}, "incompatibles"),
    ({"A0": "d.avis_technique"}, "non prise en charge"),
    ({"A1": "d.inconnue"}, "colonne Grist inconnue"),
    ({"A3": "a.montant_retenu"}, "copie OTP"),
])
async def test_enregistrement_refuse(dn, g, choix, motif):
    with pytest.raises(S.CorrespondanceInvalide, match=motif):
        await S.enregistrer_correspondances(None, g, D, choix, cle_schema="doc")


@pytest.mark.anyio
async def test_apercu_un_dossier(dn, g):
    await configurer(dn, g)
    a = await S.apercu(None, g, D, [1], None, cle_schema="doc")
    L = par_annotation(a["lignes"])
    assert L["A1"]["statut"] == "a_envoyer" and L["A1"]["grist"] == "Favorable"
    assert L["A2"]["statut"] == "identique"
    assert L["A3"]["statut"] == "conflit" and L["A3"]["copie"] == "12000" and L["A3"]["dn"] == "11900"
    assert L["A4"]["statut"] == "vide"
    assert L["A5"]["statut"] == "invalide" and "Ovin lait" in L["A5"]["message"]
    assert L["A6"]["statut"] == "absente"
    assert a["compte"]["a_envoyer"] == 1 and a["dossiers_a_envoyer"] == 1


@pytest.mark.anyio
async def test_envoi_puis_plus_de_faux_conflit(dn, g):
    await configurer(dn, g)
    b = await S.executer(None, g, D, dict.fromkeys([1, 2, 3, 99]), instructeur_id="I1", cle_schema="doc",
                         source="manuel", auteur="camille@x.fr")
    assert dn.etat[1]["A1"] == "Favorable" and dn.etat[1]["A3"] == 11900.0       # conflit : bloqué
    assert dn.etat[2]["A2"] == "2026-11-20" and dn.etat[2]["A3"] == 100.0 and dn.etat[2]["A4"] is False
    assert dn.etat[3]["A1"] == "Réservé" and dn.etat[3]["A4"] is True and dn.etat[3]["A6"] == "Motif"
    assert "A6" not in dn.etat[1]                                                  # absente : rien envoyé
    assert all(i == "I1" for i, _ in dn.envois)
    assert (b.appliquees, b.bloquees, b.absentes, b.invalides, b.introuvables) == (8, 1, 1, 1, 6)
    assert dn.etat[2]["A5"] == "Bovins"
    # Copie OTP mise à jour d'après DN
    copie = {r["dossier_number"]: r for r in g.rows("Demarche_149930_annotations")}
    assert copie[1]["avis_technique"] == "Favorable" and copie[2]["date_de_visite"] == epoch("2026-11-20")
    # Journal : ni les identiques ni les vides
    j = g.rows("ANN_Operations")
    assert {r["statut"] for r in j} == {"applique", "bloque", "erreur"}
    assert all(r["auteur"] == "camille@x.fr" for r in j)
    # Nouvel aperçu : ce qui vient d'être envoyé est « identique », pas « modifié dans DN »
    a = await S.apercu(None, g, D, [2], None, cle_schema="doc")
    assert {L["statut"] for L in a["lignes"]} <= {"identique", "vide"}


@pytest.mark.anyio
async def test_ecraser_un_conflit(dn, g):
    await configurer(dn, g)
    b = await S.executer(None, g, D, {1: ["A3"]}, instructeur_id="I1", cle_schema="doc", source="manuel",
                         ecraser={(1, "A3")})
    assert b.appliquees == 1 and dn.etat[1]["A3"] == 12480.0
    assert g.rows("ANN_Operations")[0]["message"] == "Écrasée (modifiée dans DN)"


@pytest.mark.anyio
async def test_non_ecrit_detecte_par_relecture(dn, g, monkeypatch):
    await configurer(dn, g)

    async def muet(dn_, instructeur_id, envois):   # DN répond « ok » sans rien écrire
        return [[] for _ in envois]

    monkeypatch.setattr(dn_ann, "modifier", muet)
    b = await S.executer(None, g, D, {3: ["A1"]}, instructeur_id="I1", cle_schema="doc", source="manuel")
    assert b.appliquees == 0 and b.erreurs == 1
    assert b.details[0]["message"] == "DN n'a pas enregistré la valeur"


@pytest.mark.anyio
async def test_perimetre(dn, g):
    await configurer(dn, g)
    b = await S.executer(None, g, D, dict.fromkeys([2, 3]), instructeur_id="I1", cle_schema="doc",
                         source="manuel", perimetre=frozenset({394761}))
    assert b.hors_perimetre == 6 and dn.etat[2]["A2"] is None


@pytest.mark.anyio
async def test_file_puis_envoi(dn, g):
    await configurer(dn, g)
    b = await S.mettre_en_file(None, g, D, {3: None, 1: ["A3"]}, cle_schema="doc", ecraser={(1, "A3")})
    assert b.en_file == 4 and dn.envois == []
    b = await S.envoyer_file(None, g, D, instructeur_id="I1", cle_schema="doc")
    assert b.appliquees == 4 and dn.etat[1]["A3"] == 12480.0
    assert {r["statut"] for r in g.rows("ANN_Operations")} == {"applique"}


def test_instructeur():
    g1 = GroupeInstructeur(1, "G", False, frozenset({"camille@x.fr"}), (("camille@x.fr", "I9"),))
    assert S.instructeur_de([g1], " Camille@X.fr") == "I9"
    with pytest.raises(S.SansInstructeur):
        S.instructeur_de([g1], "autre@x.fr")


def test_nom_otp():
    assert S.nom_otp("Budget alloué nourriture Poney") == "budget_alloue_nourriture_poney"
    assert S.nom_otp("1. Date d'arrivée") == "date_d_arrivee"


@pytest.mark.parametrize(("typename", "brut", "type_grist", "attendu"), [
    ("IntegerNumberChampDescriptor", 12.0, "Numeric", 12),
    ("DecimalNumberChampDescriptor", "12,5", "Text", 12.5),
    ("DateChampDescriptor", "18/11/2026", "Text", "2026-11-18"),
    ("CheckboxChampDescriptor", 0, "Bool", False),
    ("TextChampDescriptor", 3.0, "Numeric", "3"),
    ("TextChampDescriptor", "  ", "Text", None),
])
def test_normaliser(typename, brut, type_grist, attendu):
    assert V.normaliser(DescripteurAnnotation("X", "x", typename), brut, type_grist) == attendu


def test_normaliser_refus():
    with pytest.raises(V.ValeurInvalide, match="entier"):
        V.normaliser(DescripteurAnnotation("X", "x", "IntegerNumberChampDescriptor"), 12.5, "Numeric")
    multi = DescripteurAnnotation("X", "x", "MultipleDropDownListChampDescriptor", ("a", "b"))
    assert V.normaliser(multi, '["L", "b", "a"]', "ChoiceList") == ("b", "a")
    with pytest.raises(V.ValeurInvalide):
        V.normaliser(multi, '["L", "c"]', "ChoiceList")


def test_routes_declarees(config):
    from app.main import create_app
    chemins = set(create_app(config).openapi()["paths"])
    assert {"/api/demarches/{numero}/annotations/correspondances", "/api/demarches/{numero}/annotations/apercu",
            "/api/demarches/{numero}/annotations/envoyer",
            "/api/demarches/{numero}/annotations/file/envoyer"} <= chemins
