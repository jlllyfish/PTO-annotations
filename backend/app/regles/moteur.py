"""Moteur de règles : conditions sur les tables OTP, regroupées en « groupes OU de conditions ET ».

Une règle est validée champ par champ contre le schéma RÉEL du document Grist, puis compilée en SQL :
- les identifiants (tables, colonnes) viennent du schéma et passent par `ident()` ;
- les opérateurs viennent d'une liste fermée ;
- toutes les valeurs saisies passent en paramètres « ? ».
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..config import DemarcheConfig
from ..grist.client import GristClient, ident

LABEL_RE = re.compile(r"^[A-Za-z0-9+/=_-]{2,64}$")
SOURCES = (
    ("d", "dossiers", "Dossier"),
    ("c", "champs", "Champ du formulaire"),
    ("a", "annotations", "Annotation privée"),
)
COLONNES_TECHNIQUES = {"id", "manualSort", "dossier_number", "labels_json", "label_names", "dossier_id"}
REF_LABELS = "labels"


class Famille(StrEnum):
    DATE = "date"
    TEXTE = "texte"
    NOMBRE = "nombre"
    BOOLEEN = "booleen"
    LABELS = "labels"


class Op(StrEnum):
    EGAL = "egal"
    DIFFERENT = "different"
    CONTIENT = "contient"
    NE_CONTIENT_PAS = "ne_contient_pas"
    SUP = "sup"
    SUP_EGAL = "sup_egal"
    INF = "inf"
    INF_EGAL = "inf_egal"
    PLUS_ANCIEN_QUE = "plus_ancien_que"   # N jours
    PLUS_RECENT_QUE = "plus_recent_que"   # N jours
    AVANT = "avant"                       # date AAAA-MM-JJ
    APRES = "apres"
    VIDE = "vide"
    NON_VIDE = "non_vide"
    COCHE = "coche"
    NON_COCHE = "non_coche"
    A_LE_LABEL = "a_le_label"
    N_A_PAS_LE_LABEL = "n_a_pas_le_label"


OPERATEURS: dict[Famille, list[Op]] = {
    Famille.DATE: [Op.PLUS_ANCIEN_QUE, Op.PLUS_RECENT_QUE, Op.AVANT, Op.APRES, Op.VIDE, Op.NON_VIDE],
    Famille.TEXTE: [Op.EGAL, Op.DIFFERENT, Op.CONTIENT, Op.NE_CONTIENT_PAS, Op.VIDE, Op.NON_VIDE],
    Famille.NOMBRE: [Op.EGAL, Op.DIFFERENT, Op.SUP, Op.SUP_EGAL, Op.INF, Op.INF_EGAL, Op.VIDE, Op.NON_VIDE],
    Famille.BOOLEEN: [Op.COCHE, Op.NON_COCHE],
    Famille.LABELS: [Op.A_LE_LABEL, Op.N_A_PAS_LE_LABEL],
}
SANS_VALEUR = {Op.VIDE, Op.NON_VIDE, Op.COCHE, Op.NON_COCHE}


def famille_de(type_grist: str) -> Famille | None:
    t = type_grist.split(":", 1)[0]
    if t in ("Date", "DateTime"):
        return Famille.DATE
    if t in ("Int", "Numeric"):
        return Famille.NOMBRE
    if t == "Bool":
        return Famille.BOOLEEN
    if t in ("Text", "Choice", "ChoiceList", "Any"):
        return Famille.TEXTE
    return None  # Ref, RefList, Attachments… : non proposés


# ------------------------------------------------------------------ modèles


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    champ: str = Field(min_length=1, max_length=210)     # « d.state », « c.budget », « labels »
    operateur: Op
    valeur: str | float | int | None = Field(default=None)

    def valeur_texte(self) -> str:
        return "" if self.valeur is None else str(self.valeur)


Groupe = Annotated[list[Condition], Field(min_length=1, max_length=10)]


class DefinitionRegle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nom: str = Field(min_length=1, max_length=120)
    action: Literal["ajouter", "retirer"]
    label_id: str = Field(pattern=LABEL_RE.pattern)
    mode: Literal["simulation", "auto", "desactivee"] = "simulation"
    verrou: bool = True   # ne pas refaire ce qu'un humain a défait
    groupes: list[Groupe] = Field(min_length=1, max_length=10)


class RegleInvalide(ValueError):
    pass


@dataclass(frozen=True)
class Champ:
    ref: str        # identifiant stable côté widget
    alias: str      # d / c / a
    colonne: str
    famille: Famille
    source: str     # libellé de la source
    libelle: str


# ------------------------------------------------------------------ schéma


async def champs_disponibles(grist: GristClient, d: DemarcheConfig) -> dict[str, Champ]:
    tables = set(await grist.tables())
    out: dict[str, Champ] = {REF_LABELS: Champ(REF_LABELS, "d", "labels_json", Famille.LABELS, "Dossier", "Labels")}
    for alias, suffixe, source in SOURCES:
        table = d.table if suffixe == "dossiers" else d.table_otp(suffixe)
        if table not in tables:
            continue
        for col in await grist.colonnes(table):
            fam = famille_de(col.type)
            if fam is None or col.id in COLONNES_TECHNIQUES or col.id.startswith("gristHelper_"):
                continue
            ref = f"{alias}.{col.id}"
            out[ref] = Champ(ref, alias, col.id, fam, source, col.libelle)
    return out


def tables_jointes(d: DemarcheConfig, champs: dict[str, Champ], regle: DefinitionRegle) -> list[tuple[str, str]]:
    """Tables OTP à joindre (alias, table), d'après les champs réellement utilisés par la règle."""
    alias_utilises = {champs[c.champ].alias for g in regle.groupes for c in g}
    return [(a, d.table_otp(s)) for a, s, _ in SOURCES[1:] if a in alias_utilises]


# ------------------------------------------------------------------ compilation


def _jours(c: Condition) -> int:
    try:
        n = int(float(c.valeur_texte()))
    except ValueError:
        raise RegleInvalide("nombre de jours attendu") from None
    if not 0 <= n <= 36500:
        raise RegleInvalide("nombre de jours hors limites")
    return n


def _date(c: Condition) -> float:
    try:
        jour = date.fromisoformat(c.valeur_texte())
    except ValueError:
        raise RegleInvalide("date au format AAAA-MM-JJ attendue") from None
    return datetime(jour.year, jour.month, jour.day, tzinfo=UTC).timestamp()


def _nombre(c: Condition) -> float:
    try:
        return float(c.valeur_texte().replace(",", "."))
    except ValueError:
        raise RegleInvalide("nombre attendu") from None


def _motif(texte: str) -> str:
    return "%" + texte.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def compiler_condition(c: Condition, champ: Champ, maintenant: float) -> tuple[str, list[Any]]:
    if c.operateur not in OPERATEURS[champ.famille]:
        raise RegleInvalide(f"opérateur « {c.operateur} » impossible pour « {champ.libelle} »")
    col = f"{champ.alias}.{ident(champ.colonne, kind='colonne')}"
    op = c.operateur
    vide = f"({col} IS NULL OR {col} = '')"
    if op == Op.VIDE:
        return vide, []
    if op == Op.NON_VIDE:
        return f"NOT {vide}", []
    if op == Op.COCHE:
        return f"{col} = 1", []
    if op == Op.NON_COCHE:
        return f"({col} IS NULL OR {col} = 0)", []
    if champ.famille == Famille.LABELS:
        label = c.valeur_texte()
        if not LABEL_RE.fullmatch(label):
            raise RegleInvalide("label invalide")
        like = f"COALESCE({col}, '') LIKE ? ESCAPE '\\'"
        motif = _motif(f'"id": "{label}"')  # format JSON écrit par OTP et par l'outil
        return (like if op == Op.A_LE_LABEL else f"NOT {like}"), [motif]
    if op == Op.PLUS_ANCIEN_QUE:
        return f"{col} < ?", [maintenant - _jours(c) * 86400]
    if op == Op.PLUS_RECENT_QUE:
        return f"{col} >= ?", [maintenant - _jours(c) * 86400]
    if op == Op.AVANT:
        return f"{col} < ?", [_date(c)]
    if op == Op.APRES:
        return f"{col} >= ?", [_date(c) + 86400]
    if champ.famille == Famille.NOMBRE:
        sym = {Op.EGAL: "=", Op.DIFFERENT: "!=", Op.SUP: ">", Op.SUP_EGAL: ">=", Op.INF: "<", Op.INF_EGAL: "<="}[op]
        return f"{col} {sym} ?", [_nombre(c)]
    texte = c.valeur_texte()
    if len(texte) > 500:
        raise RegleInvalide("valeur trop longue")
    if op == Op.EGAL:
        return f"{col} = ?", [texte]
    if op == Op.DIFFERENT:
        return f"COALESCE({col}, '') != ?", [texte]
    if op == Op.CONTIENT:
        return f"{col} LIKE ? ESCAPE '\\'", [_motif(texte)]
    return f"COALESCE({col}, '') NOT LIKE ? ESCAPE '\\'", [_motif(texte)]


def compiler(d: DemarcheConfig, regle: DefinitionRegle, champs: dict[str, Champ],
             maintenant: float) -> tuple[str, list[Any]]:
    """SELECT des dossiers (id, numéro, labels) correspondant à la règle."""
    for g in regle.groupes:
        for c in g:
            if c.champ not in champs:
                raise RegleInvalide(f"champ inconnu : {c.champ}")
    args: list[Any] = []
    ou = []
    for g in regle.groupes:
        et = []
        for c in g:
            sql, a = compiler_condition(c, champs[c.champ], maintenant)
            et.append(sql)
            args += a
        ou.append("(" + " AND ".join(et) + ")")
    jointures = "".join(
        f" LEFT JOIN {ident(t)} {a} ON {a}.dossier_number = d.dossier_number"
        for a, t in tables_jointes(d, champs, regle)
    )
    sql = (f"SELECT d.id AS id, d.dossier_number AS dossier_number, d.labels_json AS labels_json "  # noqa: S608
           f"FROM {ident(d.table)} d{jointures} WHERE " + " OR ".join(ou))  # nosec B608 (identifiants validés)
    return sql, args


def schema_public(champs: dict[str, Champ]) -> dict[str, Any]:
    return {
        "champs": [{"ref": c.ref, "libelle": c.libelle, "source": c.source, "famille": c.famille.value}
                   for c in champs.values()],
        "operateurs": {f.value: [o.value for o in ops] for f, ops in OPERATEURS.items()},
        "sans_valeur": sorted(o.value for o in SANS_VALEUR),
    }
