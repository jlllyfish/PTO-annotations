"use strict";
/*
 * Widget Grist « Labels DN » — interface calquée sur la liste des dossiers de Démarche Numérique.
 * Sécurité : aucun innerHTML — tout le DOM est construit avec createElement / textContent.
 * Le jeton Grist (getAccessToken) authentifie chaque appel au backend, qui le vérifie auprès de Grist.
 */

// ------------------------------------------------------------------ outils DOM

function h(tag, attrs, ...enfants) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of enfants.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const SVG_NS = "http://www.w3.org/2000/svg";
const ICONES = {
  plus: "M11 11V5h2v6h6v2h-6v6h-2v-6H5v-2z",
  moins: "M5 11h14v2H5z",
  reglages: "M12 1l9.5 5.5v11L12 23l-9.5-5.5v-11L12 1zm0 2.3L4.5 7.65v8.7L12 20.7l7.5-4.35v-8.7L12 3.3zM12 16a4 4 0 1 1 0-8 4 4 0 0 1 0 8zm0-2a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  verifier: "M5.46 4.43A9.95 9.95 0 0 1 12 2c5.52 0 10 4.48 10 10 0 2.14-.67 4.12-1.81 5.74L17 12h3A8 8 0 0 0 6.46 6.11l-1-1.68zm13.08 15.14A9.95 9.95 0 0 1 12 22C6.48 22 2 17.52 2 12c0-2.14.67-4.12 1.81-5.74L7 12H4a8 8 0 0 0 13.54 5.89l1 1.68z",
  haut: "M13 7.83V20h-2V7.83l-5.36 5.36-1.42-1.41L12 4l7.78 7.78-1.42 1.41z",
  bas: "M13 16.17V4h-2v12.17l-5.36-5.36-1.42 1.41L12 20l7.78-7.78-1.42-1.41z",
  fermer: "M12 10.59l4.95-4.95 1.41 1.41L13.41 12l4.95 4.95-1.41 1.41L12 13.41l-4.95 4.95-1.41-1.41L10.59 12 5.64 7.05l1.41-1.41L12 10.59z",
  corbeille: "M17 6h5v2h-2v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V8H2V6h5V3a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v3zm1 2H6v12h12V8zm-9 3h2v6H9v-6zm4 0h2v6h-2v-6zM9 4v2h6V4H9z",
  relire: "M12 2c5.52 0 10 4.48 10 10s-4.48 10-10 10S2 17.52 2 12h2a8 8 0 1 0 2.34-5.66L8.5 8.5H2.5v-6l2.42 2.42A9.96 9.96 0 0 1 12 2zm1 5v4.59l3.2 3.2-1.41 1.42L11 12.41V7h2z",
  externe: "M10 6v2H5v11h11v-5h2v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h6zm11-3v8h-2V6.41l-7.79 7.8-1.42-1.42L17.59 5H13V3h8z",
};
function icone(nom) {
  const s = document.createElementNS(SVG_NS, "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("aria-hidden", "true");
  s.setAttribute("class", "lbl-icone");
  const p = document.createElementNS(SVG_NS, "path");
  p.setAttribute("d", ICONES[nom]);
  s.append(p);
  return s;
}

let compteurIds = 0;
const nouvelId = (p) => `${p}-${++compteurIds}`;

function selectChamp(label, options, valeur, onchange, { cacher = false } = {}) {
  const id = nouvelId("sel");
  return h("div", { class: "fr-select-group" },
    h("label", { class: cacher ? "fr-label lbl-cache" : "fr-label", for: id, text: label }),
    h("select", { class: "fr-select", id, onchange: (e) => onchange(e.target.value) },
      options.map((o) => h("option", { value: o.value, selected: o.value === valeur, text: o.label }))));
}

function alerte(type, titre, texte) {
  return h("div", { class: `fr-alert fr-alert--${type} fr-alert--sm`, role: type === "error" ? "alert" : "status" },
    titre ? h("h3", { class: "fr-alert__title", text: titre }) : null,
    texte ? h("p", { text: texte }) : null);
}

function bouton(texte, onclick, { type = "primary", taille = "", disabled = false, ic = null } = {}) {
  const cls = ["fr-btn", "lbl-btn"];
  if (type !== "primary") cls.push(`fr-btn--${type}`);
  if (taille) cls.push(`fr-btn--${taille}`);
  return h("button", { type: "button", class: cls.join(" "), disabled: disabled || S.occupe, onclick },
    ic ? icone(ic) : null, texte);
}

const fmtDate = new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "short" });
const dateEpoch = (s) => (s ? fmtDate.format(new Date(Number(s) * 1000)) : "—");

function ilYa(s) {
  if (!s) return "jamais";
  const min = Math.round((Date.now() / 1000 - Number(s)) / 60);
  if (min < 1) return "à l'instant";
  if (min < 60) return `il y a ${min} min`;
  const hr = Math.round(min / 60);
  return hr < 24 ? `il y a ${hr} h` : `le ${dateEpoch(s)}`;
}

const ETATS = {
  en_construction: ["En construction", "fr-badge--new"],
  en_instruction: ["En instruction", "fr-badge--info"],
  accepte: ["Accepté", "fr-badge--success"],
  refuse: ["Refusé", "fr-badge--error"],
  sans_suite: ["Sans suite", "fr-badge--warning"],
};
const STATUTS = {
  en_attente: ["En attente", "fr-badge--info"],
  applique: ["Appliqué", "fr-badge--success"],
  deja_applique: ["Déjà appliqué", ""],
  erreur: ["Erreur", "fr-badge--error"],
  refuse: ["Refusé", "fr-badge--warning"],
};
const badge = (texte, cls) => h("span", { class: `fr-badge fr-badge--sm fr-badge--no-icon ${cls || ""}`, text: texte });
const COULEUR_RE = /^[a-z]+(_[a-z]+)*$/;
// Couleur DN (ex. « purple_glycine ») → classe du widget (ex. « lbl-c--purple-glycine »), voir widget.css
const classeCouleur = (c) => (COULEUR_RE.test(c || "") ? `lbl-c--${c.replaceAll("_", "-")}` : "");
const pluriel = (n, un, plusieurs) => `${n} ${n > 1 ? plusieurs : un}`;

// ------------------------------------------------------------------ état et API

const S = {
  contexte: null,
  demarche: null,
  droits: null,           // {utilisateur, groupes, peut_agir, proprietaire, raison, controle_instructeurs} (certifié serveur)
  catalogue: [],          // [{id, nom, couleur}]
  records: [],            // lignes transmises au widget
  onglet: "dossiers",
  jeton: null,
  expiration: 0,
  occupe: false,
  message: null,          // {type, titre, texte}
  synchro: null,          // {tache, derniere}
  journal: [],
  filtreJournal: "toutes",
  rechercheJournal: "",
  modal: null,            // {type: "masse" | "retrait", …}
  ajoutPour: null,        // n° de dossier dont le menu « Ajouter un label » est ouvert
  R: { schema: null, regles: [], edition: null, simulation: null, erreur: null, valeurs: {} },
  T: {
    page: 1, recherche: "", etat: "", label: "", groupe: null, tri: { col: "__num", sens: "desc" },
    colonnes: [], colonnesDoc: [], colonnesPerso: null, brouillon: null, personnaliser: false, selection: new Set(),
  },
};

async function jeton() {
  if (S.jeton && Date.now() < S.expiration) return S.jeton;
  const t = await grist.docApi.getAccessToken({ readOnly: false });
  S.jeton = t;
  S.expiration = Date.now() + Math.max(30000, (Number(t.ttlMsecs) || 300000) - 30000);
  return t;
}

async function api(methode, chemin, corps) {
  const t = await jeton();
  const headers = { Authorization: `Bearer ${t.token}`, "X-Grist-Base-Url": t.baseUrl };
  if (corps !== undefined) headers["Content-Type"] = "application/json";
  const r = await fetch(chemin, { method: methode, headers, body: corps === undefined ? undefined : JSON.stringify(corps) });
  let data = null;
  try { data = await r.json(); } catch { /* corps vide */ }
  if (!r.ok) {
    if (r.status === 401) S.jeton = null;
    const d = data && data.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map((e) => e.msg).join(" ; ") : `Erreur HTTP ${r.status}`);
  }
  return data;
}

const base = () => `/api/demarches/${S.demarche}`;

async function action(fn) {
  if (S.occupe) return;
  S.occupe = true;
  S.message = null;
  rendu();
  try {
    await fn();
  } catch (e) {
    S.message = { type: "error", titre: "Échec", texte: e.message };
  } finally {
    S.occupe = false;
    rendu();
  }
}

async function lireTable(table, filtre) {
  try {
    const cols = await grist.docApi.fetchTable(table);
    const n = (cols.id || []).length;
    const lignes = [];
    for (let i = 0; i < n; i++) {
      const l = {};
      for (const c of Object.keys(cols)) l[c] = cols[c][i];
      if (!filtre || filtre(l)) lignes.push(l);
    }
    return lignes;
  } catch {
    return []; // table pas encore créée
  }
}

// ------------------------------------------------------------------ données

const numeroDe = (rec) => {
  const n = parseInt(String((rec && rec.dossier_number) || "").trim(), 10);
  return Number.isInteger(n) && n > 0 ? n : null;
};
const numerosTransmis = () => [...new Set(S.records.map(numeroDe).filter(Boolean))];

function labelsDuRecord(rec) {
  try {
    const l = JSON.parse(rec.labels_json || "[]");
    return Array.isArray(l) ? l.filter((x) => x && typeof x.id === "string") : [];
  } catch {
    return [];
  }
}

// Affichage dès que le catalogue et l'état de synchro sont là ; droits et journal arrivent ensuite.
async function chargerDemarche() {
  const numero = S.demarche;
  S.droits = null;
  S.T.groupe = null;
  chargerColonnesPerso();
  const droits = api("GET", `${base()}/droits`).catch((e) => ({ erreur: e.message }));
  const journal = chargerJournal();
  const [cat, synchro] = await Promise.all([api("GET", `${base()}/catalogue`), api("GET", `${base()}/synchro`)]);
  S.catalogue = cat.labels;
  S.synchro = synchro;
  droits.then((d) => { if (S.demarche === numero) { S.droits = d; rendu(); } });
  journal.then(() => rendu()).catch(() => {});
}

// ------------------------------------------------------------------ droits (affichage seulement : le serveur contrôle)

const peutAgir = () => Boolean(S.droits && S.droits.peut_agir);
const proprietaire = () => Boolean(S.droits && S.droits.proprietaire);
const mesGroupes = () => new Set(((S.droits && S.droits.groupes) || []).map((g) => g.numero));

// Dossier hors des groupes instructeurs de l'utilisateur, d'après la colonne d'OTP (si elle existe)
function horsGroupes(l) {
  if (!S.droits || !S.droits.controle_instructeurs) return false;
  const g = l.r.groupe_instructeur_number;
  if (g === undefined || g === null || g === "") return false; // inconnu ici : le serveur tranchera
  return !mesGroupes().has(Number(g));
}
const actionnable = (l) => peutAgir() && !horsGroupes(l);
const COL_GROUPE = "groupe_instructeur_number";
const groupesConnus = () => S.records.length > 0 && Object.prototype.hasOwnProperty.call(S.records[0], COL_GROUPE);
// Filtre de groupe effectif : « Mes groupes » par défaut quand on peut le calculer, sinon tous
function filtreGroupe() {
  if (S.T.groupe !== null) return S.T.groupe;
  return S.droits && S.droits.controle_instructeurs && S.droits.groupes && S.droits.groupes.length && groupesConnus()
    ? "__mes" : "";
}

function bandeauDroits() {
  const d = S.droits;
  if (!d) return h("div", { class: "lbl-droits", role: "status" }, h("span", { class: "lbl-mention", text: "Vérification de vos droits…" }));
  if (d.erreur) return alerte("error", "Identité non vérifiée", `${d.erreur} — aucune action n'est possible.`);
  const u = d.utilisateur;
  const roles = { owners: "propriétaire", editors: "éditeur", viewers: "lecteur" };
  const qui = u ? `${u.email}${u.role ? ` (${roles[u.role] || u.role} du document)` : ""}` : "accès en lecture seule";
  const groupes = d.controle_instructeurs
    ? (d.groupes.length ? `Groupes instructeurs : ${d.groupes.map((g) => g.libelle || g.numero).join(", ")}` : null)
    : "Contrôle des groupes instructeurs désactivé pour cette démarche";
  return h("div", { class: "lbl-droits", role: "status" },
    h("span", { class: "lbl-mention" }, "Connecté en tant que ", h("strong", { text: qui })),
    groupes ? h("span", { class: "lbl-mention", text: groupes }) : null,
    d.raison ? badge(d.raison, "fr-badge--warning") : null);
}

async function chargerJournal() {
  S.journal = (await lireTable("LBL_Operations", (l) => Number(l.demarche) === S.demarche))
    .sort((a, b) => (b.cree_le || 0) - (a.cree_le || 0) || b.id - a.id);
}

async function suivreSynchro() {
  for (let i = 0; i < 600; i++) {
    S.synchro = await api("GET", `${base()}/synchro`);
    rendu();
    if (!S.synchro.tache || S.synchro.tache.statut !== "en_cours") break;
    await new Promise((r) => setTimeout(r, 1000));
  }
  const t = S.synchro.tache;
  if (t && t.statut === "ok") {
    const b = t.bilan;
    S.message = { type: "success", titre: "Synchronisation terminée",
      texte: `${pluriel(b.dossiers_lus, "dossier lu", "dossiers lus")}, ${b.dossiers_maj} mis à jour dans Grist (${b.duree_s} s).` };
  } else if (t && t.statut === "erreur") {
    S.message = { type: "error", titre: "Synchronisation en erreur", texte: t.erreur };
  }
}

async function lancerSynchro(mode, numeros) {
  await api("POST", `${base()}/synchro`, numeros ? { mode, numeros } : { mode });
  await suivreSynchro();
}

function messageBilan(b) {
  const verbe = b.action === "ajouter" ? "Ajout" : "Retrait";
  const nom = `« ${b.label.nom} »`;
  const hors = (b.details || []).filter((d) => d.statut === "refuse").map((d) => d.numero);
  const phrases = [];
  const ok = [];
  if (b.appliques) ok.push(pluriel(b.appliques, "dossier modifié", "dossiers modifiés"));
  if (b.deja) ok.push(`${pluriel(b.deja, "dossier", "dossiers")} déjà dans l'état voulu`);
  if (b.en_file) ok.push(`${pluriel(b.en_file, "opération mise", "opérations mises")} en file d'attente`);
  if (ok.length) phrases.push(`${ok.join(", ")}.`);
  if (b.hors_perimetre) {
    const nums = hors.length ? ` (n° ${hors.slice(0, 10).join(", ")}${hors.length > 10 ? "…" : ""})` : "";
    phrases.push(b.hors_perimetre === 1
      ? `Le dossier${hors.length ? ` n° ${hors[0]}` : ""} n'a pas été modifié : il appartient à un groupe instructeur dont vous ne faites pas partie dans Démarche Numérique.`
      : `${b.hors_perimetre} dossiers${nums} n'ont pas été modifiés : ils appartiennent à des groupes instructeurs dont vous ne faites pas partie dans Démarche Numérique.`);
  }
  if (b.introuvables) phrases.push(`${pluriel(b.introuvables, "dossier introuvable", "dossiers introuvables")} dans cette démarche.`);
  if (b.erreurs) phrases.push(`${pluriel(b.erreurs, "erreur", "erreurs")} : voir l'onglet File et journal.`);
  const rien = !b.appliques && !b.deja && !b.en_file;
  return {
    type: b.erreurs || b.introuvables || b.hors_perimetre ? (rien ? "error" : "warning") : "success",
    titre: rien && (b.hors_perimetre || b.erreurs || b.introuvables) ? `${verbe} de ${nom} non effectué` : `${verbe} de ${nom}`,
    texte: phrases.join(" ") || "Aucun changement.",
  };
}

async function operer(sens, labelId, numeros, envoyer = true) {
  const b = await api("POST", `${base()}/operations`, { action: sens, label_id: labelId, numeros, envoyer });
  S.message = messageBilan(b);
  await chargerJournal();
}

// ------------------------------------------------------------------ en-tête et onglets

function enTete() {
  const demarches = (S.contexte && S.contexte.demarches) || [];
  const der = S.synchro && S.synchro.derniere;
  const enCours = S.synchro && S.synchro.tache && S.synchro.tache.statut === "en_cours";
  let etat = badge("Jamais synchronisé", "fr-badge--warning");
  if (enCours) etat = badge("Synchro en cours", "fr-badge--info");
  else if (der && der.statut === "erreur") etat = badge("Synchro en erreur", "fr-badge--error");
  else if (der && der.fin) etat = badge(`Synchro ${ilYa(der.fin)}`, "fr-badge--success");
  return h("header", { class: "lbl-header" },
    h("div", { class: "lbl-header__titre" },
      h("strong", { text: "Labels DN" }),
      h("span", { class: "lbl-mention", text: S.contexte ? `Document « ${S.contexte.document.nom} »` : "" })),
    h("div", { class: "lbl-header__droite" },
      demarches.length > 1
        ? selectChamp("Démarche", demarches.map((d) => ({ value: String(d.numero), label: `${d.numero} — ${d.nom}` })),
          String(S.demarche), (v) => action(async () => {
            S.demarche = Number(v);
            S.T.selection.clear();
            await chargerDemarche();
          }), { cacher: true })
        : h("span", { class: "lbl-mention", text: demarches[0] ? `${demarches[0].numero} — ${demarches[0].nom}` : "" }),
      etat,
      bouton("Synchroniser", () => action(() => lancerSynchro("incrementale")), { type: "tertiary", taille: "sm", ic: "verifier" }),
      h("button", { type: "button", class: "fr-btn fr-btn--tertiary fr-btn--sm lbl-btn", disabled: S.occupe,
        title: "Relit tous les dossiers de la démarche dans DN (à utiliser en cas de doute)",
        onclick: () => action(() => lancerSynchro("complete")) }, icone("relire"), "Relecture complète")));
}

function etatSynchroEnCours() {
  const t = S.synchro && S.synchro.tache;
  if (!t || t.statut !== "en_cours") return null;
  return h("p", { class: "lbl-mention", role: "status",
    text: `Synchronisation (${t.mode}) : ${t.etape} — ${pluriel(t.dossiers_lus, "dossier lu", "dossiers lus")}` });
}

const ONGLETS = [["dossiers", "Dossiers"], ["file", "File et journal"], ["regles", "Règles"]];

function onglets() {
  const attente = S.journal.filter((l) => l.statut === "en_attente").length;
  return h("nav", { class: "lbl-tabs", role: "tablist", "aria-label": "Sections du widget" },
    ONGLETS.map(([id, nom]) => h("button", {
      type: "button", class: "lbl-tab", role: "tab", "aria-selected": S.onglet === id ? "true" : "false",
      onclick: () => {
        S.onglet = id;
        S.message = null;
        if (id === "file") action(chargerJournal);
        else if (id === "regles") action(chargerRegles);
        else rendu();
      },
    }, nom, id === "file" && attente ? h("span", { class: "lbl-compteur", text: String(attente) }) : null)));
}

// ------------------------------------------------------------------ onglet Dossiers

const COLONNES_CACHEES = new Set(["id", "manualSort", "labels_json", "label_names", "dossier_number"]);
const PAR_PAGE = 50;
const MAX_LOT = 500;

// Intitulés des colonnes d'OTP, alignés sur ceux de DN ; les autres colonnes gardent leur identifiant mis en forme.
const LIBELLES = {
  state: "État du dossier", dossier_id: "Identifiant DN", date_depot: "Date de dépôt",
  date_derniere_modification: "Dernière modification", date_expiration: "Date d'expiration",
  date_traitement: "Date de traitement", date_suppression: "Date de suppression",
  date_derniere_correction_en_attente: "Correction en attente depuis",
  date_derniere_modification_champs: "Modification des champs", date_derniere_modification_annotations: "Modification des annotations",
  motivation: "Motivation", suivi_par: "Suivi par", date_accuse_lecture: "Accusé de lecture", correction_instructeur: "Correction demandée",
};
function libelleColonne(c) {
  if (LIBELLES[c]) return LIBELLES[c];
  const t = c.replaceAll("_", " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}

function colonnesDisponibles() {
  const vues = new Set();
  for (const r of S.records.slice(0, 50)) for (const k of Object.keys(r)) vues.add(k);
  return [...vues].filter((c) => !COLONNES_CACHEES.has(c) && !c.startsWith("gristHelper_")).sort();
}

const COL_LABELS = "__labels";

// Colonnes affichées dans l'ordre choisi ; la colonne Labels est toujours présente (en dernier par défaut).
function colonnesAffichees() {
  const dispo = new Set(colonnesDisponibles());
  const source = S.T.brouillon || S.T.colonnes; // le brouillon est prévisualisé en direct pendant la personnalisation
  const ordre = source.filter((c) => c === COL_LABELS || dispo.has(c));
  if (!ordre.includes(COL_LABELS)) ordre.push(COL_LABELS);
  return ordre;
}

function valeurCellule(col, v) {
  if (v === null || v === undefined || v === "") return "";
  if (col === "state" && ETATS[v]) return badge(ETATS[v][0], ETATS[v][1]);
  if (v instanceof Date) return fmtDate.format(v);
  if (typeof v === "number" && col.startsWith("date_") && v > 1e8) return dateEpoch(v);
  if (typeof v === "boolean") return v ? "Oui" : "Non";
  if (Array.isArray(v)) return v.filter((x) => x !== "L").join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function comparer(a, b) {
  const vide = (v) => v === null || v === undefined || v === "";
  if (vide(a) || vide(b)) return vide(a) - vide(b);
  if (a instanceof Date || b instanceof Date) return new Date(a) - new Date(b);
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(valeurCellule("", a)).localeCompare(String(valeurCellule("", b)), "fr", { numeric: true });
}

// Modifie le brouillon (aperçu immédiat dans le tableau) ; rien n'est enregistré avant « Enregistrer ».
function enregistrerColonnes(colonnes) {
  S.T.brouillon = colonnes;
  rendu();
}

function ouvrirPersonnaliser() {
  S.T.brouillon = colonnesAffichees();
  S.T.personnaliser = true;
  rendu();
}

function fermerPersonnaliser() {
  S.T.brouillon = null;
  S.T.personnaliser = false;
  rendu();
}

// Configuration des colonnes : personnelle (navigateur) en priorité, sinon celle du document.
// Seuls les propriétaires enregistrent celle du document : pour un éditeur, Grist ne conserve pas les options
// du widget et les rétablit à la moindre modification du document (une synchro, par exemple).
const cleColonnes = () => `pto-labels/colonnes/${S.contexte ? S.contexte.document.id : "?"}/${S.demarche}`;
const COLONNE_RE = /^[A-Za-z_][A-Za-z0-9_]{0,99}$/;
const colonnesValides = (c) => (Array.isArray(c) ? c.filter((x) => typeof x === "string" && COLONNE_RE.test(x)) : []);

function appliquerColonnes() {
  S.T.colonnes = S.T.colonnesPerso || S.T.colonnesDoc;
}

function chargerColonnesPerso() {
  try {
    const v = localStorage.getItem(cleColonnes());
    S.T.colonnesPerso = v ? colonnesValides(JSON.parse(v)) : null;
  } catch {
    S.T.colonnesPerso = null;
  }
  appliquerColonnes();
}

function sauverPersonnaliser() {
  const colonnes = S.T.brouillon || S.T.colonnes;
  fermerPersonnaliser();
  let local = true;
  try { localStorage.setItem(cleColonnes(), JSON.stringify(colonnes)); } catch { local = false; }
  S.T.colonnesPerso = colonnes;
  appliquerColonnes();
  if (proprietaire()) {
    grist.setOptions({ colonnes }).then(() => {
      S.message = { type: "success", titre: "Tableau enregistré",
        texte: "Pour vous, et comme configuration par défaut du document pour les autres utilisateurs." };
      rendu();
    }).catch(() => {
      S.message = { type: "warning", titre: "Tableau enregistré pour vous seulement", texte: "La configuration du document n'a pas pu être modifiée." };
      rendu();
    });
  } else {
    S.message = local
      ? { type: "success", titre: "Tableau enregistré", texte: "Pour vous, dans ce navigateur." }
      : { type: "warning", titre: "Configuration non enregistrée", texte: "Le navigateur refuse le stockage local : elle sera perdue au rechargement." };
  }
  rendu();
}

function reinitialiserColonnes() {
  try { localStorage.removeItem(cleColonnes()); } catch { /* rien à faire */ }
  S.T.colonnesPerso = null;
  appliquerColonnes();
  fermerPersonnaliser();
  S.message = { type: "info", titre: "Tableau réinitialisé", texte: "Configuration du document rétablie." };
  rendu();
}

function lignesFiltrees() {
  const T = S.T;
  const toutes = S.records.map((r) => ({ r, num: numeroDe(r), labels: labelsDuRecord(r) })).filter((l) => l.num);
  let lignes = toutes;
  const fg = filtreGroupe();
  if (fg === "__mes") { const mes = mesGroupes(); lignes = lignes.filter((l) => mes.has(Number(l.r[COL_GROUPE]))); }
  else if (fg) lignes = lignes.filter((l) => String(l.r[COL_GROUPE]) === fg);
  const perimetre = lignes; // base de l'état des lieux : le filtre de groupe s'applique aux compteurs
  if (T.recherche) lignes = lignes.filter((l) => String(l.num).includes(T.recherche));
  if (T.etat) lignes = lignes.filter((l) => l.r.state === T.etat);
  if (T.label === "__sans") lignes = lignes.filter((l) => !l.labels.length);
  else if (T.label) lignes = lignes.filter((l) => l.labels.some((x) => x.id === T.label));
  const cle = T.tri.col === "__num" ? (l) => l.num : T.tri.col === COL_LABELS ? (l) => l.labels.length : (l) => l.r[T.tri.col];
  lignes.sort((a, b) => comparer(cle(a), cle(b)) * (T.tri.sens === "asc" ? 1 : -1));
  return { toutes, perimetre, lignes };
}

function panneauFiltres(toutes, perimetre) {
  const T = S.T;
  const etats = [...new Set(toutes.map((l) => l.r.state).filter(Boolean))];
  const idRech = nouvelId("rech");
  const compte = new Map();
  let sans = 0;
  for (const l of perimetre) {
    if (!l.labels.length) sans++;
    for (const x of l.labels) compte.set(x.id, (compte.get(x.id) || 0) + 1);
  }
  const filtrer = (id) => () => { T.label = T.label === id ? "" : id; T.page = 1; rendu(); };
  const groupes = new Map();
  for (const l of toutes) {
    const g = l.r[COL_GROUPE];
    if (g !== undefined && g !== null && g !== "") groupes.set(String(g), l.r.groupe_instructeur_label || String(g));
  }
  const optionsGroupe = [
    ...(S.droits && S.droits.groupes && S.droits.groupes.length ? [{ value: "__mes", label: "Mes groupes" }] : []),
    { value: "", label: "Tous les groupes" },
    ...[...groupes].sort((a, b) => a[1].localeCompare(b[1], "fr")).map(([v, lib]) => ({ value: v, label: lib })),
  ];
  return h("section", { class: "lbl-panneau", "aria-labelledby": "lbl-titre-filtres" },
    h("h2", { class: "lbl-panneau__titre", id: "lbl-titre-filtres", text: "Rechercher / filtrer les dossiers" }),
    h("div", { class: "lbl-filtres-grille" },
      selectChamp("État du dossier", [{ value: "", label: "Tous" },
        ...etats.map((e) => ({ value: e, label: (ETATS[e] || [e])[0] }))], T.etat, (v) => { T.etat = v; T.page = 1; rendu(); }),
      h("div", { class: "fr-input-group" },
        h("label", { class: "fr-label", for: idRech, text: "N° dossier" }),
        h("div", { class: "fr-search-bar", role: "search" },
          h("input", { class: "fr-input", type: "search", id: idRech, placeholder: "Rechercher", value: T.recherche,
            inputmode: "numeric", oninput: (e) => { T.recherche = e.target.value.replace(/\D/g, ""); T.page = 1; rendu(); } }),
          h("button", { type: "button", class: "fr-btn", title: "Rechercher", text: "Rechercher" }))),
      selectChamp("Label", [{ value: "", label: "Tous" }, { value: "__sans", label: "Sans label" },
        ...S.catalogue.map((l) => ({ value: l.id, label: l.nom }))], T.label, (v) => { T.label = v; T.page = 1; rendu(); }),
      groupesConnus()
        ? selectChamp("Groupe instructeur", optionsGroupe, filtreGroupe(), (v) => { T.groupe = v; T.page = 1; rendu(); })
        : null),
    S.records.length && !groupesConnus() && S.droits && S.droits.controle_instructeurs
      ? h("p", { class: "lbl-mention", text: "La table des dossiers n'a pas de colonne groupe_instructeur_number (synchronisée par OTP) : "
        + "le tableau ne peut pas filtrer par groupe instructeur. Les actions restent contrôlées par le serveur." })
      : null,
    h("div", { class: "lbl-etat-des-lieux" },
      h("span", { class: "lbl-mention", text: "État des lieux :" }),
      h("div", { class: "lbl-tags lbl-filtres", role: "group", "aria-label": "Filtrer par label" },
        S.catalogue.map((l) => h("button", {
          type: "button", class: `fr-tag fr-tag--sm ${classeCouleur(l.couleur)}`, "aria-pressed": T.label === l.id ? "true" : "false",
          onclick: filtrer(l.id),
        }, `${l.nom} · ${compte.get(l.id) || 0}`)),
        h("button", { type: "button", class: "fr-tag fr-tag--sm", "aria-pressed": T.label === "__sans" ? "true" : "false",
          onclick: filtrer("__sans") }, `Sans label · ${sans}`))));
}

function panneauPersonnaliser() {
  const ordre = colonnesAffichees();
  const autres = colonnesDisponibles().filter((c) => !ordre.includes(c));
  const nom = (c) => (c === COL_LABELS ? "Labels" : libelleColonne(c));
  const deplacer = (i, d) => () => {
    const n = [...ordre];
    [n[i], n[i + d]] = [n[i + d], n[i]];
    enregistrerColonnes(n);
  };
  const petitBouton = (id, libelle, ic, onclick, disabled) => h("button", {
    type: "button", id, class: "fr-btn fr-btn--tertiary-no-outline fr-btn--sm lbl-btn-icone", title: libelle,
    "aria-label": libelle, disabled, onclick }, icone(ic));
  return h("section", { class: "lbl-personnaliser", "aria-label": "Personnaliser le tableau" },
    h("div", { class: "lbl-personnaliser__col" },
      h("h3", { class: "fr-text--md fr-text--bold fr-mb-0", text: "Colonnes affichées" }),
      h("p", { class: "lbl-mention", text: "Le n° de dossier reste en première position et les actions en dernière." }),
      h("ol", { class: "lbl-ordre" }, ordre.map((c, i) => h("li", { class: "lbl-ordre__item" },
        h("span", { class: "lbl-ordre__nom", text: nom(c) }),
        h("span", { class: "lbl-ordre__actions" },
          petitBouton(`ord-h-${c}`, `Monter la colonne ${nom(c)}`, "haut", deplacer(i, -1), i === 0),
          petitBouton(`ord-b-${c}`, `Descendre la colonne ${nom(c)}`, "bas", deplacer(i, 1), i === ordre.length - 1),
          c === COL_LABELS
            ? h("span", { class: "lbl-btn-icone lbl-btn-icone--vide", "aria-hidden": "true" })
            : petitBouton(`ord-x-${c}`, `Masquer la colonne ${nom(c)}`, "fermer", () => enregistrerColonnes(ordre.filter((x) => x !== c)), false)))))),
    h("div", { class: "lbl-personnaliser__col" },
      h("h3", { class: "fr-text--md fr-text--bold fr-mb-0", text: "Colonnes disponibles" }),
      h("p", { class: "lbl-mention", text: "Cochez une colonne pour l'ajouter en fin de tableau." }),
      autres.length
        ? h("fieldset", { class: "fr-fieldset lbl-colonnes" },
          h("legend", { class: "lbl-cache", text: "Colonnes à ajouter" }),
          autres.map((c) => {
            const id = `col-${c}`;
            return h("div", { class: "fr-fieldset__element" }, h("div", { class: "fr-checkbox-group fr-checkbox-group--sm" },
              h("input", { type: "checkbox", id, onchange: () => enregistrerColonnes([...ordre, c]) }),
              h("label", { class: "fr-label", for: id, text: libelleColonne(c) })));
          }))
        : h("p", { class: "lbl-mention", text: "Toutes les colonnes sont affichées." })),
    h("div", { class: "lbl-personnaliser__pied" },
      h("p", { class: "lbl-mention", text: proprietaire()
        ? "Le tableau montre déjà vos changements. Enregistrer : pour vous, et comme configuration par défaut du document."
        : "Le tableau montre déjà vos changements. Enregistrer : pour vous, dans ce navigateur." }),
      h("div", { class: "lbl-actions" },
        S.T.colonnesPerso ? h("button", { type: "button", class: "fr-link fr-link--sm lbl-lien", onclick: reinitialiserColonnes },
          "Revenir à la configuration du document") : null,
        bouton("Annuler", fermerPersonnaliser, { type: "secondary", taille: "sm" }),
        bouton("Enregistrer", sauverPersonnaliser, { taille: "sm" }))));
}

function caseLigne(libelle, coche, onchange, { indetermine = false, disabled = false } = {}) {
  const id = nouvelId("chk");
  const input = h("input", { type: "checkbox", id, checked: coche, disabled, onchange: (e) => onchange(e.target.checked) });
  input.indeterminate = indetermine;
  return h("div", { class: "fr-checkbox-group fr-checkbox-group--sm" }, input,
    h("label", { class: "fr-label", for: id, text: libelle }));
}

function enteteTriable(titre, col) {
  // Modèle DN : le titre est le bouton de tri ; une flèche n'apparaît que sur la colonne triée.
  const T = S.T;
  const actif = T.tri.col === col;
  const sens = actif ? (T.tri.sens === "asc" ? "ascending" : "descending") : "none";
  return h("th", { scope: "col", "aria-sort": sens },
    h("button", {
      type: "button", class: "lbl-tri",
      onclick: () => { T.tri = { col, sens: actif && T.tri.sens === "asc" ? "desc" : "asc" }; T.page = 1; rendu(); },
    }, titre, actif ? h("span", { "aria-hidden": "true", class: "lbl-tri__fleche", text: T.tri.sens === "asc" ? "↑" : "↓" }) : null));
}

function barreSelection(lignes) {
  const T = S.T;
  const n = T.selection.size;
  const nums = [...T.selection];
  const ouvrirMasse = (sens) => () => {
    S.modal = { type: "masse", sens, numeros: nums, label: "", apercu: null, coche: false };
    rendu();
  };
  const selectionnables = lignes.filter(actionnable);
  const toutesSelectionnees = selectionnables.length > 0 && selectionnables.every((l) => T.selection.has(l.num));
  return h("div", { class: "lbl-barre-selection", role: "region", "aria-label": "Actions sur la sélection",
    "data-lbl-ancre": lignes.length ? "" : null },
    h("span", { class: "lbl-barre-selection__compte", text: n ? pluriel(n, "dossier sélectionné", "dossiers sélectionnés") : "0 dossier sélectionné" }),
    bouton("Ajouter un label", ouvrirMasse("ajouter"), { type: "tertiary", taille: "sm", ic: "plus", disabled: !n || !peutAgir() }),
    bouton("Retirer un label", ouvrirMasse("retirer"), { type: "tertiary", taille: "sm", ic: "moins", disabled: !n || !peutAgir() }),
    bouton("Vérifier dans DN", () => action(() => lancerSynchro("ciblee", nums)),
      { type: "tertiary", taille: "sm", ic: "verifier", disabled: !n || n > MAX_LOT }),
    !toutesSelectionnees && selectionnables.length && n
      ? h("button", { type: "button", class: "fr-link fr-link--sm lbl-lien",
        onclick: () => { for (const l of selectionnables) T.selection.add(l.num); rendu(); } },
        `Sélectionner les ${selectionnables.length} dossiers filtrés`)
      : null,
    n ? h("button", { type: "button", class: "fr-link fr-link--sm lbl-lien",
      onclick: () => { T.selection.clear(); rendu(); } }, "Tout désélectionner") : null);
}

function celluleLabels(l) {
  if (!actionnable(l)) {
    return h("td", {}, l.labels.length
      ? h("div", { class: "lbl-tags lbl-tags--pile" }, l.labels.map((x) => h("span", {
        class: `fr-tag fr-tag--sm ${classeCouleur(x.color)}`, text: x.name })))
      : h("span", { class: "lbl-mention", text: "—" }));
  }
  return h("td", {}, l.labels.length
    ? h("div", { class: "lbl-tags lbl-tags--pile" }, l.labels.map((x) => h("button", {
      type: "button", class: `fr-tag fr-tag--sm fr-tag--dismiss ${classeCouleur(x.color)}`, disabled: S.occupe,
      "aria-label": `Retirer le label ${x.name} du dossier ${l.num}`,
      onclick: () => { S.modal = { type: "retrait", num: l.num, label: x }; rendu(); },
    }, x.name)))
    : h("span", { class: "lbl-mention", text: "—" }));
}

function menuAjout(l) {
  const presents = new Set(l.labels.map((x) => x.id));
  const dispo = S.catalogue.filter((c) => !presents.has(c.id));
  return h("div", { class: "lbl-menu", role: "group", "aria-label": `Ajouter un label au dossier ${l.num}` },
    dispo.length
      ? dispo.map((c) => h("button", {
        type: "button", class: `fr-tag fr-tag--sm ${classeCouleur(c.couleur)}`, disabled: S.occupe,
        onclick: () => { S.ajoutPour = null; action(() => operer("ajouter", c.id, [l.num])); },
      }, c.nom))
      : h("span", { class: "lbl-mention", text: "Tous les labels sont déjà posés." }),
    h("button", { type: "button", class: "fr-link fr-link--sm lbl-lien", onclick: () => { S.ajoutPour = null; rendu(); } }, "Fermer"));
}

function vueDossiers() {
  const T = S.T;
  const { toutes, perimetre, lignes } = lignesFiltrees();
  const presents = new Set(toutes.map((l) => l.num));
  const permis = new Set(toutes.filter(actionnable).map((l) => l.num));
  for (const n of [...T.selection]) if (!presents.has(n) || !permis.has(n)) T.selection.delete(n); // sortis du périmètre
  const ordre = colonnesAffichees();
  const pages = Math.max(1, Math.ceil(lignes.length / PAR_PAGE));
  T.page = Math.min(T.page, pages);
  const page = lignes.slice((T.page - 1) * PAR_PAGE, T.page * PAR_PAGE);
  const pageSel = page.filter(actionnable);
  const nbPageSel = pageSel.filter((l) => T.selection.has(l.num)).length;
  const basculer = (num) => (c) => { if (c) T.selection.add(num); else T.selection.delete(num); rendu(); };
  const lienDN = (num) => `https://demarche.numerique.gouv.fr/procedures/${S.demarche}/dossiers/${num}`;

  const tableau = h("div", { class: "fr-table fr-table--bordered fr-table--multiline fr-mb-0 lbl-tableau" },
    h("div", { class: "fr-table__wrapper" }, h("div", { class: "fr-table__container" }, h("div", { class: "fr-table__content" },
      h("table", {},
        h("caption", { class: "lbl-cache", text: "Dossiers de la démarche" }),
        h("thead", {}, h("tr", {},
          h("th", { class: "fr-cell--fixed", role: "columnheader" },
            caseLigne("Sélectionner tous les dossiers de la page", pageSel.length > 0 && nbPageSel === pageSel.length, (c) => {
              for (const l of pageSel) { if (c) T.selection.add(l.num); else T.selection.delete(l.num); }
              rendu();
            }, { indetermine: nbPageSel > 0 && nbPageSel < pageSel.length, disabled: !pageSel.length })),
          enteteTriable("N° dossier", "__num"),
          ordre.map((c) => (c === COL_LABELS ? enteteTriable("Labels", COL_LABELS) : enteteTriable(libelleColonne(c), c))),
          h("th", { scope: "col", text: "Actions" }))),
        h("tbody", {}, page.map((l) => h("tr", { "aria-selected": T.selection.has(l.num) ? "true" : "false" },
          h("th", { class: "fr-cell--fixed", scope: "row" },
            caseLigne(`Sélectionner le dossier ${l.num}`, T.selection.has(l.num), basculer(l.num), { disabled: !actionnable(l) })),
          h("td", {}, h("a", { class: "fr-link", href: lienDN(l.num), target: "_blank", rel: "noopener noreferrer",
            title: `Ouvrir le dossier ${l.num} dans DN (nouvelle fenêtre)`, text: String(l.num) })),
          ordre.map((c) => (c === COL_LABELS ? celluleLabels(l)
            : h("td", { class: c.startsWith("date_") ? "lbl-nowrap" : null }, valeurCellule(c, l.r[c])))),
          h("td", {}, actionnable(l)
            ? [bouton("Ajouter un label", () => { S.ajoutPour = S.ajoutPour === l.num ? null : l.num; rendu(); },
              { type: "secondary", taille: "sm", ic: "plus" }),
            S.ajoutPour === l.num ? menuAjout(l) : null]
            : h("span", { class: "lbl-mention", text: !S.droits ? "…" : horsGroupes(l)
              ? `Hors de vos groupes${l.r.groupe_instructeur_label ? ` (${l.r.groupe_instructeur_label})` : ""}` : "Lecture seule" }))))))))));

  const pagination = pages > 1 ? h("nav", { class: "fr-pagination", "aria-label": "Pagination" },
    h("ul", { class: "fr-pagination__list" },
      h("li", {}, h("button", { type: "button", class: "fr-pagination__link fr-pagination__link--prev fr-pagination__link--lg-label",
        disabled: T.page <= 1, onclick: () => { T.page--; rendu(); } }, "Précédente")),
      h("li", {}, h("span", { class: "fr-pagination__link", "aria-current": "page", text: `Page ${T.page} / ${pages}` })),
      h("li", {}, h("button", { type: "button", class: "fr-pagination__link fr-pagination__link--next fr-pagination__link--lg-label",
        disabled: T.page >= pages, onclick: () => { T.page++; rendu(); } }, "Suivante")))) : null;

  return [
    panneauFiltres(toutes, perimetre),
    h("div", { class: "lbl-entre lbl-entre--centre" },
      h("h2", { class: "fr-h4 fr-mb-0", text: pluriel(lignes.length, "dossier", "dossiers") }),
      h("button", {
        type: "button", class: "fr-btn fr-btn--tertiary fr-btn--sm lbl-btn", "aria-expanded": T.personnaliser ? "true" : "false",
        onclick: () => (T.personnaliser ? fermerPersonnaliser() : ouvrirPersonnaliser()),
      }, icone("reglages"), "Personnaliser le tableau")),
    T.personnaliser ? panneauPersonnaliser() : null,
    h("div", { class: "lbl-bloc-tableau" },
      barreSelection(lignes),
      lignes.length ? tableau : h("p", { class: "lbl-mention fr-p-2w", text: "Aucun dossier ne correspond." })),
    pagination,
  ];
}

// ------------------------------------------------------------------ fenêtres de confirmation

async function calculerApercu() {
  const m = S.modal;
  m.apercu = null;
  m.coche = false;
  if (!m.label) { rendu(); return; }
  m.chargement = true;
  rendu();
  try {
    m.apercu = await api("POST", `${base()}/operations/apercu`, { action: m.sens, label_id: m.label, numeros: m.numeros });
  } catch (e) {
    m.erreur = e.message;
  } finally {
    m.chargement = false;
    if (S.modal === m) rendu();
  }
}

function fermerModal() { S.modal = null; rendu(); }

function modale() {
  const m = S.modal;
  if (!m) return null;
  let titre, corps, actions;
  if (m.type === "regle") {
    const d = m.regle.definition;
    const sim = m.sim;
    titre = `Appliquer « ${d.nom} »`;
    corps = [
      h("p", {}, `${d.action === "ajouter" ? "Ajouter" : "Retirer"} le label « ${nomLabel(d.label_id)} » sur `,
        h("strong", { text: pluriel(sim.a_faire, "dossier", "dossiers") }), " maintenant."),
      h("p", { class: "lbl-mention", text: `${pluriel(sim.correspondants, "dossier remplit", "dossiers remplissent")} les conditions · ${sim.deja} déjà dans l'état voulu`
        + (sim.verrouilles ? ` · ${sim.verrouilles} laissé(s) de côté (modifiés à la main)` : "") + ". 500 dossiers au plus par passage." }),
    ];
    actions = [bouton("Annuler", fermerModal, { type: "secondary" }),
      bouton("Appliquer", () => {
        const id = m.regle.id;
        S.modal = null;
        action(async () => {
          const r = await api("POST", `${base()}/regles/${id}/appliquer`);
          S.message = r.bilan ? messageBilan(r.bilan) : { type: "info", titre: "Rien à faire", texte: "Aucun dossier à traiter." };
          await chargerRegles();
          await chargerJournal();
        });
      }, { disabled: !sim.a_faire })];
  } else if (m.type === "suppr-regle") {
    const d = m.regle.definition || { nom: "?" };
    titre = "Supprimer la règle";
    corps = [h("p", {}, "Supprimer la règle ", h("strong", { text: `« ${d.nom} »` }), " ?"),
      h("p", { class: "lbl-mention", text: "Les labels déjà posés ou retirés par cette règle ne changent pas." })];
    actions = [bouton("Annuler", fermerModal, { type: "secondary" }),
      bouton("Supprimer", () => {
        const id = m.regle.id;
        S.modal = null;
        action(async () => { await api("DELETE", `${base()}/regles/${id}`); await chargerRegles();
          S.message = { type: "success", titre: "Règle supprimée", texte: `« ${d.nom} »` }; });
      })];
  } else if (m.type === "vider") {
    const traitees = S.journal.filter((l) => l.statut !== "en_attente").length;
    const attente = S.journal.length - traitees;
    titre = "Vider le journal";
    corps = [
      h("p", {}, "Supprimer ", h("strong", { text: pluriel(traitees, "entrée traitée", "entrées traitées") }),
        ` du journal de la démarche ${S.demarche} ?`),
      h("p", { class: "lbl-mention", text: attente
        ? `${pluriel(attente, "opération en attente est conservée", "opérations en attente sont conservées")}. Les labels dans DN ne changent pas.`
        : "Les labels dans DN ne changent pas." }),
      alerte("info", null, "La suppression reste visible dans l'historique du document Grist."),
    ];
    actions = [bouton("Annuler", fermerModal, { type: "secondary" }),
      bouton("Vider le journal", () => {
        S.modal = null;
        action(async () => {
          const r = await api("POST", `${base()}/operations/journal/vider`);
          S.message = { type: "success", titre: "Journal vidé", texte: `${pluriel(r.supprimees, "entrée supprimée", "entrées supprimées")}.` };
          await chargerJournal();
        });
      })];
  } else if (m.type === "retrait") {
    titre = "Retirer un label";
    corps = [h("p", {}, "Retirer le label ", h("span", { class: `fr-tag fr-tag--sm ${classeCouleur(m.label.color)}`, text: m.label.name }),
      ` du dossier ${m.num} ?`),
    h("p", { class: "lbl-mention", text: "Le retrait est envoyé immédiatement à DN." })];
    actions = [bouton("Annuler", fermerModal, { type: "secondary" }),
      bouton("Retirer", () => { const { num, label } = m; S.modal = null; action(() => operer("retirer", label.id, [num])); })];
  } else {
    const n = m.numeros.length;
    const a = m.apercu;
    const trop = n > MAX_LOT;
    titre = m.sens === "ajouter" ? `Ajouter un label à ${pluriel(n, "dossier", "dossiers")}` : `Retirer un label de ${pluriel(n, "dossier", "dossiers")}`;
    const idChk = nouvelId("conf");
    corps = [
      trop ? alerte("warning", null, `Sélectionnez ${MAX_LOT} dossiers au maximum par envoi.`) : null,
      selectChamp("Label", [{ value: "", label: "Choisir un label" }, ...S.catalogue.map((l) => ({ value: l.id, label: l.nom }))],
        m.label, (v) => { m.label = v; m.erreur = null; calculerApercu(); }),
      m.chargement ? h("p", { class: "lbl-mention", text: "Calcul de l'aperçu d'après l'état actuel dans DN…" }) : null,
      m.erreur ? alerte("error", null, m.erreur) : null,
      a ? h("div", { class: "lbl-stats" },
        h("div", { class: "lbl-stat lbl-stat--fort" }, h("strong", { text: String(a.a_faire) }),
          h("span", { text: m.sens === "ajouter" ? "recevront le label" : "perdront le label" })),
        h("div", { class: "lbl-stat" }, h("strong", { text: String(a.deja) }), h("span", { text: "déjà dans l'état voulu" })),
        h("div", { class: "lbl-stat" }, h("strong", { text: String(a.introuvables) }), h("span", { text: "introuvables" })),
        a.hors_perimetre ? h("div", { class: "lbl-stat" }, h("strong", { text: String(a.hors_perimetre) }),
          h("span", { text: "hors de vos groupes (ignorés)" })) : null) : null,
      a && a.a_faire ? h("div", { class: "fr-checkbox-group" },
        h("input", { type: "checkbox", id: idChk, checked: m.coche, onchange: (e) => { m.coche = e.target.checked; rendu(); } }),
        h("label", { class: "fr-label", for: idChk, text: "J'ai vérifié la sélection" })) : null,
    ];
    const pret = a && a.a_faire > 0 && !trop;
    actions = [
      bouton("Annuler", fermerModal, { type: "secondary" }),
      bouton("Mettre en file", () => { const { sens, label, numeros } = m; S.modal = null; action(() => operer(sens, label, numeros, false)); },
        { type: "tertiary", disabled: !pret }),
      bouton("Envoyer à DN", () => {
        const { sens, label, numeros } = m;
        S.modal = null;
        action(async () => { await operer(sens, label, numeros); S.T.selection.clear(); });
      }, { disabled: !pret || !m.coche }),
    ];
  }
  return h("div", { class: "lbl-modal", onclick: (e) => { if (e.target === e.currentTarget) fermerModal(); } },
    h("div", { class: "lbl-modal__boite", role: "dialog", "aria-modal": "true", "aria-labelledby": "lbl-modal-titre" },
      h("div", { class: "lbl-entre" },
        h("h2", { class: "fr-h5 fr-mb-0", id: "lbl-modal-titre", text: titre }),
        h("button", { type: "button", class: "fr-btn--close fr-btn", title: "Fermer", onclick: fermerModal, text: "Fermer" })),
      corps,
      h("div", { class: "lbl-actions lbl-actions--droite" }, actions)));
}

// ------------------------------------------------------------------ autres onglets

// Couleur prise dans le catalogue DN actuel ; un label supprimé depuis reste affiché, en gris.
function pastilleJournal(l) {
  const c = S.catalogue.find((x) => x.id === l.label_id);
  return h("span", { class: `fr-tag fr-tag--sm ${c ? classeCouleur(c.couleur) : ""}`, text: l.label || "?" });
}

function retentionJournal() {
  const j = S.contexte && S.contexte.journal_retention_jours;
  return h("p", { class: "lbl-mention", text: j
    ? `Les entrées traitées de plus de ${pluriel(j, "jour", "jours")} sont supprimées automatiquement ; les opérations en attente sont conservées.`
    : "Les entrées du journal sont conservées sans limite de durée." });
}

function vueFile() {
  const filtres = [["toutes", "Toutes"], ["en_attente", "En attente"], ["applique", "Appliquées"], ["erreur", "Erreurs"]];
  const parNumero = S.journal.filter((l) => !S.rechercheJournal || String(l.dossier_number).includes(S.rechercheJournal));
  const compte = (f) => (f === "toutes" ? parNumero.length : parNumero.filter((l) => l.statut === f).length);
  const lignes = parNumero.filter((l) => S.filtreJournal === "toutes" || l.statut === S.filtreJournal).slice(0, 200);
  const attente = S.journal.filter((l) => l.statut === "en_attente").length;
  const idRech = nouvelId("rechj");
  return h("section", { class: "lbl-carte" },
    h("div", { class: "lbl-entre lbl-entre--centre", "data-lbl-ancre": lignes.length ? "" : null },
      h("div", { class: "lbl-actions" },
        bouton(`Envoyer ${pluriel(attente, "opération en attente", "opérations en attente")}`, () => action(async () => {
          const r = await api("POST", `${base()}/operations/file/envoyer`);
          const t = r.lots.reduce((acc, b) => ({ a: acc.a + b.appliques, d: acc.d + b.deja, e: acc.e + b.erreurs + b.introuvables,
            h: acc.h + (b.hors_perimetre || 0) }), { a: 0, d: 0, e: 0, h: 0 });
          S.message = { type: t.e || t.h ? "warning" : "success", titre: "File envoyée",
            texte: `${t.a} appliquée(s) · ${t.d} déjà dans l'état voulu · ${t.e} erreur(s)`
              + (t.h ? ` · ${t.h} restée(s) en attente (hors de vos groupes)` : "") };
          await chargerJournal();
        }), { disabled: !attente || !peutAgir() }),
        bouton("Actualiser", () => action(chargerJournal), { type: "tertiary", ic: "verifier" }),
        proprietaire() ? bouton("Vider le journal", () => { S.modal = { type: "vider" }; rendu(); },
          { type: "tertiary", ic: "corbeille", disabled: !S.journal.some((l) => l.statut !== "en_attente") }) : null),
      h("div", { class: "fr-input-group fr-mb-0 lbl-champ" },
        h("label", { class: "fr-label lbl-cache", for: idRech, text: "Filtrer par n° de dossier" }),
        h("input", { class: "fr-input", type: "search", id: idRech, placeholder: "N° de dossier", value: S.rechercheJournal,
          inputmode: "numeric", oninput: (e) => { S.rechercheJournal = e.target.value.replace(/\D/g, ""); rendu(); } }))),
    retentionJournal(),
    h("div", { class: "lbl-actions" }, filtres.map(([f, nom]) => h("button", {
      type: "button", class: `fr-btn fr-btn--sm ${S.filtreJournal === f ? "" : "fr-btn--secondary"}`,
      "aria-pressed": S.filtreJournal === f ? "true" : "false",
      onclick: () => { S.filtreJournal = f; rendu(); },
    }, `${nom} (${compte(f)})`))),
    lignes.length
      ? h("div", { class: "fr-table fr-table--bordered fr-table--multiline fr-mb-0 lbl-tableau" },
        h("div", { class: "fr-table__wrapper" }, h("div", { class: "fr-table__container" }, h("div", { class: "fr-table__content" },
          h("table", {},
            h("caption", { class: "lbl-cache", text: "Opérations sur les labels" }),
            h("thead", {}, h("tr", {}, ["Dossier", "Action", "Label", "Source", "Auteur", "Statut", "Date"].map((t) => h("th", { scope: "col", text: t })))),
            h("tbody", {}, lignes.map((l) => h("tr", {},
              h("td", { text: String(l.dossier_number) }),
              h("td", { text: l.action === "ajouter" ? "Ajout" : "Retrait" }),
              h("td", {}, pastilleJournal(l)),
              h("td", { text: l.source }),
              h("td", { class: "lbl-auteur", text: l.auteur || "—" }),
              h("td", {}, badge(...(STATUTS[l.statut] || [l.statut, ""])), l.message ? h("div", { class: "lbl-mention", text: l.message }) : null),
              h("td", { text: dateEpoch(l.traite_le || l.cree_le) })))))))))
      : h("p", { class: "lbl-mention", text: "Aucune opération." }));
}

// ------------------------------------------------------------------ onglet Règles

const LIB_OPS = {
  egal: "est égal à", different: "est différent de", contient: "contient", ne_contient_pas: "ne contient pas",
  sup: "est supérieur à", sup_egal: "est supérieur ou égal à", inf: "est inférieur à", inf_egal: "est inférieur ou égal à",
  plus_ancien_que: "plus ancien que (jours)", plus_recent_que: "plus récent que (jours)", avant: "avant le", apres: "après le",
  vide: "est vide", non_vide: "n'est pas vide", coche: "est coché", non_coche: "n'est pas coché",
  a_le_label: "a le label", n_a_pas_le_label: "n'a pas le label",
};
const MODES = { simulation: ["Simulation", "fr-badge--info"], auto: ["Automatique", "fr-badge--success"], desactivee: ["Désactivée", ""] };

async function chargerRegles() {
  const [schema, liste] = await Promise.all([api("GET", `${base()}/regles/schema`), api("GET", `${base()}/regles`)]);
  S.R.schema = schema;
  S.R.regles = liste.regles;
}

const champDe = (ref) => (S.R.schema ? S.R.schema.champs.find((c) => c.ref === ref) : null);
function libelleChamp(c) {
  if (!c) return "?";
  const col = c.ref.includes(".") ? c.ref.split(".")[1] : c.ref;
  return c.libelle && c.libelle !== col ? c.libelle : libelleColonne(col);
}
const opsDe = (ref) => { const c = champDe(ref); return c ? S.R.schema.operateurs[c.famille] : []; };
const sansValeur = (op) => S.R.schema && S.R.schema.sans_valeur.includes(op);
const nomLabel = (id) => (S.catalogue.find((l) => l.id === id) || { nom: id }).nom;

function conditionVide() {
  const premier = S.R.schema.champs.find((c) => c.ref === "d.state") || S.R.schema.champs[0];
  return { champ: premier.ref, operateur: opsDe(premier.ref)[0], valeur: "" };
}

function nouvelleRegle() {
  S.R.edition = { id: null, def: { nom: "", action: "ajouter", label_id: S.catalogue[0] ? S.catalogue[0].id : "",
    mode: "simulation", verrou: true, groupes: [[conditionVide()]] } };
  S.R.simulation = null;
  S.R.erreur = null;
  rendu();
}

function modifierRegle(r) {
  S.R.edition = { id: r.id, def: JSON.parse(JSON.stringify(r.definition)) };
  S.R.simulation = null;
  S.R.erreur = null;
  rendu();
}

function resumeConditions(def) {
  return def.groupes.map((g) => g.map((c) => {
    const nom = libelleChamp(champDe(c.champ));
    if (sansValeur(c.operateur)) return `${nom} ${LIB_OPS[c.operateur]}`;
    if (c.operateur === "plus_ancien_que") return `${nom} plus ancien que ${c.valeur} jours`;
    if (c.operateur === "plus_recent_que") return `${nom} plus récent que ${c.valeur} jours`;
    let v = c.valeur;
    if (c.champ === "labels") v = nomLabel(c.valeur);
    else if (c.champ === "d.state" && ETATS[v]) v = ETATS[v][0];
    else if (c.operateur === "avant" || c.operateur === "apres") v = new Date(`${v}T00:00:00`).toLocaleDateString("fr-FR");
    return `${nom} ${LIB_OPS[c.operateur] || c.operateur} « ${v} »`;
  }).join(" ET ")).join(" — OU — ");
}

function definitionPropre(def) {
  return { ...def, nom: def.nom.trim(),
    groupes: def.groupes.map((g) => g.map((c) => ({ champ: c.champ, operateur: c.operateur, valeur: sansValeur(c.operateur) ? null : c.valeur }))) };
}

async function simulerEdition() {
  const e = S.R.edition;
  const q = e.id ? `?regle_id=${e.id}` : "";
  S.R.erreur = null;
  try {
    S.R.simulation = await api("POST", `${base()}/regles/simuler${q}`, definitionPropre(e.def));
  } catch (err) {
    S.R.simulation = null;
    S.R.erreur = err.message;
  }
}

async function enregistrerRegle() {
  const e = S.R.edition;
  S.R.erreur = null;
  try {
    if (e.id) await api("PUT", `${base()}/regles/${e.id}`, definitionPropre(e.def));
    else await api("POST", `${base()}/regles`, definitionPropre(e.def));
  } catch (err) {
    S.R.erreur = err.message;
    return;
  }
  S.message = { type: "success", titre: "Règle enregistrée", texte: `« ${e.def.nom.trim()} »` };
  S.R.edition = null;
  S.R.simulation = null;
  await chargerRegles();
}

// Valeurs proposées pour une colonne (choix déclarés + valeurs présentes), chargées une fois par colonne.
function valeursDe(ref) {
  const cache = S.R.valeurs;
  if (!(ref in cache)) {
    cache[ref] = null; // chargement en cours
    api("GET", `${base()}/regles/valeurs?champ=${encodeURIComponent(ref)}`)
      .then((v) => { cache[ref] = v; })
      .catch(() => { cache[ref] = { valeurs: [], complet: false }; })
      .finally(() => { if (S.onglet === "regles" && S.R.edition) rendu(); });
  }
  return cache[ref];
}

function champValeur(c, idx) {
  const ch = champDe(c.champ);
  if (!ch || sansValeur(c.operateur)) return h("div", { class: "lbl-cond__valeur" });
  const id = `val-${idx}`;
  const maj = (e) => { c.valeur = e.target.value; S.R.simulation = null; };
  let champ;
  if (c.champ === "d.state" && (c.operateur === "egal" || c.operateur === "different")) {
    if (!c.valeur) c.valeur = "en_construction";
    champ = h("select", { class: "fr-select", id, onchange: (e) => { maj(e); rendu(); } },
      Object.entries(ETATS).map(([v, [lib]]) => h("option", { value: v, selected: v === c.valeur, text: lib })));
  } else if (ch.famille === "labels") {
    if (!c.valeur && S.catalogue[0]) c.valeur = S.catalogue[0].id;
    champ = h("select", { class: "fr-select", id, onchange: (e) => { maj(e); rendu(); } },
      S.catalogue.map((l) => h("option", { value: l.id, selected: l.id === c.valeur, text: l.nom })));
  } else if (c.operateur === "avant" || c.operateur === "apres") {
    champ = h("input", { class: "fr-input", type: "date", id, value: c.valeur || "", oninput: maj });
  } else if ((ch.famille === "nombre" && c.operateur !== "egal" && c.operateur !== "different")
    || c.operateur === "plus_ancien_que" || c.operateur === "plus_recent_que") {
    champ = h("input", { class: "fr-input", type: "number", id, value: c.valeur ?? "", min: ch.famille === "date" ? "0" : null, oninput: maj });
  } else {
    const v = valeursDe(c.champ);
    const exact = c.operateur === "egal" || c.operateur === "different";
    if (exact && v && v.complet && v.valeurs.length) {
      // Menu déroulant des valeurs existantes ; une valeur saisie auparavant reste proposée.
      const options = c.valeur && !v.valeurs.includes(String(c.valeur)) ? [String(c.valeur), ...v.valeurs] : v.valeurs;
      champ = h("select", { class: "fr-select", id, onchange: (e) => { maj(e); rendu(); } },
        h("option", { value: "", disabled: true, selected: !c.valeur, text: "Choisir une valeur" }),
        options.map((x) => h("option", { value: x, selected: x === String(c.valeur), text: x })));
    } else {
      const liste = `dl-${idx}`;
      champ = [
        h("input", { class: "fr-input", type: ch.famille === "nombre" ? "number" : "text", id, value: c.valeur ?? "",
          maxlength: "500", list: v && v.valeurs.length ? liste : null, oninput: maj,
          placeholder: v === null ? "Chargement des valeurs…" : (v.valeurs.length ? "Saisir ou choisir" : "") }),
        v && v.valeurs.length ? h("datalist", { id: liste }, v.valeurs.map((x) => h("option", { value: x }))) : null,
      ];
    }
  }
  return h("div", { class: "fr-input-group lbl-cond__valeur" }, h("label", { class: "fr-label lbl-cache", for: id, text: "Valeur" }), champ);
}

function ligneCondition(groupe, c, gi, ci) {
  const sources = [...new Set(S.R.schema.champs.map((x) => x.source))];
  const idC = `cond-${gi}-${ci}`;
  const idO = `op-${gi}-${ci}`;
  return h("div", { class: "lbl-cond" },
    h("div", { class: "fr-select-group lbl-cond__champ" },
      h("label", { class: "fr-label lbl-cache", for: idC, text: "Colonne" }),
      h("select", { class: "fr-select", id: idC, onchange: (e) => {
        c.champ = e.target.value; c.operateur = opsDe(c.champ)[0]; c.valeur = ""; S.R.simulation = null; rendu();
      } }, sources.map((src) => h("optgroup", { label: src },
        S.R.schema.champs.filter((x) => x.source === src).map((x) => h("option", { value: x.ref, selected: x.ref === c.champ, text: libelleChamp(x) })))))),
    h("div", { class: "fr-select-group lbl-cond__op" },
      h("label", { class: "fr-label lbl-cache", for: idO, text: "Condition" }),
      h("select", { class: "fr-select", id: idO, onchange: (e) => { c.operateur = e.target.value; c.valeur = ""; S.R.simulation = null; rendu(); } },
        opsDe(c.champ).map((o) => h("option", { value: o, selected: o === c.operateur, text: LIB_OPS[o] || o })))),
    champValeur(c, `${gi}-${ci}`),
    h("button", { type: "button", class: "fr-btn fr-btn--tertiary fr-btn--sm lbl-btn-icone", id: `suppr-${gi}-${ci}`,
      title: "Supprimer la condition", "aria-label": "Supprimer la condition",
      onclick: () => {
        groupe.splice(ci, 1);
        if (!groupe.length) S.R.edition.def.groupes.splice(gi, 1);
        if (!S.R.edition.def.groupes.length) S.R.edition.def.groupes.push([conditionVide()]);
        S.R.simulation = null; rendu();
      } }, icone("fermer")));
}

function editeurRegle() {
  const e = S.R.edition;
  const def = e.def;
  const sim = S.R.simulation;
  const autoOk = S.R.schema.auto_autorise;
  const radio = (val, texte, aide, disabled) => {
    const id = `mode-${val}`;
    return h("div", { class: "fr-fieldset__element" }, h("div", { class: "fr-radio-group" },
      h("input", { type: "radio", id, name: "lbl-mode", value: val, checked: def.mode === val, disabled,
        onchange: () => { def.mode = val; rendu(); } }),
      h("label", { class: "fr-label", for: id }, texte, h("span", { class: "fr-hint-text", text: aide }))));
  };
  return h("section", { class: "lbl-carte", "aria-labelledby": "lbl-titre-edition" },
    h("h2", { class: "fr-h5 fr-mb-0", id: "lbl-titre-edition", text: e.id ? `Modifier « ${def.nom} »` : "Nouvelle règle" }),
    h("div", { class: "lbl-regle-entete" },
      h("div", { class: "fr-input-group" },
        h("label", { class: "fr-label", for: "regle-nom", text: "Nom de la règle" }),
        h("input", { class: "fr-input", id: "regle-nom", value: def.nom, maxlength: "120", oninput: (ev) => { def.nom = ev.target.value; } })),
      selectChamp("Action", [{ value: "ajouter", label: "Ajouter le label" }, { value: "retirer", label: "Retirer le label" }],
        def.action, (v) => { def.action = v; S.R.simulation = null; rendu(); }),
      selectChamp("Label", S.catalogue.map((l) => ({ value: l.id, label: l.nom })), def.label_id,
        (v) => { def.label_id = v; S.R.simulation = null; rendu(); })),
    h("div", { class: "lbl-pile" },
      h("h3", { class: "fr-text--md fr-text--bold fr-mb-0", text: "Quand" }),
      def.groupes.map((g, gi) => [
        gi > 0 ? h("div", { class: "lbl-ou", "aria-hidden": "true" }, h("span", { text: "OU" })) : null,
        h("div", { class: "lbl-groupe", role: "group", "aria-label": `Groupe ${gi + 1}` },
          h("p", { class: "lbl-groupe__titre", text: `Groupe ${gi + 1} — toutes ces conditions (ET)` }),
          g.map((c, ci) => ligneCondition(g, c, gi, ci)),
          h("button", { type: "button", class: "fr-btn fr-btn--tertiary-no-outline fr-btn--sm lbl-btn", id: `ajout-et-${gi}`,
            onclick: () => { g.push(conditionVide()); S.R.simulation = null; rendu(); } }, icone("plus"), "Ajouter une condition (ET)")),
      ]),
      h("div", {}, h("button", { type: "button", class: "fr-btn fr-btn--secondary fr-btn--sm lbl-btn", id: "ajout-ou",
        disabled: def.groupes.length >= 10,
        onclick: () => { def.groupes.push([conditionVide()]); S.R.simulation = null; rendu(); } }, icone("plus"), "Ajouter un groupe (OU)"))),
    h("fieldset", { class: "fr-fieldset fr-mb-0" },
      h("legend", { class: "fr-fieldset__legend fr-text--regular", text: "Mode" }),
      radio("simulation", "Simulation", "Calcule seulement les dossiers concernés ; vous appliquez à la main.", false),
      radio("auto", "Automatique", autoOk ? "Appliquée à chaque synchronisation planifiée, sans intervention."
        : "Désactivé par la configuration du serveur.", !autoOk),
      radio("desactivee", "Désactivée", "Conservée mais jamais exécutée.", false)),
    h("div", { class: "fr-checkbox-group" },
      h("input", { type: "checkbox", id: "regle-verrou", checked: def.verrou, onchange: (ev) => { def.verrou = ev.target.checked; } }),
      h("label", { class: "fr-label", for: "regle-verrou" }, "Ne pas refaire ce qu'une personne a défait",
        h("span", { class: "fr-hint-text", text: "Si quelqu'un retire (ou remet) le label à la main, la règle ne revient plus sur ce dossier." }))),
    S.R.erreur ? alerte("error", "Règle invalide", S.R.erreur) : null,
    sim ? alerte("info", `Simulation : ${pluriel(sim.correspondants, "dossier remplit", "dossiers remplissent")} les conditions`,
      `${sim.a_faire} à ${def.action === "ajouter" ? "étiqueter" : "désétiqueter"} · ${sim.deja} déjà dans l'état voulu`
      + (sim.verrouilles ? ` · ${sim.verrouilles} laissé(s) de côté (modifiés à la main)` : "")
      + (sim.numeros_a_faire.length ? ` — ex. : ${sim.numeros_a_faire.slice(0, 8).join(", ")}${sim.a_faire > 8 ? "…" : ""}` : "")) : null,
    h("div", { class: "lbl-actions lbl-actions--droite" },
      bouton("Annuler", () => { S.R.edition = null; S.R.simulation = null; S.R.erreur = null; rendu(); }, { type: "secondary" }),
      bouton("Simuler", () => action(simulerEdition), { type: "tertiary", ic: "verifier" }),
      bouton("Enregistrer", () => {
        if (!def.nom.trim()) { S.R.erreur = "Donnez un nom à la règle."; rendu(); return; }
        action(enregistrerRegle);
      })));
}

function listeRegles() {
  const R = S.R;
  if (!R.regles.length) {
    return h("div", { class: "lbl-carte" }, h("p", { class: "lbl-mention", text: "Aucune règle pour cette démarche. Créez-en une pour poser ou retirer un label automatiquement selon des conditions." }));
  }
  const tableau = h("div", { class: "fr-table fr-table--bordered fr-table--multiline fr-mb-0 lbl-tableau" },
    h("div", { class: "fr-table__wrapper" }, h("div", { class: "fr-table__container" }, h("div", { class: "fr-table__content" },
      h("table", {},
        h("caption", { class: "lbl-cache", text: "Règles de la démarche" }),
        h("thead", {}, h("tr", {}, ["Règle", "Conditions", "Mode", "Dernière exécution", "Actions"].map((t) => h("th", { scope: "col", text: t })))),
        h("tbody", {}, R.regles.map((r) => {
          if (!r.definition) return h("tr", {}, h("td", { colspan: "5" }, alerte("error", null, r.erreur)));
          const d = r.definition;
          const proprio = proprietaire();
          const lab = S.catalogue.find((l) => l.id === d.label_id);
          return h("tr", {},
            h("td", {}, h("strong", { text: d.nom }), h("div", { class: "lbl-ligne lbl-ligne--centre" },
              h("span", { class: "lbl-mention", text: d.action === "ajouter" ? "Ajouter" : "Retirer" }),
              h("span", { class: `fr-tag fr-tag--sm ${lab ? classeCouleur(lab.couleur) : ""}`, text: lab ? lab.nom : r.label || "?" }))),
            h("td", { class: "lbl-resume", text: resumeConditions(d) }),
            h("td", {}, badge(...MODES[d.mode]), r.erreur ? h("p", { class: "fr-error-text fr-mt-1v fr-mb-0", text: r.erreur }) : null),
            h("td", {}, r.derniere_execution ? [h("div", { text: dateEpoch(r.derniere_execution) }),
              h("div", { class: "lbl-mention", text: r.dernier_resultat || "" })] : h("span", { class: "lbl-mention", text: "jamais" })),
            h("td", {}, proprio ? h("div", { class: "lbl-actions-ligne" },
              bouton(r.erreur ? "Réenregistrer" : "Modifier", () => modifierRegle(r), { type: "tertiary", taille: "sm" }),
              bouton("Appliquer maintenant", () => action(async () => {
                const sim = await api("POST", `${base()}/regles/simuler?regle_id=${r.id}`, d);
                S.modal = { type: "regle", regle: r, sim };
              }), { type: "secondary", taille: "sm", disabled: d.mode === "desactivee" || Boolean(r.erreur) }),
              h("button", { type: "button", class: "fr-btn fr-btn--tertiary-no-outline fr-btn--sm lbl-btn-icone",
                title: `Supprimer la règle ${d.nom}`, "aria-label": `Supprimer la règle ${d.nom}`, disabled: S.occupe,
                onclick: () => { S.modal = { type: "suppr-regle", regle: r }; rendu(); } }, icone("corbeille")))
              : h("span", { class: "lbl-mention", text: "Réservé aux propriétaires" })));
        })))))));
  return tableau;
}

function vueRegles() {
  if (!S.R.schema) return h("p", { class: "lbl-mention", text: "Chargement des règles…" });
  return [
    h("div", { class: "lbl-entre lbl-entre--centre" },
      h("h2", { class: "fr-h4 fr-mb-0", text: pluriel(S.R.regles.length, "règle", "règles") }),
      S.R.edition || !proprietaire() ? null : bouton("Nouvelle règle", nouvelleRegle, { taille: "sm", ic: "plus" })),
    proprietaire() ? null : alerte("info", null, "Les règles automatiques sont gérées par les propriétaires du document Grist. "
      + "Vous pouvez les consulter."),
    h("p", { class: "lbl-mention", text: "Une règle pose ou retire un label sur les dossiers qui remplissent au moins un groupe de conditions. "
      + "Les conditions portent sur les colonnes synchronisées par OTP (dossier, champs du formulaire, annotations privées) et sur les labels." }),
    S.R.edition ? editeurRegle() : null,
    listeRegles(),
  ];
}

// ------------------------------------------------------------------ rendu

function rendu() {
  const app = document.getElementById("app");
  if (!S.contexte) return;
  compteurIds = 0; // identifiants stables d'un rendu à l'autre (restauration du focus)
  const vues = { dossiers: vueDossiers, file: vueFile, regles: vueRegles };
  const focus = document.activeElement && document.activeElement.id;
  // replaceChildren écrirait « null » en texte : on ne passe que des nœuds
  app.replaceChildren(...[
    enTete(),
    bandeauDroits(),
    onglets(),
    h("main", { class: "lbl-main" },
      S.message ? alerte(S.message.type, S.message.titre, S.message.texte) : null,
      S.occupe ? h("div", { class: "lbl-progression", role: "progressbar", "aria-label": "Traitement en cours" },
        h("div", { class: "lbl-progression__barre" })) : null,
      etatSynchroEnCours(),
      vues[S.onglet]()),
    boutonHaut(),
    modale(),
  ].filter(Boolean));
  surveillerAncre();
  const cible = focus && document.getElementById(focus);
  if (cible) {
    cible.focus();
    if (cible.tagName === "INPUT" && cible.type === "search") cible.setSelectionRange(cible.value.length, cible.value.length);
  } else if (S.modal) {
    const premier = document.querySelector(".lbl-modal__boite select, .lbl-modal__boite button:not(.fr-btn--close)");
    if (premier) premier.focus();
  }
}

// ------------------------------------------------------------------ retour en haut

// Apparaît dès que la zone d'actions marquée [data-lbl-ancre] (au-dessus d'un tableau) sort de l'écran par le haut.
function boutonHaut() {
  return h("button", {
    type: "button", class: "lbl-haut", id: "lbl-haut", title: "Retour en haut", "aria-label": "Retour en haut", hidden: true,
    onclick: () => {
      const reduit = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      window.scrollTo({ top: 0, behavior: reduit ? "auto" : "smooth" });
      // Le focus revient sur la première action disponible (sinon le premier champ de la page)
      const cible = document.querySelector("[data-lbl-ancre] button:not(:disabled), [data-lbl-ancre] input")
        || document.querySelector(".lbl-main select, .lbl-main input, .lbl-main button:not(:disabled)");
      if (cible) cible.focus({ preventScroll: true });
    },
  }, icone("haut"));
}

let observateur = null;
function surveillerAncre() {
  if (observateur) observateur.disconnect();
  const ancre = document.querySelector("[data-lbl-ancre]");
  const btn = document.getElementById("lbl-haut");
  if (!btn) return;
  if (!ancre || !("IntersectionObserver" in window)) { btn.hidden = true; return; }
  observateur = new IntersectionObserver(([e]) => { btn.hidden = e.isIntersecting || e.boundingClientRect.top > 0; });
  observateur.observe(ancre);
}

// ------------------------------------------------------------------ démarrage

async function demarrer() {
  const app = document.getElementById("app");
  try {
    S.contexte = await api("GET", "/api/contexte");
    let tableId = null;
    try { tableId = await grist.selectedTable.getTableId(); } catch { /* API absente */ }
    const m = /^Demarche_(\d+)_dossiers$/.exec(tableId || "");
    const parTable = m && S.contexte.demarches.find((d) => d.numero === Number(m[1]));
    S.demarche = (parTable || S.contexte.demarches[0]).numero;
    await chargerDemarche();
    rendu();
  } catch (e) {
    app.replaceChildren(h("div", { class: "fr-p-3w" }, alerte("error", "Le widget ne peut pas démarrer", e.message),
      h("p", { class: "lbl-mention fr-mt-2w", text: "Vérifiez que le widget a l'accès complet au document et que le document est déclaré dans demarches.yaml." })));
  }
}

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (S.modal) fermerModal();
  else if (S.ajoutPour !== null) { S.ajoutPour = null; rendu(); }
  else if (S.T.personnaliser) fermerPersonnaliser();
});

grist.ready({ requiredAccess: "full", allowSelectBy: false });
grist.onOptions((options) => {
  S.T.colonnesDoc = colonnesValides(options && options.colonnes);
  appliquerColonnes();
  rendu();
});
// « normal » : toutes les colonnes de la table, même masquées dans le widget (dont groupe_instructeur_number
// et les colonnes ajoutées après coup) ; par défaut Grist ne transmet que les colonnes affichées.
grist.onRecords((recs) => { S.records = recs || []; rendu(); }, { includeColumns: "normal" });
demarrer();
