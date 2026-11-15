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

    def _create(self, table, cols):
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
        return [Colonne(c, t, c) for c, t in self.types[table].items()]

    async def sql(self, sql, args=()):
        assert sql.lstrip().upper().startswith("SELECT")
        return [dict(r) for r in self.db.execute(sql, list(args))]

    async def creer_table(self, table, colonnes):
        ident(table)
        self._create(table, list(colonnes))

    async def ajouter_colonnes(self, table, colonnes):
        for c, t in colonnes:
            self.db.execute(f'ALTER TABLE "{table}" ADD COLUMN "{c}"')
            self.types[table][c] = t

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
        for l in lignes:
            cols = ", ".join(f'"{k}"' for k in l)
            self.db.execute(f'INSERT INTO "{table}" ({cols}) VALUES ({", ".join("?" * len(l))})', list(l.values()))
        self.ecritures.append(("ajouter", table, len(lignes)))
        return len(lignes)

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
        return DossierLabels(n, f"D{n}", frozenset(self.etat[n]))

    async def catalogue(self, demarche):
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
