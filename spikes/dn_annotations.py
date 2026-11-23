"""Requêtes et utilitaires partagés par les tests sur les annotations privées (ann_01, ann_02).

Toutes les valeurs passent en `variables` ; le texte des requêtes ne dépend que de constantes
et d'entiers validés.
"""

from __future__ import annotations

from typing import Any

from common import DN

LOT_MAX = 50

_CHAMP = """
  __typename id champDescriptorId label stringValue updatedAt
  ... on TextChamp { texte: value }
  ... on CheckboxChamp { coche: value }
  ... on YesNoChamp { ouiNon: value }
  ... on DateChamp { date }
  ... on IntegerNumberChamp { entier: value }
  ... on DropDownListChamp { choix: value }
  ... on MultipleDropDownListChamp { choixMultiples: values }
"""

Q_CATALOGUE = """
query Catalogue($n: Int!) {
  demarche(number: $n) {
    number title
    activeRevision {
      id
      annotationDescriptors {
        __typename id label required description
        ... on DropDownListChampDescriptor { options otherOption }
        ... on MultipleDropDownListChampDescriptor { options }
      }
    }
    groupeInstructeurs { number label closed instructeurs { id email } }
  }
}
"""

Q_DOSSIER = f"""
query Dossier($n: Int!) {{
  dossier(number: $n) {{
    id number state
    dateDerniereModification dateDerniereModificationAnnotations
    groupeInstructeur {{ number label }}
    demarche {{ number }}
    annotations {{ {_CHAMP} }}
  }}
}}
"""

Q_DEPUIS = """
query Depuis($n: Int!, $since: ISO8601DateTime!) {
  demarche(number: $n) {
    dossiers(first: 100, updatedSince: $since) { nodes { number dateDerniereModification } }
  }
}
"""


def mutation_lot(n: int) -> str:
    if not 1 <= n <= LOT_MAX:
        raise ValueError("taille de lot invalide")
    decl = ", ".join(f"$i{k}: DossierModifierAnnotationsInput!" for k in range(n))
    body = " ".join(
        f"m{k}: dossierModifierAnnotations(input: $i{k}) {{ annotations {{ id stringValue updatedAt }} errors {{ message }} }}"
        for k in range(n)
    )
    return f"mutation Lot({decl}) {{ {body} }}"


async def get_dossier(dn: DN, numero: int) -> dict[str, Any]:
    res = await dn.gql(Q_DOSSIER, {"n": numero})
    if not res.ok or not res.data or not res.data.get("dossier"):
        raise SystemExit(f"Lecture du dossier {numero} impossible : HTTP {res.status} {res.errors}")
    return res.data["dossier"]


def annotation(dossier: dict[str, Any], ident: str) -> dict[str, Any] | None:
    """Cherche une annotation par id de champ OU par id de descripteur."""
    for a in dossier["annotations"]:
        if ident in (a["id"], a["champDescriptorId"]):
            return a
    return None


async def envoyer_lot(dn: DN, inputs: list[dict[str, Any]]):
    """Un appel GraphQL, une mutation aliasée par dossier. Renvoie (résultat brut, statut par dossier)."""
    query = mutation_lot(len(inputs))
    res = await dn.gql(query, {f"i{k}": v for k, v in enumerate(inputs)})
    par_alias: list[dict[str, Any]] = []
    erreurs_par_alias: dict[str, list[str]] = {}
    for err in res.errors or []:
        path = err.get("path") or []
        if path:
            erreurs_par_alias.setdefault(str(path[0]), []).append(err.get("message", ""))
    for k in range(len(inputs)):
        payload = (res.data or {}).get(f"m{k}") or {}
        erreurs = [e["message"] for e in payload.get("errors") or []] + erreurs_par_alias.get(f"m{k}", [])
        par_alias.append({
            "ok": bool(payload) and not erreurs,
            "erreurs": erreurs,
            "annotations": payload.get("annotations"),
        })
    return res, par_alias
