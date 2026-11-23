"""Annotations privées dans l'API DN : catalogue, lecture ciblée des valeurs, écriture groupée.

Constats des tests (spikes/RESULTATS.md, annotations) appliqués ici :
- l'id d'une annotation est le même sur tous les dossiers et vaut l'id du descripteur du catalogue ;
- une annotation ajoutée au catalogue après le dépôt est ABSENTE du dossier, et y écrire répond « ok »
  sans rien écrire : la présence est vérifiée avant l'envoi, et l'effet est contrôlé en relisant DN ;
- `dossierModifierAnnotations` n'est pas atomique : relire DN pour connaître l'état réel ;
- `dateDerniereModificationAnnotations` et `updatedAt` ne sont pas fiables : on compare les valeurs.

Toutes les valeurs passent en `variables` ; le texte des requêtes ne dépend que de constantes et d'entiers validés.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .client import LOT_LECTURE, LOT_MUTATION, DNClient, DNError, _chunks


class Nature(StrEnum):
    TEXTE = "texte"
    BOOLEEN = "booleen"
    DATE = "date"
    DATETIME = "datetime"
    ENTIER = "entier"
    DECIMAL = "decimal"
    CHOIX = "choix"
    CHOIX_MULTIPLES = "choix_multiples"


# Descripteur DN → (clé de `AnnotationValueInput`, nature de la valeur, libellé du type)
SUPPORTES: dict[str, tuple[str, Nature, str]] = {
    "TextChampDescriptor": ("text", Nature.TEXTE, "texte"),
    "TextareaChampDescriptor": ("textarea", Nature.TEXTE, "zone de texte"),
    "EmailChampDescriptor": ("email", Nature.TEXTE, "adresse électronique"),
    "PhoneChampDescriptor": ("phone", Nature.TEXTE, "téléphone"),
    "CheckboxChampDescriptor": ("checkbox", Nature.BOOLEEN, "case à cocher"),
    "YesNoChampDescriptor": ("yesNo", Nature.BOOLEEN, "oui / non"),
    "DateChampDescriptor": ("date", Nature.DATE, "date"),
    "DatetimeChampDescriptor": ("datetime", Nature.DATETIME, "date et heure"),
    "IntegerNumberChampDescriptor": ("integerNumber", Nature.ENTIER, "nombre entier"),
    "DecimalNumberChampDescriptor": ("decimalNumber", Nature.DECIMAL, "nombre décimal"),
    "DropDownListChampDescriptor": ("dropDownList", Nature.CHOIX, "liste déroulante"),
    "MultipleDropDownListChampDescriptor": ("multipleDropDownList", Nature.CHOIX_MULTIPLES, "choix multiple"),
}
EXCLUS = {
    "HeaderSectionChampDescriptor": "titre de section",
    "ExplicationChampDescriptor": "explication",
    "RepetitionChampDescriptor": "bloc répétable",
    "PieceJustificativeChampDescriptor": "pièce jointe",
    "TitreIdentiteChampDescriptor": "pièce jointe",
    "ReferentielChampDescriptor": "référentiel",
}

Q_CATALOGUE_ANNOTATIONS = """
query CatalogueAnnotations($n: Int!) {
  demarche(number: $n) {
    activeRevision {
      annotationDescriptors {
        __typename id label required
        ... on DropDownListChampDescriptor { options otherOption }
        ... on MultipleDropDownListChampDescriptor { options }
      }
    }
  }
}
"""

_CHAMP = (
    "__typename id champDescriptorId "
    "... on TextChamp { texte: value } "
    "... on CheckboxChamp { coche: value } "
    "... on YesNoChamp { ouiNon: value } "
    "... on DateChamp { date } "
    "... on DatetimeChamp { datetime } "
    "... on IntegerNumberChamp { entier: value } "
    "... on DecimalNumberChamp { decimal: value } "
    "... on DropDownListChamp { choix: value } "
    "... on MultipleDropDownListChamp { choixMultiples: values }"
)
_DOSSIER = f"id number groupeInstructeur {{ number }} demarche {{ number }} annotations {{ {_CHAMP} }}"


def _query_lecture(n: int) -> str:
    if not 1 <= n <= LOT_LECTURE:
        raise ValueError("taille de lot invalide")
    decl = ", ".join(f"$n{k}: Int!" for k in range(n))
    body = " ".join(f"d{k}: dossier(number: $n{k}) {{ {_DOSSIER} }}" for k in range(n))
    return f"query CibleAnnotations({decl}) {{ {body} }}"


def _query_mutation(n: int) -> str:
    if not 1 <= n <= LOT_MUTATION:
        raise ValueError("taille de lot invalide")
    decl = ", ".join(f"$i{k}: DossierModifierAnnotationsInput!" for k in range(n))
    body = " ".join(f"m{k}: dossierModifierAnnotations(input: $i{k}) {{ errors {{ message }} }}" for k in range(n))
    return f"mutation LotAnnotations({decl}) {{ {body} }}"


@dataclass(frozen=True)
class DescripteurAnnotation:
    id: str
    libelle: str
    typename: str
    options: tuple[str, ...] = ()
    autre_option: bool = False

    @property
    def supporte(self) -> bool:
        return self.typename in SUPPORTES

    @property
    def cle(self) -> str:
        return SUPPORTES[self.typename][0]

    @property
    def nature(self) -> Nature:
        return SUPPORTES[self.typename][1]

    @property
    def type_libelle(self) -> str:
        if self.typename in SUPPORTES:
            return SUPPORTES[self.typename][2]
        return EXCLUS.get(self.typename, "type non pris en charge")


@dataclass(frozen=True)
class DossierAnnotations:
    numero: int
    id: str
    demarche: int | None
    groupe: int | None
    valeurs: dict[str, Any]  # id d'annotation → valeur normalisée (None = vide) ; clé absente = annotation absente


def _normaliser_dn(champ: dict[str, Any]) -> Any:
    """Valeur DN → forme comparable (voir `normaliser` côté service pour Grist)."""
    t = champ.get("__typename")
    if t == "CheckboxChamp":
        return bool(champ.get("coche"))
    if t == "YesNoChamp":
        return champ.get("ouiNon")
    if t == "DateChamp":
        return champ.get("date") or None
    if t == "DatetimeChamp":
        v = champ.get("datetime")
        return datetime.fromisoformat(v).astimezone(UTC) if v else None
    if t == "IntegerNumberChamp":
        v = champ.get("entier")
        return int(v) if v not in (None, "") else None
    if t == "DecimalNumberChamp":
        v = champ.get("decimal")
        return float(v) if v is not None else None
    if t == "DropDownListChamp":
        return champ.get("choix") or None
    if t == "MultipleDropDownListChamp":
        return tuple(champ.get("choixMultiples") or ()) or None
    if t == "TextChamp":
        return champ.get("texte") or None
    return None


def _dossier(node: dict[str, Any]) -> DossierAnnotations:
    return DossierAnnotations(
        numero=int(node["number"]),
        id=str(node["id"]),
        demarche=(node.get("demarche") or {}).get("number"),
        groupe=(node.get("groupeInstructeur") or {}).get("number"),
        valeurs={a["champDescriptorId"]: _normaliser_dn(a) for a in node.get("annotations") or []},
    )


CATALOGUE_TTL = 300.0


async def catalogue(dn: DNClient, demarche: int, *, frais: bool = False) -> list[DescripteurAnnotation]:
    """Annotations privées de la révision active, en cache 5 min."""
    cache = dn.__dict__.setdefault("_cache_annotations", {})
    now = time.monotonic()
    if not frais and (hit := cache.get(demarche)) and hit[0] > now:
        return hit[1]
    data = await dn._data(Q_CATALOGUE_ANNOTATIONS, {"n": demarche})
    descs = [
        DescripteurAnnotation(str(a["id"]), a.get("label") or "", a.get("__typename") or "",
                              tuple(a.get("options") or ()), bool(a.get("otherOption")))
        for a in ((data.get("demarche") or {}).get("activeRevision") or {}).get("annotationDescriptors") or []
    ]
    cache[demarche] = (now + CATALOGUE_TTL, descs)
    return descs


async def dossiers(dn: DNClient, numeros: Sequence[int], demarche: int) -> list[DossierAnnotations]:
    """Lecture ciblée par alias (lots de 25, en parallèle). Dossiers introuvables ou d'une autre démarche écartés."""

    async def lot(nums: Sequence[int]) -> list[DossierAnnotations]:
        body = await dn._post(_query_lecture(len(nums)), {f"n{k}": n for k, n in enumerate(nums)})
        data = body.get("data") or {}
        lus = [_dossier(node) for k in range(len(nums)) if (node := data.get(f"d{k}"))]
        return [d for d in lus if d.demarche == demarche]

    uniques = list(dict.fromkeys(int(n) for n in numeros))
    parts = await asyncio.gather(*(lot(c) for c in _chunks(uniques, LOT_LECTURE)))
    return [d for part in parts for d in part]


@dataclass(frozen=True)
class Envoi:
    dossier_id: str
    annotations: tuple[tuple[str, str, Any], ...]  # (id d'annotation, clé de valeur, valeur DN)


async def modifier(dn: DNClient, instructeur_id: str, envois: Sequence[Envoi]) -> list[list[str]]:
    """Un `dossierModifierAnnotations` par dossier, lots de 50 par alias. Renvoie les erreurs DN de chaque envoi.

    Une liste vide ne prouve PAS l'écriture (annotation absente : « ok » sans effet) : relire DN ensuite.
    """

    async def lot(part: Sequence[Envoi]) -> list[list[str]]:
        variables = {
            f"i{k}": {"dossierId": e.dossier_id, "instructeurId": instructeur_id,
                      "annotations": [{"id": i, "value": {cle: v}} for i, cle, v in e.annotations]}
            for k, e in enumerate(part)
        }
        try:
            body = await dn._post(_query_mutation(len(part)), variables)
        except DNError as exc:
            return [[str(exc)] for _ in part]
        data = body.get("data") or {}
        par_alias: dict[str, list[str]] = {}
        for err in body.get("errors") or []:
            path = err.get("path") or []
            cle = str(path[0]) if path else "*"
            par_alias.setdefault(cle, []).append(err.get("message", "erreur"))
        out = []
        for k in range(len(part)):
            node = data.get(f"m{k}")
            msgs = [e.get("message", "") for e in (node or {}).get("errors") or []]
            msgs += par_alias.get(f"m{k}", []) + par_alias.get("*", [])
            if node is None and not msgs:
                msgs = ["réponse DN absente"]
            out.append(msgs)
        return out

    parts = await asyncio.gather(*(lot(c) for c in _chunks(list(envois), LOT_MUTATION)))
    return [r for part in parts for r in part]
