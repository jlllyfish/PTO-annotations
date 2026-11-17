"""Faux Grist (vrai SQLite en mémoire) et faux DN pour tester la synchro sans réseau."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from app.dn.client import Action, DossierLabels, Label, Resultat, Statut
from app.grist.client import Colonne, GristError, ident


class FakeGrist:
    def __init__(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.types: dict[str, dict[str, str]] = {}
        self.meta: dict[str, dict[str, dict]] = {}   # métadonnées de formule par table / colonne
        self._col_ref = 0
        # Utilisateur au nom duquel les écritures sont faites (formules déclenchées user.*)
        self.utilisateur = {"Email": "camille@agriculture.gouv.fr", "UserID": 2949, "Access": "owners", "Name": "Camille"}
        self.ecritures: list[tuple[str, str, int]] = []  # (méthode, table, nb lignes)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    def creer_otp(self, demarche: int, lignes: list[tuple[str, str, str]]) -> None:
        t = f"Demarche_{demarche}_dossiers"
        self._create(t, [("dossier_number", "Text"), ("label_names", "Text"), ("labels_json", "Text")])
        for num, names, js in lignes:
            self.db.execute(f'INSERT INTO "{t}" (dossier_number, label_names, labels_json) VALUES (?,?,?)', (num, names, js))

    def creer_table_otp(self, table: str, cols: list[tuple[str, str]], lignes: list[dict]) -> None:
        self._create(table, cols)
        for l in lignes:
            noms = ", ".join(f'"{k}"' for k in l)
            self.db.execute(f'INSERT INTO "{table}" ({noms}) VALUES ({", ".join("?" * len(l))})', list(l.values()))

    def _create(self, table, cols):
        cols = [(c, t if isinstance(t, str) else t.get("type", "Any")) for c, t in cols]
        self.types[table] = dict(cols)
        defs = ", ".join(f'"{c}"' for c, _ in cols)
        self.db.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, {defs})')

    def rows(self, table) -> list[dict]:
        return [dict(r) for r in self.db.execute(f'SELECT * FROM "{table}" ORDER BY id')]

    # --- interface GristClient ---
    async def tables(self):
        return list(self.types)

    async def colonnes(self, table):
        if table not in self.types:
            raise GristError("Table not found", status=404)
        choix = getattr(self, "choix", {}).get(table, {})
        meta = self.meta.get(table, {})
        return [Colonne(c, t, c, tuple(choix.get(c, ())), dict(meta.get(c, {}))) for c, t in self.types[table].items()]

    async def sql(self, sql, args=()):
        assert sql.lstrip().upper().startswith("SELECT")
        return [dict(r) for r in self.db.execute(sql, list(args))]

    async def creer_table(self, table, colonnes):
        ident(table)
        self._create(table, list(colonnes))
        self._noter_meta(table, colonnes)

    def _noter_meta(self, table, colonnes):
        for c, t in colonnes:
            self._col_ref += 1
            champs = t if isinstance(t, dict) else {"type": t}
            self.meta.setdefault(table, {})[c] = {
                "formula": champs.get("formula", ""), "isFormula": champs.get("isFormula", False),
                "recalcWhen": champs.get("recalcWhen", 0), "recalcDeps": None, "colRef": self._col_ref}

    async def maj_colonnes(self, table, colonnes):
        for c in colonnes:
            self.meta[table][c["id"]].update({k: v for k, v in c["fields"].items() if k != "type"})
        self.ecritures.append(("maj_colonnes", table, len(colonnes)))

    async def membres(self):
        return getattr(self, "liste_membres", [
            {"id": 2949, "email": "Camille@agriculture.gouv.fr", "access": "owners", "parentAccess": None},
            {"id": 3000, "email": "dominique@agriculture.gouv.fr", "access": "editors", "parentAccess": None}])

    async def ajouter_colonnes(self, table, colonnes):
        for c, t in colonnes:
            self.db.execute(f'ALTER TABLE "{table}" ADD COLUMN "{c}"')
            self.types[table][c] = t if isinstance(t, str) else t.get("type", "Any")
        self._noter_meta(table, colonnes)

    def _triggers(self, table, ligne):
        """Simule les formules déclenchées : user.X → utilisateur courant ; autre formule → constante."""
        out = dict(ligne)
        for c, m in self.meta.get(table, {}).items():
            if not m.get("formula") or m.get("isFormula"):
                continue
            auto_dep = m.get("recalcDeps") == ["L", m["colRef"]]
            if c in ligne and not auto_dep:
                continue  # valeur fournie conservée (pas de dépendance à soi-même)
            f = m["formula"]
            out[c] = self.utilisateur.get(f[5:]) if f.startswith("user.") else f.strip('"')
        return out

    async def upsert(self, table, lignes, cles):
        for l in lignes:
            where = " AND ".join(f'"{c}" = ?' for c in cles)
            found = self.db.execute(f'SELECT id FROM "{table}" WHERE {where}', [l[c] for c in cles]).fetchone()
            if found:
                sets = ", ".join(f'"{k}" = ?' for k in l)
                self.db.execute(f'UPDATE "{table}" SET {sets} WHERE id = ?', [*l.values(), found["id"]])
            else:
                cols = ", ".join(f'"{k}"' for k in l)
                self.db.execute(f'INSERT INTO "{table}" ({cols}) VALUES ({", ".join("?" * len(l))})', list(l.values()))
        self.ecritures.append(("upsert", table, len(lignes)))
        return len(lignes)

    async def ajouter(self, table, lignes):
        if getattr(self, "lecture_seule", False):
            raise GristError("No write access", status=403)
        lignes = [self._triggers(table, l) for l in lignes]
        for l in lignes:
            cols = ", ".join(f'"{k}"' for k in l)
            self.db.execute(f'INSERT INTO "{table}" ({cols}) VALUES ({", ".join("?" * len(l))})', list(l.values()))
        self.ecritures.append(("ajouter", table, len(lignes)))
        return len(lignes)

    async def supprimer(self, table, ids):
        for i in ids:
            self.db.execute(f'DELETE FROM "{table}" WHERE id = ?', [i])
        self.ecritures.append(("supprimer", table, len(ids)))
        return len(ids)

    async def maj(self, table, lignes):
        for l in lignes:
            sets = ", ".join(f'"{k}" = ?' for k in l["fields"])
            self.db.execute(f'UPDATE "{table}" SET {sets} WHERE id = ?', [*l["fields"].values(), l["id"]])
        self.ecritures.append(("maj", table, len(lignes)))
        return len(lignes)


CATALOGUE = [
    Label("LA", "À examiner", "purple_glycine"),
    Label("LR", "À relancer", "green_tilleul_verveine"),
    Label("LU", "Urgent", "pink_macaron"),
]


class FakeDN:
    def __init__(self, dossiers: dict[int, set[str]], catalogue=CATALOGUE) -> None:
        self.etat = dossiers
        self.cat = list(catalogue)
        self.appels: list[tuple] = []
        self.erreur: Exception | None = None

    def _d(self, n):
        groupe = getattr(self, "groupe_de", {}).get(n, 394762)
        return DossierLabels(n, f"D{n}", frozenset(self.etat[n]), groupe=groupe, groupe_libelle=f"G{groupe}")

    async def catalogue(self, demarche, *, frais=False):
        if self.erreur:
            raise self.erreur
        return self.cat

    async def tous_les_dossiers(self, demarche, on_page=None):
        self.appels.append(("complete",))
        if on_page:
            on_page(len(self.etat))
        return [self._d(n) for n in self.etat]

    async def dossiers_modifies(self, demarche, depuis: datetime, on_page=None):
        self.appels.append(("incrementale", depuis))
        modifies = getattr(self, "modifies", list(self.etat))
        return [self._d(n) for n in modifies]

    async def dossiers(self, numeros, demarche, on_page=None):
        self.appels.append(("ciblee", tuple(numeros)))
        autres = getattr(self, "autre_demarche", set())
        return [self._d(n) for n in dict.fromkeys(numeros) if n in self.etat and n not in autres]

    async def appliquer(self, action, operations):
        self.appels.append(("appliquer", action, len(operations)))
        res = []
        for op in operations:
            n = int(op.dossier_id[1:])
            if n in getattr(self, "en_erreur", set()):
                res.append(Resultat(op, Statut.ERREUR, "Dossier archivé"))
                continue
            (self.etat[n].add if action == Action.AJOUTER else self.etat[n].discard)(op.label_id)
            res.append(Resultat(op, Statut.APPLIQUE, labels_apres=frozenset(self.etat[n])))
        return res
