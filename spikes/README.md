# Phase 0 — Tests préalables (labels DN ↔ Grist)

Scripts jetables pour vérifier les hypothèses du plan avant d'écrire le backend.
Chaque script affiche un résumé et enregistre le détail dans `results/` (ignoré par git).

## Prérequis

- Python 3.12+
- Une **démarche DN de test** avec quelques dossiers et au moins 2 labels
- Un **jeton DN dédié** aux tests (limité à cette démarche si l'interface le permet)
- Un **document Grist de test** synchronisé par OTP, et une clé API Grist

```bash
cd spikes
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # puis remplir .env
```

## Ordre d'exécution

| # | Commande | Écrit ? | Question tranchée |
|---|---|---|---|
| 1 | `python dn_01_catalogue.py` | non | Le jeton lit la démarche ? Est-il refusé ailleurs ? Liste des `labelId` |
| 2 | `python dn_02_pagination.py` | non | Taille de page max, temps de lecture complète, gain du parallèle par état |
| 3 | `python dn_03_updated_since.py --ecrire` | DN (restauré) | Un label modifie-t-il `dateDerniereModification` / `updatedSince` ? |
| 4 | `python dn_04_mutations_lot.py --ecrire` | DN (restauré) | Taille de lot par alias, idempotence, erreur partielle |
| 5 | `python dn_05_debit.py --rafale` | non | Débit toléré, en-têtes de limite, premier 429 |
| 6 | `python grist_01_sql.py` | non | `/sql` dispo, paramètres liés, jointures OTP, temps de réponse |
| 7 | `python grist_02_upsert.py --ecrire` | Grist (table temporaire supprimée) | Upsert `PUT /records` + `require` en masse, sans doublon |
| 8 | Récepteur (ci-dessous) | non | Notifications DN sur labels, webhooks Grist, `getAccessToken` |

| A1 | `python ann_01_catalogue.py` | non | Annotations de la démarche (id, type, options), `instructeurId` lisibles, id stables d'un dossier à l'autre |
| A2 | `python ann_02_mutations.py --ecrire` | DN (restauré) | `dossierModifierAnnotations` : id accepté, lots par alias, dates modifiées (détection de conflit), erreurs, texte vide |

Pour A2 : choisir de préférence des annotations **texte** ou **case à cocher** de test (après A1, recopier leurs id dans
`DN_TEST_ANNOTATION_IDS`) et renseigner `DN_TEST_INSTRUCTEUR_EMAIL`. Le script remet les valeurs initiales, même s'il est interrompu.

Après l'étape 1, recopier 2 ou 3 `labelId` dans `DN_TEST_LABEL_IDS`.
Les scripts qui écrivent n'agissent que sur `DN_TEST_DOSSIERS` / `DN_TEST_LABEL_IDS` et
remettent l'état initial ; ils exigent un drapeau explicite (`--ecrire`, `--rafale`).

## Récepteur (hôte de test public)

`receiver/` est un petit serveur sans dépendance, déployable tel quel (Procfile).

Variables à définir chez l'hébergeur :
- `RECEIVER_SECRET` : `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- `GRIST_ALLOWED_HOST=grist.numerique.gouv.fr`

Puis :

1. **Notification DN** — dans la démarche de test, renseigner l'URL de notification
   `https://<hote>/hook/<RECEIVER_SECRET>/dn`. Faire ensuite, dans l'interface DN :
   un changement d'état (témoin), puis un ajout et un retrait de label.
   Consulter `https://<hote>/events/<RECEIVER_SECRET>` : qu'est-ce qui est arrivé ?
2. **Webhook Grist** — dans le document de test, *Paramètres → Webhooks*, URL
   `https://<hote>/hook/<RECEIVER_SECRET>/grist` sur la table des dossiers ; modifier une ligne.
   Noter si l'instance refuse le domaine.
3. **Jeton d'accès Grist** — ajouter une vue *Widget personnalisé* d'URL `https://<hote>/widget`,
   accès « lecture table », puis cliquer sur le bouton (avec et sans lecture seule).
   Le serveur appelle Grist avec ce jeton : `ok: true` prouve qu'on peut authentifier le widget ainsi.

Le secret n'apparaît jamais dans les journaux ; les en-têtes `Authorization`/`Cookie` reçus sont écartés.
Après les tests : supprimer le déploiement et révoquer le jeton DN.

## Résultats

Reporter les constats dans `RESULTATS.md` : c'est la base de décision pour la phase 1.
