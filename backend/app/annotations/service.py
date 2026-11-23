"""Envoi manuel de colonnes Grist vers les annotations privées DN.

- Correspondances (ANN_Correspondances) : une colonne Grist source par annotation DN, réglées par les propriétaires.
- Analyse d'un envoi, d'après l'état RÉEL de DN (lecture ciblée) et de Grist :
  vide → ignorée ; identique → rien à faire ; annotation absente du dossier → signalée ;
  valeur DN ≠ copie OTP dans Grist → modifiée dans DN depuis la synchro : bloquée sauf « écraser ».
- Envoi : un `dossierModifierAnnotations` par dossier, au nom de l'instructeur connecté ;
  relecture DN pour constater ce qui a été écrit (l'API répond « ok » sans écrire sur une annotation absente,
  et n'est pas atomique) ; mise à jour de la copie OTP ; journal ANN_Operations.
"""

from __future__ import annotations

import re
import time
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from ..config import DemarcheConfig
from ..dn import annotations as dn_ann
from ..dn.annotations import DescripteurAnnotation, DossierAnnotations, Envoi, Nature
from ..dn.client import DNClient
from ..grist.client import GristClient, ident
from ..sync.schema import assurer_schema
from . import valeurs as V

CORRESP = "ANN_Correspondances"
JOURNAL = "ANN_Operations"
MAX_FILE = 2000
MAX_DETAILS = 100
MSG_HORS = "Hors de vos groupes instructeurs"

SOURCES = (("d", "dossiers", "Dossier"), ("c", "champs", "Champ du formulaire"),
           ("a", "annotations", "Annotation (copie OTP)"))
TYPES_SOURCE = {"Text", "Choice", "ChoiceList", "Any", "Int", "Numeric", "Bool", "Date", "DateTime"}
TECHNIQUES = {"id", "manualSort", "dossier_number", "dossier_id", "labels_json", "label_names", "champ_id"}
REF_RE = re.compile(r"^[dca]\.[A-Za-z_][A-Za-z0-9_]{0,99}$")


class CorrespondanceInvalide(ValueError):
    pass


class SansInstructeur(PermissionError):
    pass


# ------------------------------------------------------------------ sources et copie OTP


@dataclass(frozen=True)
class Source:
    ref: str       # « d.avis_technique »
    alias: str
    table: str
    colonne: str
    type: str
    libelle: str
    origine: str
    choix: tuple[str, ...] = ()

    def vue(self) -> dict:
        return {"ref": self.ref, "colonne": self.colonne, "libelle": self.libelle, "origine": self.origine,
                "type": V.base(self.type)}


async def sources_grist(grist: GristClient, d: DemarcheConfig) -> dict[str, Source]:
    tables = set(await grist.tables())
    out: dict[str, Source] = {}
    for alias, suffixe, origine in SOURCES:
        table = d.table if suffixe == "dossiers" else d.table_otp(suffixe)
        if table not in tables:
            continue
        for col in await grist.colonnes(table):
            if (col.id in TECHNIQUES or col.id.startswith("gristHelper_") or V.base(col.type) not in TYPES_SOURCE
                    or (alias == "a" and col.id.endswith("_id"))):
                continue
            out[f"{alias}.{col.id}"] = Source(f"{alias}.{col.id}", alias, table, col.id, col.type, col.libelle,
                                              origine, col.choix)
    return out


def nom_otp(libelle: str) -> str:
    """Identifiant de colonne donné par OTP à un libellé (même règle que grist/utils.normalize_column_name)."""
    s = re.sub(r"\s+", " ", (libelle or "").strip()).replace("'", "_").replace("`", "_")
    s = re.sub(r"^\d+[.)]\s*", "", s)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()
    s = re.sub(r"_+", "_", re.sub(r"[^a-z0-9_]", "_", s)).strip("_")
    if not s:
        return "column"
    return s if s[0].isalpha() else "col_" + s


def copie_otp(desc: DescripteurAnnotation, sources: dict[str, Source]) -> Source | None:
    """Colonne de la table d'annotations d'OTP qui recopie cette annotation (libellé identique, sinon nom OTP)."""
    cols = [s for s in sources.values() if s.alias == "a"]
    par_libelle = [s for s in cols if s.libelle == desc.libelle]
    if len(par_libelle) == 1:
        return par_libelle[0]
    return next((s for s in cols if s.colonne == nom_otp(desc.libelle)), None)


# ------------------------------------------------------------------ correspondances


@dataclass(frozen=True)
class Correspondance:
    desc: DescripteurAnnotation
    source: Source
    copie: Source | None


async def lire_brutes(grist: GristClient, d: DemarcheConfig) -> dict[str, str]:
    rows = await grist.sql(f'SELECT annotation_id, source FROM "{CORRESP}" WHERE demarche = ?',  # noqa: S608  # nosec B608
                           [d.numero])
    return {str(r["annotation_id"]): str(r["source"]) for r in rows if r.get("annotation_id") and r.get("source")}


async def correspondances(dn: DNClient, grist: GristClient, d: DemarcheConfig, *, cle_schema: str,
                          annotation_ids: Iterable[str] | None = None) -> tuple[list[Correspondance], list[str]]:
    """Correspondances utilisables (et avertissements pour celles qui ne le sont plus)."""
    await assurer_schema(grist, cle_schema)
    brutes = await lire_brutes(grist, d)
    descs = {a.id: a for a in await dn_ann.catalogue(dn, d.numero)}
    sources = await sources_grist(grist, d)
    voulues = set(annotation_ids) if annotation_ids is not None else None
    ok, avert = [], []
    for aid, ref in brutes.items():
        if voulues is not None and aid not in voulues:
            continue
        desc = descs.get(aid)
        if desc is None or not desc.supporte:
            avert.append(f"Annotation {aid} absente du catalogue DN : correspondance ignorée")
        elif ref not in sources:
            avert.append(f"« {desc.libelle} » : colonne Grist {ref.split('.', 1)[-1]} introuvable")
        elif V.compatibilite(desc, sources[ref].type)[0] == V.ERREUR:
            avert.append(f"« {desc.libelle} » : {V.compatibilite(desc, sources[ref].type)[1]}")
        else:
            copie = copie_otp(desc, sources)
            ok.append(Correspondance(desc, sources[ref], copie if copie and copie.ref != ref else None))
    return ok, avert


async def _inconnus(grist: GristClient, desc: DescripteurAnnotation, src: Source) -> list[str]:
    """Valeurs de la colonne source absentes des options DN (listes déroulantes)."""
    if desc.nature not in (Nature.CHOIX, Nature.CHOIX_MULTIPLES) or desc.autre_option:
        return []
    col = ident(src.colonne, kind="colonne")
    rows = await grist.sql(f"SELECT DISTINCT {col} AS v FROM {ident(src.table)} WHERE {col} IS NOT NULL LIMIT 1000")  # noqa: S608  # nosec B608
    vus = dict.fromkeys(src.choix)
    for r in rows:
        for x in V._liste(r["v"]) if desc.nature == Nature.CHOIX_MULTIPLES else [str(r["v"]).strip()]:
            if x:
                vus[x] = None
    return [x for x in vus if x not in desc.options]


async def vue_correspondances(dn: DNClient, grist: GristClient, d: DemarcheConfig, *, cle_schema: str,
                              frais: bool = False) -> dict:
    await assurer_schema(grist, cle_schema)
    descs = await dn_ann.catalogue(dn, d.numero, frais=frais)
    sources = await sources_grist(grist, d)
    brutes = await lire_brutes(grist, d)
    annotations, exclues = [], []
    for a in descs:
        if not a.supporte:
            exclues.append({"id": a.id, "libelle": a.libelle, "raison": a.type_libelle})
            continue
        ref = brutes.get(a.id)
        compat = None
        if ref:
            src = sources.get(ref)
            if src is None:
                compat = {"niveau": V.ERREUR, "message": "Colonne Grist introuvable"}
            else:
                niveau, msg = V.compatibilite(a, src.type)
                if niveau != V.ERREUR and (inc := await _inconnus(grist, a, src)):
                    niveau = V.AVERTISSEMENT
                    msg = (f"{len(inc)} choix inconnu{'s' if len(inc) > 1 else ''} de DN : "
                           + ", ".join(f"« {x} »" for x in inc[:5]) + (" …" if len(inc) > 5 else "")
                           + ". Ces dossiers seront signalés en erreur.")
                compat = {"niveau": niveau, "message": msg or "Compatible"}
        annotations.append({"id": a.id, "libelle": a.libelle, "type": a.type_libelle, "options": list(a.options),
                            "source": ref, "compatibilite": compat,
                            "copie_otp": bool(copie_otp(a, sources))})
    return {"annotations": annotations, "exclues": exclues,
            "sources": [s.vue() for s in sources.values()]}


async def enregistrer_correspondances(dn: DNClient, grist: GristClient, d: DemarcheConfig,
                                      choix: dict[str, str | None], *, cle_schema: str, auteur: str = "") -> int:
    """Remplace les correspondances de la démarche. Refuse une annotation inconnue ou des types incompatibles."""
    await assurer_schema(grist, cle_schema)
    descs = {a.id: a for a in await dn_ann.catalogue(dn, d.numero, frais=True)}
    sources = await sources_grist(grist, d)
    lignes = []
    now = time.time()
    for aid, ref in choix.items():
        if not ref:
            continue
        desc = descs.get(aid)
        if desc is None or not desc.supporte:
            raise CorrespondanceInvalide(f"Annotation inconnue ou non prise en charge : {aid}")
        if not REF_RE.fullmatch(ref) or ref not in sources:
            raise CorrespondanceInvalide(f"« {desc.libelle} » : colonne Grist inconnue")
        niveau, msg = V.compatibilite(desc, sources[ref].type)
        if niveau == V.ERREUR:
            raise CorrespondanceInvalide(f"« {desc.libelle} » : {msg}")
        copie = copie_otp(desc, sources)
        if copie and copie.ref == ref:
            raise CorrespondanceInvalide(f"« {desc.libelle} » : cette colonne est la copie OTP de l'annotation")
        lignes.append({"demarche": d.numero, "annotation_id": aid, "annotation": desc.libelle,
                       "type": desc.type_libelle, "source": ref, "modifie_le": now, "auteur": auteur})
    anciennes = await grist.sql(f'SELECT id FROM "{CORRESP}" WHERE demarche = ?', [d.numero])  # noqa: S608  # nosec B608
    if anciennes:
        await grist.supprimer(CORRESP, [r["id"] for r in anciennes])
    if lignes:
        await grist.ajouter(CORRESP, lignes)
    return len(lignes)


# ------------------------------------------------------------------ analyse


@dataclass
class Ligne:
    numero: int
    annotation_id: str
    annotation: str
    statut: str
    grist: str = ""
    dn: str = ""
    copie: str = ""
    message: str = ""
    # interne
    valeur: Any = field(default=None, repr=False)
    nature: Any = field(default=None, repr=False)

    def vue(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k not in ("valeur", "nature")}


STATUTS_ANALYSE = ("a_envoyer", "identique", "vide", "conflit", "absente", "invalide", "introuvable", "hors_perimetre")


def _num(v: Any) -> str:
    s = str(v).strip()
    return s[:-2] if s.endswith(".0") else s


async def _lire_grist(grist: GristClient, d: DemarcheConfig, corr: list[Correspondance],
                      numeros: Sequence[int]) -> dict[str, dict[str, Any]]:
    """{numéro: {"s<i>": source, "o<i>": copie OTP, "a_id": ligne de la table d'annotations}}.

    Une requête par table OTP utilisée, sans jointure : `dossier_number` est en texte dans certaines tables et en
    entier dans d'autres, on cherche donc les deux formes.
    """
    par_alias: dict[str, list[str]] = defaultdict(list)
    for i, c in enumerate(corr):
        par_alias[c.source.alias].append(f"{ident(c.source.colonne, kind='colonne')} AS s{i}")
        if c.copie:
            par_alias["a"].append(f"{ident(c.copie.colonne, kind='colonne')} AS o{i}")
    if "a" in par_alias:
        par_alias["a"].append("id AS a_id")
    valeurs: list[Any] = [x for n in numeros for x in (str(n), int(n))]
    place = ", ".join("?" * len(valeurs))
    tables = {"d": d.table, "c": d.table_otp("champs"), "a": d.table_otp("annotations")}
    out: dict[str, dict[str, Any]] = {}
    for alias, champs in par_alias.items():
        sql = (f"SELECT dossier_number AS num, {', '.join(champs)} FROM {ident(tables[alias])} "  # noqa: S608
               f"WHERE dossier_number IN ({place})")  # nosec B608 (identifiants validés)
        for r in await grist.sql(sql, valeurs):
            cible = out.setdefault(_num(r.pop("num")), {})
            for k, v in r.items():
                cible.setdefault(k, v)
    return out


def _analyser_un(n: int, c: Correspondance, i: int, ligne_g: dict | None, dos: DossierAnnotations | None,
                 perimetre: frozenset[int] | None) -> Ligne:
    desc = c.desc
    L = Ligne(n, desc.id, desc.libelle, "", nature=desc.nature)
    if dos is None:
        L.statut, L.message = "introuvable", "Dossier introuvable dans cette démarche"
        return L
    if perimetre is not None and dos.groupe not in perimetre:
        L.statut, L.message = "hors_perimetre", MSG_HORS
        return L
    brut = (ligne_g or {}).get(f"s{i}")
    try:
        val = V.normaliser(desc, brut, c.source.type)
    except V.ValeurInvalide as exc:
        L.statut, L.message, L.grist = "invalide", str(exc), str(brut)[:200]
        return L
    L.grist = V.affichage(desc.nature, val)
    if desc.id not in dos.valeurs:
        L.statut = "absente"
        L.message = "Annotation absente de ce dossier (déposé avant son ajout à la démarche) : DN ignore l'écriture"
        return L
    actuel = dos.valeurs[desc.id]
    L.dn = V.affichage(desc.nature, actuel)
    if val is None:
        L.statut, L.message = "vide", "Valeur vide dans Grist : ignorée"
        return L
    L.valeur = val
    if V.egales(desc.nature, val, actuel):
        L.statut = "identique"
        return L
    if c.copie and ligne_g is not None and ligne_g.get("a_id") is not None:
        try:
            copie = V.normaliser(desc, ligne_g.get(f"o{i}"), c.copie.type, verifier_options=False)
        except V.ValeurInvalide:
            copie = actuel  # copie illisible : pas de conflit déductible
        if not V.egales(desc.nature, copie, actuel):
            L.copie = V.affichage(desc.nature, copie)
            L.statut = "conflit"
            L.message = "Modifiée dans DN depuis la dernière synchro"
            return L
    L.statut = "a_envoyer"
    return L


@dataclass
class Analyse:
    lignes: list[Ligne]
    corr: list[Correspondance]
    dossiers: dict[int, DossierAnnotations]
    grist: dict[str, dict[str, Any]]
    avertissements: list[str]


async def analyser(dn: DNClient, grist: GristClient, d: DemarcheConfig, cibles: dict[int, list[str] | None], *,
                   cle_schema: str, perimetre: frozenset[int] | None = None) -> Analyse:
    """`cibles` : {numéro: ids d'annotations, ou None = toutes les correspondances}."""
    toutes = {i for ids in cibles.values() if ids for i in ids}
    filtre = None if any(ids is None for ids in cibles.values()) else toutes
    corr, avert = await correspondances(dn, grist, d, cle_schema=cle_schema, annotation_ids=filtre)
    numeros = list(cibles)
    if not corr or not numeros:
        return Analyse([], corr, {}, {}, avert)
    g = await _lire_grist(grist, d, corr, numeros)
    dossiers = {x.numero: x for x in await dn_ann.dossiers(dn, numeros, d.numero)}
    lignes = []
    for n in numeros:
        voulues = cibles[n]
        for i, c in enumerate(corr):
            if voulues is None or c.desc.id in voulues:
                lignes.append(_analyser_un(n, c, i, g.get(str(n)), dossiers.get(n), perimetre))
    return Analyse(lignes, corr, dossiers, g, avert)


def _compter(lignes: Iterable[Ligne]) -> dict[str, int]:
    out = dict.fromkeys(STATUTS_ANALYSE, 0)
    for L in lignes:
        out[L.statut] = out.get(L.statut, 0) + 1
    return out


async def apercu(dn: DNClient, grist: GristClient, d: DemarcheConfig, numeros: Sequence[int],
                 annotation_ids: Sequence[str] | None, *, cle_schema: str,
                 perimetre: frozenset[int] | None = None) -> dict:
    numeros = list(dict.fromkeys(numeros))
    ids = list(annotation_ids) if annotation_ids is not None else None
    an = await analyser(dn, grist, d, dict.fromkeys(numeros, ids), cle_schema=cle_schema, perimetre=perimetre)
    compte = _compter(an.lignes)
    a_envoyer = [L for L in an.lignes if L.statut == "a_envoyer"]
    detail = len(numeros) == 1
    signales = [L for L in an.lignes if detail or L.statut in ("conflit", "invalide", "absente")]
    return {
        "total_dossiers": len(numeros),
        "compte": compte,
        "dossiers_a_envoyer": len({L.numero for L in a_envoyer}),
        "dossiers_introuvables": len({L.numero for L in an.lignes if L.statut == "introuvable"}),
        "dossiers_hors_perimetre": len({L.numero for L in an.lignes if L.statut == "hors_perimetre"}),
        "annotations": [{"id": c.desc.id, "libelle": c.desc.libelle, "type": c.desc.type_libelle,
                         "source": c.source.vue(), "copie_otp": bool(c.copie)} for c in an.corr],
        "lignes": [L.vue() for L in signales[:MAX_DETAILS]],
        "lignes_tronquees": len(signales) > MAX_DETAILS,
        "avertissements": an.avertissements,
    }


# ------------------------------------------------------------------ envoi


@dataclass
class Bilan:
    appliquees: int = 0
    erreurs: int = 0
    identiques: int = 0
    vides: int = 0
    bloquees: int = 0          # conflits non écrasés
    absentes: int = 0
    invalides: int = 0
    introuvables: int = 0
    hors_perimetre: int = 0
    en_file: int = 0
    dossiers_envoyes: int = 0
    grist_maj: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)


_JOURNAL_STATUT = {"conflit": "bloque", "absente": "erreur", "invalide": "erreur", "introuvable": "erreur",
                   "hors_perimetre": "refuse", "identique": "deja_applique", "vide": "ignore"}


def instructeur_de(groupes, email: str) -> str:
    for g in groupes:
        if i := g.instructeur_id(email):
            return i
    raise SansInstructeur("DN exige qu'une annotation soit modifiée au nom d'un instructeur de la démarche : "
                          "votre adresse n'en fait pas partie")


async def executer(dn: DNClient, grist: GristClient, d: DemarcheConfig, cibles: dict[int, list[str] | None], *,
                   instructeur_id: str, cle_schema: str, source: str, ecraser_tout: bool = False,
                   ecraser: set[tuple[int, str]] | None = None, perimetre: frozenset[int] | None = None,
                   auteur: str = "", lignes_file: dict[tuple[int, str], list[int]] | None = None) -> Bilan:
    ecraser = ecraser or set()
    an = await analyser(dn, grist, d, cibles, cle_schema=cle_schema, perimetre=perimetre)
    bilan = Bilan(avertissements=an.avertissements)
    retenues = [L for L in an.lignes if L.statut == "a_envoyer"
                or (L.statut == "conflit" and (ecraser_tout or (L.numero, L.annotation_id) in ecraser))]
    par_dossier: dict[int, list[Ligne]] = defaultdict(list)
    for L in retenues:
        par_dossier[L.numero].append(L)
    descs = {c.desc.id: c.desc for c in an.corr}

    envois = [Envoi(an.dossiers[n].id, tuple((L.annotation_id, descs[L.annotation_id].cle,
                                              V.valeur_dn(descs[L.annotation_id], L.valeur)) for L in ls))
              for n, ls in par_dossier.items()]
    reponses = await dn_ann.modifier(dn, instructeur_id, envois) if envois else []
    erreurs_dn = dict(zip(par_dossier, reponses, strict=True))
    bilan.dossiers_envoyes = len(envois)

    # Relecture : seule preuve de l'écriture (annotation absente, envoi partiel)
    apres = {x.numero: x for x in await dn_ann.dossiers(dn, list(par_dossier), d.numero)} if par_dossier else {}
    copies: list[dict[str, Any]] = []
    corr_par_id = {c.desc.id: c for c in an.corr}
    for n, ls in par_dossier.items():
        relu = apres.get(n)
        for L in ls:
            valeur_dn = relu.valeurs.get(L.annotation_id) if relu else None
            if relu and L.annotation_id in relu.valeurs and V.egales(L.nature, L.valeur, valeur_dn):
                L.statut, L.message = "applique", ("Écrasée (modifiée dans DN)" if L.message else "")
                L.dn = V.affichage(L.nature, valeur_dn)
                c = corr_par_id[L.annotation_id]
                ligne_g = an.grist.get(str(n)) or {}
                if c.copie and ligne_g.get("a_id") is not None:
                    copies.append({"id": ligne_g["a_id"],
                                   "fields": {c.copie.colonne: V.vers_grist(L.nature, L.valeur, c.copie.type)}})
            else:
                L.statut = "erreur"
                L.message = "; ".join(erreurs_dn.get(n) or []) or "DN n'a pas enregistré la valeur"
    if copies:  # la copie OTP suit DN : pas de faux « modifiée dans DN » au prochain envoi
        fusion: dict[int, dict[str, Any]] = {}
        for x in copies:
            fusion.setdefault(x["id"], {}).update(x["fields"])
        bilan.grist_maj = await grist.maj(d.table_otp("annotations"),
                                          [{"id": k, "fields": f} for k, f in fusion.items()])

    for L in an.lignes:
        s = L.statut
        bilan.appliquees += s == "applique"
        bilan.erreurs += s == "erreur"
        bilan.identiques += s == "identique"
        bilan.vides += s == "vide"
        bilan.bloquees += s == "conflit"
        bilan.absentes += s == "absente"
        bilan.invalides += s == "invalide"
        bilan.introuvables += s == "introuvable"
        bilan.hors_perimetre += s == "hors_perimetre"
        if s not in ("applique", "identique", "vide") and len(bilan.details) < MAX_DETAILS:
            bilan.details.append(L.vue())

    now = time.time()
    if lignes_file is None:
        journal = [L for L in an.lignes if L.statut not in ("identique", "vide")]
        if journal:
            await grist.ajouter(JOURNAL, [
                {"demarche": d.numero, "dossier_number": str(L.numero), "annotation_id": L.annotation_id,
                 "annotation": L.annotation, "valeur": L.grist[:500], "source": source,
                 "statut": _JOURNAL_STATUT.get(L.statut, L.statut), "message": L.message, "cree_le": now,
                 "traite_le": now, "auteur": auteur, "ecraser": False}
                for L in journal])
    else:
        maj = [{"id": rid, "fields": {"statut": _JOURNAL_STATUT.get(L.statut, L.statut), "message": L.message,
                                      "valeur": L.grist[:500], "traite_le": now}}
               for L in an.lignes if L.statut != "hors_perimetre"
               for rid in lignes_file.get((L.numero, L.annotation_id), [])]
        if maj:
            await grist.maj(JOURNAL, maj)
    return bilan


async def mettre_en_file(dn: DNClient, grist: GristClient, d: DemarcheConfig, cibles: dict[int, list[str] | None], *,
                         cle_schema: str, ecraser_tout: bool = False, ecraser: set[tuple[int, str]] | None = None,
                         perimetre: frozenset[int] | None = None, auteur: str = "") -> Bilan:
    """Met en attente ce qui serait envoyé maintenant ; la valeur sera relue dans Grist au moment de l'envoi."""
    ecraser = ecraser or set()
    an = await analyser(dn, grist, d, cibles, cle_schema=cle_schema, perimetre=perimetre)
    retenues = [L for L in an.lignes if L.statut == "a_envoyer"
                or (L.statut == "conflit" and (ecraser_tout or (L.numero, L.annotation_id) in ecraser))]
    now = time.time()
    if retenues:
        await grist.ajouter(JOURNAL, [
            {"demarche": d.numero, "dossier_number": str(L.numero), "annotation_id": L.annotation_id,
             "annotation": L.annotation, "valeur": L.grist[:500], "source": "manuel", "statut": "en_attente",
             "message": "", "cree_le": now, "auteur": auteur, "ecraser": L.statut == "conflit"}
            for L in retenues])
    return Bilan(en_file=len(retenues), avertissements=an.avertissements)


async def envoyer_file(dn: DNClient, grist: GristClient, d: DemarcheConfig, *, instructeur_id: str, cle_schema: str,
                       perimetre: frozenset[int] | None = None, auteur: str = "") -> Bilan:
    await assurer_schema(grist, cle_schema)
    rows = await grist.sql(
        f'SELECT id, dossier_number, annotation_id, ecraser FROM "{JOURNAL}" '  # noqa: S608  # nosec B608 (constante)
        "WHERE demarche = ? AND statut = 'en_attente' ORDER BY id LIMIT ?", [d.numero, MAX_FILE])
    cibles: dict[int, list[str]] = defaultdict(list)
    lignes: dict[tuple[int, str], list[int]] = defaultdict(list)
    ecraser: set[tuple[int, str]] = set()
    for r in rows:
        try:
            n = int(str(r["dossier_number"]).strip())
        except ValueError:
            await grist.maj(JOURNAL, [{"id": r["id"], "fields": {"statut": "erreur", "message": "Ligne invalide"}}])
            continue
        aid = str(r["annotation_id"])
        if aid not in cibles[n]:
            cibles[n].append(aid)
        lignes[(n, aid)].append(r["id"])
        if r.get("ecraser"):
            ecraser.add((n, aid))
    if not cibles:
        return Bilan()
    # Correspondance supprimée entre-temps : la ligne ne peut plus être traitée
    corr, _ = await correspondances(dn, grist, d, cle_schema=cle_schema)
    connues = {c.desc.id for c in corr}
    orphelines = [rid for (n, aid), ids in lignes.items() if aid not in connues for rid in ids]
    if orphelines:
        await grist.maj(JOURNAL, [{"id": i, "fields": {"statut": "erreur", "message": "Correspondance supprimée"}}
                                  for i in orphelines])
    return await executer(dn, grist, d, dict(cibles), instructeur_id=instructeur_id, cle_schema=cle_schema,
                          source="file", ecraser=ecraser, perimetre=perimetre, auteur=auteur,
                          lignes_file=dict(lignes))
