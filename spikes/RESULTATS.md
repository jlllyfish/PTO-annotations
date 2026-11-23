# Fiche de résultats — phase 0

Date : 15/11/2026 · Démarche de test : 149930 (26 dossiers) · Mesures de volume : démarche réelle de 6 368 dossiers
· Grist : grist.numerique.gouv.fr, document synchronisé par OTP · Récepteur : en local

| Question | Résultat | Conséquence sur le plan |
|---|---|---|
| Portée du jeton DN (dn_01) | Restriction réseau (IP) active et efficace. Jeton trop large : lit aussi une autre démarche | Prod : jeton restreint aux démarches gérées (si DN le permet) + IP du serveur interne |
| Taille de page `first` (dn_02) | Plafonnée **en silence à 100** | Pagination par 100, toujours suivre `hasNextPage` |
| Lecture complète (dn_02) | 6 368 dossiers = 64 pages ≈ 12–15 s. Découpage par état : ×1,3 seulement (93 % « accepté ») | Relecture complète en tâche de fond uniquement |
| Découpage par date de création (dn_02b) | ×1,9 mais **perd 25 dossiers** (ordre DN ≠ numéro) | Écarté |
| Lecture ciblée par alias `dossier(number:)` (dn_02b) | ≈ 30 ms/dossier (25 → 0,8 s ; 100 → 3,1 s) | Pour les petites sélections, lots de 25 en parallèle |
| Un label modifie `dateDerniereModification` ? (dn_03, dn_03b) | **Oui** : ajout et retrait, via API **et** via l'interface DN ; visible dans `updatedSince` | **Synchro incrémentale** + relecture complète de nuit. Commentaire d'OTP obsolète |
| Lots de mutations par alias (dn_04) | 50 ops OK en ≈ 0,75 s (≈ 15 ms/op) ; 100 non testé | Lots de 50 |
| Idempotence (dn_04) | Non native : erreurs explicites « déjà associé » / « n'est pas associé » | Traiter comme `déjà appliqué`, confirmé par les labels renvoyés |
| Erreur partielle (dn_04) | Erreur rattachée à l'alias (`path`, `code: not_found`) ; le reste du lot passe | Statut par ligne via `path` ; labelId validés contre le catalogue avant envoi |
| Débit (dn_05) | 60 req/s (5 simultanées) sans 429 ; aucun en-tête de limite ; p50 69 ms | 3–4 requêtes simultanées max, nouvelle tentative sur 429/503, journaliser `x-request-id` |
| `/sql` Grist (grist_01) | Disponible, ≈ 50 ms, paramètres liés, jointures OTP OK, injection neutralisée, **écriture refusée** | Moteur de règles en SQL paramétré |
| Types OTP (grist_01) | `dossier_number` stocké en **texte** | Tables `LBL_*` : même type pour les jointures |
| Upsert `PUT` + `require` (grist_02) | 2 000 lignes : 0,8 s création, 0,4 s mise à jour, sans doublon | Écriture en masse par upsert |
| `grist-plugin-api.js` | Exige `'unsafe-eval'` dans la CSP | CSP du widget : `'unsafe-eval'` sans `'unsafe-inline'`, affichage par `textContent` |
| `getAccessToken` | Exige l'**accès complet** au document ; jetons lecture seule **et** écriture obtenus en ≈ 37 ms, vérifiés serveur en 110–160 ms ; `baseUrl` = `/o/<org>/api/docs/<docId>` | Authentification du widget validée ; contrôle docId ↔ `demarches.yaml` ; cache pendant la durée du jeton |
| Notification DN sur les labels | Reporté (nécessite une URL publique) | Non bloquant grâce à `updatedSince` |
| Webhook Grist | Reporté | Non bloquant |

## Décisions

- Synchro : incrémentale (`updatedSince`, marge de recouvrement) toutes les quelques minutes + relecture complète la nuit ; bouton « synchroniser la sélection » par alias.
- Écriture DN : lots de 50, statut par opération, « déjà associé / pas associé » = déjà appliqué.
- Concurrence DN : 3–4 requêtes simultanées, gestion des 429/503.
- Grist : lectures en `/sql` paramétré, écritures par upsert ; `dossier_number` en texte.
- Widget : accès complet au document, jeton Grist vérifié par le backend, CSP stricte sauf `'unsafe-eval'`.
- À trancher en phase 1 : écrire dans Grist avec le jeton de l'utilisateur (historique Grist nominatif) ou avec la clé du service.

# Fiche de résultats — annotations privées (ann_01, ann_02)

Date : 23/11/2026 · Démarche de test : 149930 · 7 annotations (dont 1 titre de section, 1 référentiel)

| Question | Résultat | Conséquence |
|---|---|---|
| Catalogue (`activeRevision.annotationDescriptors`) | Lisible : id, libellé, type, options des listes | Liste des cibles de l'onglet Correspondances ; exclure titres de section et référentiels |
| Identifiants des instructeurs | Lisibles via `groupeInstructeurs.instructeurs { id email }` | `instructeurId` = instructeur connecté (email certifié Grist) |
| Id d'une annotation | **Identique sur tous les dossiers et = id du descripteur** | La table de correspondances suffit ; pas de lecture préalable pour les id |
| Annotation absente d'un dossier (révision antérieure) | Ajoutée au catalogue après le dépôt : **absente du dossier** | Voir ligne « écriture sur annotation absente » |
| Écriture sur annotation absente | **`ok` sans erreur, mais rien n'est écrit** | Vérifier la présence avant l'envoi ; statut « absente de ce dossier » ; ne jamais conclure au succès sans relire |
| Plusieurs annotations d'un dossier en un appel | OK ≈ 100–120 ms | Un `dossierModifierAnnotations` par dossier |
| Lots par alias | OK (2 dossiers testés ; 50 validé pour les labels) | Lots de 50, à confirmer sur plus de dossiers |
| Erreur dans un appel | **Non atomique** : les annotations valides du même dossier sont appliquées ; les autres alias du lot ne sont pas touchés | Statut par annotation ; relire DN après un envoi en erreur |
| Mauvais type | Erreur explicite « n'est pas de type attendu » | Contrôle des types dans Correspondances |
| Liste déroulante `""` | Accepté : vide l'annotation | (on n'envoie pas les vides ; utile pour un futur « effacer ») |
| Valeur identique | Aucune date modifiée | Comparer avant d'envoyer reste utile (aperçu) mais sans risque |
| Dates après écriture | `dateDerniereModification` modifiée, dossier vu par `updatedSince` ; **`dateDerniereModificationAnnotations` inchangée**, `updatedAt` pas fiable | Détection de conflit **par les valeurs** : valeur DN actuelle ≠ copie OTP dans Grist ⇒ modifiée dans DN depuis la synchro |
