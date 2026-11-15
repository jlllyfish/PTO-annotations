"""Aides pour lire un dossier et ajouter/retirer des labels (mutations groupées par alias)."""

from __future__ import annotations

from common import DN, GqlResult

DOSSIER_QUERY = """
query Dossier($n: Int!) {
  dossier(number: $n) {
    id
    number
    state
    dateDerniereModification
    labels { id name }
  }
}
"""

MUTATIONS = {
    "ajouter": ("dossierAjouterLabel", "DossierAjouterLabelInput"),
    "retirer": ("dossierSupprimerLabel", "DossierSupprimerLabelInput"),
}


async def get_dossier(dn: DN, number: int) -> dict:
    res = await dn.gql(DOSSIER_QUERY, {"n": number})
    if not res.ok:
        raise RuntimeError(f"Lecture du dossier {number} impossible : {res.status} {res.errors}")
    return res.data["dossier"]


def build_batch(action: str, n: int) -> str:
    """Construit une mutation groupée : n alias, chacun avec sa variable typée $iK.

    Seuls `action` (liste fermée) et `n` (entier) influencent le texte de la requête ;
    les identifiants passent uniquement par les variables.
    """
    field, input_type = MUTATIONS[action]
    if not isinstance(n, int) or not 1 <= n <= 200:
        raise ValueError("taille de lot invalide")
    decl = ", ".join(f"$i{k}: {input_type}!" for k in range(n))
    body = "\n".join(
        f"  m{k}: {field}(input: $i{k}) {{ dossier {{ number labels {{ id }} }} errors {{ message }} }}"
        for k in range(n)
    )
    return f"mutation Lot({decl}) {{\n{body}\n}}"


async def apply_batch(dn: DN, action: str, pairs: list[tuple[str, str]]) -> tuple[GqlResult, list[dict]]:
    """pairs = [(dossierId, labelId), …]. Renvoie le résultat brut et un état par opération."""
    query = build_batch(action, len(pairs))
    variables = {f"i{k}": {"dossierId": d, "labelId": l} for k, (d, l) in enumerate(pairs)}
    res = await dn.gql(query, variables)
    per_op = []
    for k, (d, l) in enumerate(pairs):
        node = (res.data or {}).get(f"m{k}")
        errs = (node or {}).get("errors") or []
        labels_after = [x["id"] for x in ((node or {}).get("dossier") or {}).get("labels", [])]
        per_op.append({
            "dossierId": d,
            "labelId": l,
            "ok": node is not None and not errs,
            "erreurs": [e["message"] for e in errs],
            "label_present_apres": l in labels_after,
        })
    return res, per_op
