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
  T: {
    page: 1, recherche: "", etat: "", label: "", tri: { col: "__num", sens: "desc" },
    colonnes: [], personnaliser: false, selection: new Set(),
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

async function chargerDemarche() {
  const [cat, synchro] = await Promise.all([api("GET", `${base()}/catalogue`), api("GET", `${base()}/synchro`)]);
  S.catalogue = cat.labels;
  S.synchro = synchro;
  await chargerJournal();
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
  const parts = [];
  if (b.appliques) parts.push(`${b.appliques} appliqué(s)`);
  if (b.deja) parts.push(`${b.deja} déjà dans l'état voulu`);
  if (b.en_file) parts.push(`${b.en_file} mis en file`);
  if (b.introuvables) parts.push(`${b.introuvables} introuvable(s)`);
  if (b.erreurs) parts.push(`${b.erreurs} erreur(s)`);
  const verbe = b.action === "ajouter" ? "Ajout" : "Retrait";
  return { type: b.erreurs || b.introuvables ? "warning" : "success",
    titre: `${verbe} de « ${b.label.nom} »`, texte: parts.join(" · ") || "Aucun changement." };
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
      h("button", { type: "button", class: "fr-link fr-link--sm lbl-lien", disabled: S.occupe,
        title: "Relit tous les dossiers de la démarche dans DN (à utiliser en cas de doute)",
        onclick: () => action(() => lancerSynchro("complete")) }, "Relecture complète")));
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
      onclick: () => { S.onglet = id; S.message = null; if (id === "file") action(chargerJournal); else rendu(); },
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

function enregistrerColonnes(colonnes) {
  S.T.colonnes = colonnes;
  rendu();
  grist.setOptions({ colonnes }).catch(() => {
    S.message = { type: "warning", titre: "Configuration non enregistrée", texte: "Elle sera perdue au rechargement." };
    rendu();
  });
}

function lignesFiltrees() {
  const T = S.T;
  const toutes = S.records.map((r) => ({ r, num: numeroDe(r), labels: labelsDuRecord(r) })).filter((l) => l.num);
  let lignes = toutes;
  if (T.recherche) lignes = lignes.filter((l) => String(l.num).includes(T.recherche));
  if (T.etat) lignes = lignes.filter((l) => l.r.state === T.etat);
  if (T.label === "__sans") lignes = lignes.filter((l) => !l.labels.length);
  else if (T.label) lignes = lignes.filter((l) => l.labels.some((x) => x.id === T.label));
  const cle = T.tri.col === "__num" ? (l) => l.num : T.tri.col === "__labels" ? (l) => l.labels.length : (l) => l.r[T.tri.col];
  lignes.sort((a, b) => comparer(cle(a), cle(b)) * (T.tri.sens === "asc" ? 1 : -1));
  return { toutes, lignes };
}

function panneauFiltres(toutes) {
  const T = S.T;
  const etats = [...new Set(toutes.map((l) => l.r.state).filter(Boolean))];
  const idRech = nouvelId("rech");
  const compte = new Map();
  let sans = 0;
  for (const l of toutes) {
    if (!l.labels.length) sans++;
    for (const x of l.labels) compte.set(x.id, (compte.get(x.id) || 0) + 1);
  }
  const filtrer = (id) => () => { T.label = T.label === id ? "" : id; T.page = 1; rendu(); };
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
        ...S.catalogue.map((l) => ({ value: l.id, label: l.nom }))], T.label, (v) => { T.label = v; T.page = 1; rendu(); })),
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
  const dispo = colonnesDisponibles();
  const choisies = S.T.colonnes;
  return h("section", { class: "lbl-personnaliser", "aria-label": "Personnaliser le tableau" },
    h("p", { class: "lbl-mention", text: "Colonnes affichées en plus du numéro et des labels. Le choix est enregistré dans le document Grist." }),
    dispo.length
      ? h("fieldset", { class: "fr-fieldset lbl-colonnes" },
        h("legend", { class: "lbl-cache", text: "Colonnes à afficher" }),
        dispo.map((c) => {
          const id = nouvelId("col");
          return h("div", { class: "fr-fieldset__element" }, h("div", { class: "fr-checkbox-group fr-checkbox-group--sm" },
            h("input", { type: "checkbox", id, checked: choisies.includes(c),
              onchange: (e) => enregistrerColonnes(e.target.checked ? [...choisies, c] : choisies.filter((x) => x !== c)) }),
            h("label", { class: "fr-label", for: id, text: libelleColonne(c) })));
        }))
      : h("p", { class: "lbl-mention", text: "Aucune autre colonne transmise au widget." }));
}

function caseLigne(libelle, coche, onchange, { indetermine = false } = {}) {
  const id = nouvelId("chk");
  const input = h("input", { type: "checkbox", id, checked: coche, onchange: (e) => onchange(e.target.checked) });
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
  const toutesSelectionnees = lignes.length > 0 && lignes.every((l) => T.selection.has(l.num));
  return h("div", { class: "lbl-barre-selection", role: "region", "aria-label": "Actions sur la sélection",
    "data-lbl-ancre": lignes.length ? "" : null },
    h("span", { class: "lbl-barre-selection__compte", text: n ? pluriel(n, "dossier sélectionné", "dossiers sélectionnés") : "0 dossier sélectionné" }),
    bouton("Ajouter un label", ouvrirMasse("ajouter"), { type: "tertiary", taille: "sm", ic: "plus", disabled: !n }),
    bouton("Retirer un label", ouvrirMasse("retirer"), { type: "tertiary", taille: "sm", ic: "moins", disabled: !n }),
    bouton("Vérifier dans DN", () => action(() => lancerSynchro("ciblee", nums)),
      { type: "tertiary", taille: "sm", ic: "verifier", disabled: !n || n > MAX_LOT }),
    !toutesSelectionnees && lignes.length && n
      ? h("button", { type: "button", class: "fr-link fr-link--sm lbl-lien",
        onclick: () => { for (const l of lignes) T.selection.add(l.num); rendu(); } },
        `Sélectionner les ${lignes.length} dossiers filtrés`)
      : null,
    n ? h("button", { type: "button", class: "fr-link fr-link--sm lbl-lien",
      onclick: () => { T.selection.clear(); rendu(); } }, "Tout désélectionner") : null);
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
  const { toutes, lignes } = lignesFiltrees();
  const presents = new Set(toutes.map((l) => l.num));
  for (const n of [...T.selection]) if (!presents.has(n)) T.selection.delete(n); // sortis du périmètre
  const cols = T.colonnes.filter((c) => colonnesDisponibles().includes(c));
  const pages = Math.max(1, Math.ceil(lignes.length / PAR_PAGE));
  T.page = Math.min(T.page, pages);
  const page = lignes.slice((T.page - 1) * PAR_PAGE, T.page * PAR_PAGE);
  const nbPageSel = page.filter((l) => T.selection.has(l.num)).length;
  const basculer = (num) => (c) => { if (c) T.selection.add(num); else T.selection.delete(num); rendu(); };
  const lienDN = (num) => `https://demarche.numerique.gouv.fr/procedures/${S.demarche}/dossiers/${num}`;

  const tableau = h("div", { class: "fr-table fr-table--bordered fr-table--multiline fr-mb-0 lbl-tableau" },
    h("div", { class: "fr-table__wrapper" }, h("div", { class: "fr-table__container" }, h("div", { class: "fr-table__content" },
      h("table", {},
        h("caption", { class: "lbl-cache", text: "Dossiers de la démarche" }),
        h("thead", {}, h("tr", {},
          h("th", { class: "fr-cell--fixed", role: "columnheader" },
            caseLigne("Sélectionner tous les dossiers de la page", page.length > 0 && nbPageSel === page.length, (c) => {
              for (const l of page) { if (c) T.selection.add(l.num); else T.selection.delete(l.num); }
              rendu();
            }, { indetermine: nbPageSel > 0 && nbPageSel < page.length })),
          enteteTriable("N° dossier", "__num"),
          cols.map((c) => enteteTriable(libelleColonne(c), c)),
          enteteTriable("Labels", "__labels"),
          h("th", { scope: "col", text: "Actions" }))),
        h("tbody", {}, page.map((l) => h("tr", { "aria-selected": T.selection.has(l.num) ? "true" : "false" },
          h("th", { class: "fr-cell--fixed", scope: "row" },
            caseLigne(`Sélectionner le dossier ${l.num}`, T.selection.has(l.num), basculer(l.num))),
          h("td", {}, h("a", { class: "fr-link", href: lienDN(l.num), target: "_blank", rel: "noopener noreferrer",
            title: `Ouvrir le dossier ${l.num} dans DN (nouvelle fenêtre)`, text: String(l.num) })),
          cols.map((c) => h("td", {}, valeurCellule(c, l.r[c]))),
          h("td", {}, l.labels.length
            ? h("div", { class: "lbl-tags lbl-tags--pile" }, l.labels.map((x) => h("button", {
              type: "button", class: `fr-tag fr-tag--sm fr-tag--dismiss ${classeCouleur(x.color)}`, disabled: S.occupe,
              "aria-label": `Retirer le label ${x.name} du dossier ${l.num}`,
              onclick: () => { S.modal = { type: "retrait", num: l.num, label: x }; rendu(); },
            }, x.name)))
            : h("span", { class: "lbl-mention", text: "—" })),
          h("td", {},
            bouton("Ajouter un label", () => { S.ajoutPour = S.ajoutPour === l.num ? null : l.num; rendu(); },
              { type: "secondary", taille: "sm", ic: "plus" }),
            S.ajoutPour === l.num ? menuAjout(l) : null)))))))));

  const pagination = pages > 1 ? h("nav", { class: "fr-pagination", "aria-label": "Pagination" },
    h("ul", { class: "fr-pagination__list" },
      h("li", {}, h("button", { type: "button", class: "fr-pagination__link fr-pagination__link--prev fr-pagination__link--lg-label",
        disabled: T.page <= 1, onclick: () => { T.page--; rendu(); } }, "Précédente")),
      h("li", {}, h("span", { class: "fr-pagination__link", "aria-current": "page", text: `Page ${T.page} / ${pages}` })),
      h("li", {}, h("button", { type: "button", class: "fr-pagination__link fr-pagination__link--next fr-pagination__link--lg-label",
        disabled: T.page >= pages, onclick: () => { T.page++; rendu(); } }, "Suivante")))) : null;

  return [
    panneauFiltres(toutes),
    h("div", { class: "lbl-entre lbl-entre--centre" },
      h("h2", { class: "fr-h4 fr-mb-0", text: pluriel(lignes.length, "dossier", "dossiers") }),
      h("button", {
        type: "button", class: "fr-btn fr-btn--tertiary fr-btn--sm lbl-btn", "aria-expanded": T.personnaliser ? "true" : "false",
        onclick: () => { T.personnaliser = !T.personnaliser; rendu(); },
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
  if (m.type === "retrait") {
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
        h("div", { class: "lbl-stat" }, h("strong", { text: String(a.introuvables) }), h("span", { text: "introuvables" }))) : null,
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
          const t = r.lots.reduce((acc, b) => ({ a: acc.a + b.appliques, d: acc.d + b.deja, e: acc.e + b.erreurs + b.introuvables }), { a: 0, d: 0, e: 0 });
          S.message = { type: t.e ? "warning" : "success", titre: "File envoyée",
            texte: `${t.a} appliquée(s) · ${t.d} déjà dans l'état voulu · ${t.e} erreur(s)` };
          await chargerJournal();
        }), { disabled: !attente }),
        bouton("Actualiser", () => action(chargerJournal), { type: "tertiary", ic: "verifier" })),
      h("div", { class: "fr-input-group fr-mb-0 lbl-champ" },
        h("label", { class: "fr-label lbl-cache", for: idRech, text: "Filtrer par n° de dossier" }),
        h("input", { class: "fr-input", type: "search", id: idRech, placeholder: "N° de dossier", value: S.rechercheJournal,
          inputmode: "numeric", oninput: (e) => { S.rechercheJournal = e.target.value.replace(/\D/g, ""); rendu(); } }))),
    h("div", { class: "lbl-actions" }, filtres.map(([f, nom]) => h("button", {
      type: "button", class: `fr-btn fr-btn--sm ${S.filtreJournal === f ? "" : "fr-btn--secondary"}`,
      "aria-pressed": S.filtreJournal === f ? "true" : "false",
      onclick: () => { S.filtreJournal = f; rendu(); },
    }, `${nom} (${compte(f)})`))),
    lignes.length
      ? h("div", { class: "fr-table fr-table--bordered fr-table--multiline fr-mb-0" },
        h("div", { class: "fr-table__wrapper" }, h("div", { class: "fr-table__container" }, h("div", { class: "fr-table__content" },
          h("table", {},
            h("caption", { class: "lbl-cache", text: "Opérations sur les labels" }),
            h("thead", {}, h("tr", {}, ["Dossier", "Action", "Label", "Source", "Statut", "Date"].map((t) => h("th", { scope: "col", text: t })))),
            h("tbody", {}, lignes.map((l) => h("tr", {},
              h("td", { text: String(l.dossier_number) }),
              h("td", { text: l.action === "ajouter" ? "Ajout" : "Retrait" }),
              h("td", { text: l.label }),
              h("td", { text: l.source }),
              h("td", {}, badge(...(STATUTS[l.statut] || [l.statut, ""])), l.message ? h("div", { class: "lbl-mention", text: l.message }) : null),
              h("td", { text: dateEpoch(l.traite_le || l.cree_le) })))))))))
      : h("p", { class: "lbl-mention", text: "Aucune opération." }));
}

function vueRegles() {
  return alerte("info", "Bientôt disponible", "Les règles automatiques ET / OU arrivent dans la prochaine version (phase 5).");
}

// ------------------------------------------------------------------ rendu

function rendu() {
  const app = document.getElementById("app");
  if (!S.contexte) return;
  compteurIds = 0; // identifiants stables d'un rendu à l'autre (restauration du focus)
  const vues = { dossiers: vueDossiers, file: vueFile, regles: vueRegles };
  const focus = document.activeElement && document.activeElement.id;
  app.replaceChildren(
    enTete(),
    onglets(),
    h("main", { class: "lbl-main" },
      S.message ? alerte(S.message.type, S.message.titre, S.message.texte) : null,
      S.occupe ? h("div", { class: "lbl-progression", role: "progressbar", "aria-label": "Traitement en cours" },
        h("div", { class: "lbl-progression__barre" })) : null,
      etatSynchroEnCours(),
      vues[S.onglet]()),
    boutonHaut(),
    modale());
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
});

grist.ready({ requiredAccess: "full", allowSelectBy: false });
grist.onOptions((options) => {
  const c = options && Array.isArray(options.colonnes) ? options.colonnes : [];
  S.T.colonnes = c.filter((x) => typeof x === "string" && /^[A-Za-z_][A-Za-z0-9_]{0,99}$/.test(x));
  rendu();
});
grist.onRecords((recs) => { S.records = recs || []; rendu(); });
demarrer();
