"use strict";
/*
 * Widget Grist « Labels DN ».
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

function bouton(texte, onclick, { type = "primary", disabled = false, icone = null } = {}) {
  const cls = ["fr-btn", type === "secondary" ? "fr-btn--secondary" : type === "tertiary" ? "fr-btn--tertiary" : ""];
  if (icone) cls.push(icone, "fr-btn--icon-left");
  return h("button", { type: "button", class: cls.join(" "), disabled: disabled || S.occupe, onclick }, texte);
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
const classeCouleur = (c) => (COULEUR_RE.test(c || "") ? `fr-tag--${c.replaceAll("_", "-")}` : "");

// ------------------------------------------------------------------ état et API

const S = {
  contexte: null,
  demarche: null,       // numéro
  catalogue: [],        // [{id, nom, couleur}]
  record: null,         // ligne sélectionnée dans Grist
  records: [],          // lignes transmises au widget
  onglet: "dossier",
  jeton: null,
  expiration: 0,
  occupe: false,
  message: null,        // {type, titre, texte}
  synchro: null,        // {tache, derniere}
  apercu: null,
  masse: { action: "ajouter", label: "" },
  journal: [],
  filtreJournal: "toutes",
  modal: null,
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
  const n = parseInt(String(rec && rec.dossier_number || "").trim(), 10);
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
  if (!S.masse.label && S.catalogue[0]) S.masse.label = S.catalogue[0].id;
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
      texte: `${b.dossiers_lus} dossier(s) lu(s), ${b.dossiers_maj} mis à jour dans Grist (${b.duree_s} s).` };
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

async function operer(actionLabel, labelId, numeros, envoyer = true) {
  const b = await api("POST", `${base()}/operations`, { action: actionLabel, label_id: labelId, numeros, envoyer });
  S.message = messageBilan(b);
  await chargerJournal();
}

// ------------------------------------------------------------------ rendu

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
          String(S.demarche), (v) => action(async () => { S.demarche = Number(v); S.apercu = null; await chargerDemarche(); }),
          { cacher: true })
        : h("span", { class: "lbl-mention", text: demarches[0] ? `${demarches[0].numero} — ${demarches[0].nom}` : "" }),
      etat));
}

const ONGLETS = [["dossier", "Dossier"], ["masse", "En masse"], ["file", "File et journal"], ["regles", "Règles"], ["synchro", "Synchro"]];

function onglets() {
  const attente = S.journal.filter((l) => l.statut === "en_attente").length;
  return h("nav", { class: "lbl-tabs", role: "tablist", "aria-label": "Sections du widget" },
    ONGLETS.map(([id, nom]) => h("button", {
      type: "button", class: "lbl-tab", role: "tab", "aria-selected": S.onglet === id ? "true" : "false",
      onclick: () => { S.onglet = id; S.message = null; if (id === "file") action(chargerJournal); else rendu(); },
    }, nom, id === "file" && attente ? h("span", { class: "lbl-compteur", text: String(attente) }) : null)));
}

function vueDossier() {
  const rec = S.record;
  const num = numeroDe(rec);
  if (!num) {
    return alerte("info", "Aucun dossier sélectionné",
      `Sélectionnez une ligne dans la table Demarche_${S.demarche}_dossiers liée à ce widget.`);
  }
  const presents = labelsDuRecord(rec);
  const idsPresents = new Set(presents.map((l) => l.id));
  const ajoutables = S.catalogue.filter((l) => !idsPresents.has(l.id));
  const etat = ETATS[rec.state] || [rec.state || "État inconnu", ""];
  const lienDN = `https://demarche.numerique.gouv.fr/procedures/${S.demarche}/dossiers/${num}`;
  let choix = ajoutables[0] ? ajoutables[0].id : "";

  const historique = S.journal.filter((l) => String(l.dossier_number).trim() === String(num)).slice(0, 8);

  return [
    h("section", { class: "lbl-carte" },
      h("div", { class: "lbl-entre" },
        h("div", { class: "lbl-pile" },
          h("p", { class: "lbl-mention", text: "Dossier sélectionné dans Grist" }),
          h("h2", { class: "fr-h4 fr-mb-0", text: `Dossier n° ${num}` })),
        h("div", { class: "lbl-pile lbl-pile--droite" },
          badge(etat[0], etat[1]),
          h("a", { class: "fr-link fr-link--sm", href: lienDN, target: "_blank", rel: "noopener noreferrer",
            title: "Ouvrir dans DN (nouvelle fenêtre)", text: "Ouvrir dans DN" }))),
      h("h3", { class: "fr-h6 fr-mb-0", text: "Labels" }),
      presents.length
        ? h("div", { class: "lbl-tags" }, presents.map((l) => h("button", {
          type: "button", class: `fr-tag fr-tag--dismiss ${classeCouleur(l.color)}`,
          "aria-label": `Retirer le label ${l.name}`, disabled: S.occupe,
          onclick: () => action(() => operer("retirer", l.id, [num])),
        }, l.name)))
        : h("p", { class: "lbl-mention", text: "Aucun label sur ce dossier." }),
      ajoutables.length
        ? h("div", { class: "lbl-ligne" },
          h("div", { class: "lbl-champ" },
            selectChamp("Ajouter un label", ajoutables.map((l) => ({ value: l.id, label: l.nom })), choix, (v) => { choix = v; })),
          bouton("Ajouter", () => action(() => operer("ajouter", choix, [num]))))
        : null,
      h("p", { class: "lbl-mention", text: "Chaque ajout ou retrait est envoyé immédiatement à DN, puis la ligne Grist est mise à jour." }),
      h("div", { class: "lbl-actions" },
        bouton("Vérifier ce dossier dans DN", () => action(() => lancerSynchro("ciblee", [num])), { type: "secondary" }))),
    h("section", { class: "lbl-carte" },
      h("h3", { class: "fr-h6 fr-mb-0", text: "Historique de ce dossier" }),
      historique.length
        ? h("ul", { class: "lbl-historique" }, historique.map((l) => h("li", {},
          h("span", { class: "lbl-mention", text: dateEpoch(l.traite_le || l.cree_le) }),
          h("span", {}, `${l.action === "ajouter" ? "Ajout" : "Retrait"} « ${l.label} » · `,
            h("span", { class: "lbl-mention", text: l.source })),
          badge(...(STATUTS[l.statut] || [l.statut, ""])))))
        : h("p", { class: "lbl-mention", text: "Aucune opération enregistrée par cet outil." })),
  ];
}

function vueMasse() {
  const numeros = numerosTransmis();
  const trop = numeros.length > 500;
  const a = S.apercu;
  const lab = S.catalogue.find((l) => l.id === S.masse.label);
  const radio = (val, texte) => {
    const id = nouvelId("act");
    return h("div", { class: "fr-fieldset__element fr-fieldset__element--inline" },
      h("div", { class: "fr-radio-group" },
        h("input", { type: "radio", id, name: "lbl-action", value: val, checked: S.masse.action === val,
          onchange: () => { S.masse.action = val; S.apercu = null; rendu(); } }),
        h("label", { class: "fr-label", for: id, text: texte })));
  };
  return h("section", { class: "lbl-carte" },
    h("div", { class: "lbl-pile" },
      h("p", { class: "lbl-mention", text: "Périmètre" }),
      h("h2", { class: "fr-h4 fr-mb-0", text: `${numeros.length} dossier(s) transmis au widget` }),
      h("p", { class: "lbl-mention", text: "Les filtres de la vue du widget (ou sa liaison à une autre vue) définissent le périmètre." })),
    trop ? alerte("warning", "Plus de 500 dossiers", "Filtrez la vue pour agir sur 500 dossiers au maximum à la fois.") : null,
    h("fieldset", { class: "fr-fieldset" },
      h("legend", { class: "fr-fieldset__legend fr-text--regular", text: "Action" }),
      radio("ajouter", "Ajouter"), radio("retirer", "Retirer")),
    h("div", { class: "lbl-champ" },
      selectChamp("Label", S.catalogue.map((l) => ({ value: l.id, label: l.nom })), S.masse.label,
        (v) => { S.masse.label = v; S.apercu = null; rendu(); })),
    h("div", { class: "lbl-actions" },
      bouton("Calculer l'aperçu", () => action(async () => {
        S.apercu = await api("POST", `${base()}/operations/apercu`,
          { action: S.masse.action, label_id: S.masse.label, numeros });
      }), { type: "secondary", disabled: !numeros.length || trop || !S.masse.label })),
    a ? h("div", { class: "lbl-pile" },
      h("h3", { class: "fr-h6 fr-mb-0", text: "Aperçu (état actuel dans DN)" }),
      h("div", { class: "lbl-stats" },
        h("div", { class: "lbl-stat lbl-stat--fort" }, h("strong", { text: String(a.a_faire) }),
          h("span", { text: a.action === "ajouter" ? "recevront le label" : "perdront le label" })),
        h("div", { class: "lbl-stat" }, h("strong", { text: String(a.deja) }), h("span", { text: "déjà dans l'état voulu" })),
        h("div", { class: "lbl-stat" }, h("strong", { text: String(a.introuvables) }), h("span", { text: "introuvables dans la démarche" }))),
      h("div", { class: "lbl-actions" },
        bouton(`${a.action === "ajouter" ? "Ajouter à" : "Retirer de"} ${a.a_faire} dossier(s)…`,
          () => { S.modal = { a, numeros }; rendu(); }, { disabled: !a.a_faire }),
        bouton("Mettre en file sans envoyer", () => action(async () => {
          await operer(a.action, a.label.id, a.numeros_a_faire, false);
          S.apercu = null;
        }), { type: "secondary", disabled: !a.a_faire }))) : null,
    lab && !a ? h("p", { class: "lbl-mention", text: "Calculez l'aperçu pour voir les dossiers concernés avant d'envoyer." }) : null);
}

function modale() {
  if (!S.modal) return null;
  const { a, numeros } = S.modal;
  const id = nouvelId("chk");
  let coche = false;
  const envoyer = bouton("Envoyer à DN", () => {
    S.modal = null;
    action(async () => { await operer(a.action, a.label.id, numeros); S.apercu = null; });
  }, { disabled: true });
  return h("div", { class: "lbl-modal" },
    h("div", { class: "lbl-modal__boite", role: "dialog", "aria-modal": "true", "aria-labelledby": "lbl-modal-titre" },
      h("h2", { class: "fr-h5", id: "lbl-modal-titre", text: "Confirmer l'envoi vers DN" }),
      h("p", {}, `Le label « ${a.label.nom} » sera ${a.action === "ajouter" ? "ajouté à" : "retiré de"} `,
        h("strong", { text: `${a.a_faire} dossier(s)` }), ` de la démarche ${S.demarche}.`),
      h("p", { class: "lbl-mention", text: "Les instructeurs le verront immédiatement dans DN. L'opération est journalisée." }),
      h("div", { class: "fr-checkbox-group" },
        h("input", { type: "checkbox", id, onchange: (e) => { coche = e.target.checked; envoyer.disabled = !coche; } }),
        h("label", { class: "fr-label", for: id, text: "J'ai vérifié le périmètre" })),
      h("div", { class: "lbl-actions lbl-actions--droite" },
        bouton("Annuler", () => { S.modal = null; rendu(); }, { type: "secondary" }), envoyer)));
}

function vueFile() {
  const filtres = [["toutes", "Toutes"], ["en_attente", "En attente"], ["applique", "Appliquées"], ["erreur", "Erreurs"]];
  const compte = (f) => (f === "toutes" ? S.journal.length : S.journal.filter((l) => l.statut === f).length);
  const lignes = S.journal.filter((l) => S.filtreJournal === "toutes" || l.statut === S.filtreJournal).slice(0, 200);
  const attente = compte("en_attente");
  return h("section", { class: "lbl-carte" },
    h("div", { class: "lbl-actions" }, filtres.map(([f, nom]) => h("button", {
      type: "button", class: `fr-btn fr-btn--sm ${S.filtreJournal === f ? "" : "fr-btn--secondary"}`,
      "aria-pressed": S.filtreJournal === f ? "true" : "false",
      onclick: () => { S.filtreJournal = f; rendu(); },
    }, `${nom} (${compte(f)})`))),
    lignes.length
      ? h("div", { class: "lbl-table" }, h("table", {},
        h("caption", { class: "lbl-cache", text: "Opérations sur les labels" }),
        h("thead", {}, h("tr", {}, ["Dossier", "Action", "Label", "Source", "Statut", "Date"].map((t) => h("th", { scope: "col", text: t })))),
        h("tbody", {}, lignes.map((l) => h("tr", {},
          h("td", { text: String(l.dossier_number) }),
          h("td", { text: l.action === "ajouter" ? "Ajout" : "Retrait" }),
          h("td", { text: l.label }),
          h("td", { text: l.source }),
          h("td", {}, badge(...(STATUTS[l.statut] || [l.statut, ""])), l.message ? h("div", { class: "lbl-mention", text: l.message }) : null),
          h("td", { text: dateEpoch(l.traite_le || l.cree_le) }))))))
      : h("p", { class: "lbl-mention", text: "Aucune opération." }),
    h("div", { class: "lbl-actions" },
      bouton(`Envoyer les ${attente} opération(s) en attente`, () => action(async () => {
        const r = await api("POST", `${base()}/operations/file/envoyer`);
        const t = r.lots.reduce((acc, b) => ({ a: acc.a + b.appliques, d: acc.d + b.deja, e: acc.e + b.erreurs + b.introuvables }), { a: 0, d: 0, e: 0 });
        S.message = { type: t.e ? "warning" : "success", titre: "File envoyée",
          texte: `${t.a} appliquée(s) · ${t.d} déjà dans l'état voulu · ${t.e} erreur(s)` };
        await chargerJournal();
      }), { disabled: !attente }),
      bouton("Actualiser", () => action(chargerJournal), { type: "tertiary" })));
}

function vueSynchro() {
  const der = (S.synchro && S.synchro.derniere) || {};
  const tache = S.synchro && S.synchro.tache;
  const enCours = tache && tache.statut === "en_cours";
  const numeros = numerosTransmis();
  const kv = (k, v) => h("div", { class: "lbl-kv" }, h("dt", { text: k }), h("dd", { text: v }));
  return [
    h("section", { class: "lbl-carte" },
      h("h3", { class: "fr-h6 fr-mb-0", text: "Synchronisation DN → Grist" }),
      h("dl", { class: "fr-mb-0" },
        kv("Dernière synchro", der.fin ? `${ilYa(der.fin)} (${der.mode}, ${der.statut})` : "jamais"),
        kv("Résultat", der.statut === "erreur" ? der.message : der.fin ? `${der.dossiers_lus} lu(s), ${der.dossiers_maj} mis à jour` : "—"),
        kv("Dernière relecture complète", der.derniere_complete ? dateEpoch(der.derniere_complete) : "jamais")),
      h("div", { class: "lbl-actions" },
        bouton("Synchroniser maintenant", () => action(() => lancerSynchro("incrementale"))),
        bouton(`Synchroniser les ${numeros.length} dossier(s) transmis`, () => action(() => lancerSynchro("ciblee", numeros)),
          { type: "secondary", disabled: !numeros.length || numeros.length > 500 }),
        bouton("Relecture complète", () => action(() => lancerSynchro("complete")), { type: "tertiary" })),
      enCours ? h("div", { class: "lbl-pile" },
        h("p", { class: "lbl-mention", text: `${tache.etape} — ${tache.dossiers_lus} dossier(s) lu(s)` }),
        h("div", { class: "lbl-progression", role: "progressbar", "aria-label": "Synchronisation en cours" },
          h("div", { class: "lbl-progression__barre" }))) : null),
    h("section", { class: "lbl-carte" },
      h("h3", { class: "fr-h6 fr-mb-0", text: `Catalogue des labels — démarche ${S.demarche}` }),
      h("div", { class: "lbl-tags" }, S.catalogue.map((l) => h("span", { class: `fr-tag ${classeCouleur(l.couleur)}`, text: l.nom }))),
      h("p", { class: "lbl-mention", text: "Les labels se créent et se renomment dans l'administration de la démarche DN ; le catalogue est relu à chaque synchro." })),
  ];
}

function vueRegles() {
  return alerte("info", "Bientôt disponible", "Les règles automatiques ET / OU arrivent dans la prochaine version (phase 5).");
}

function rendu() {
  const app = document.getElementById("app");
  if (!S.contexte) return;
  compteurIds = 0; // identifiants stables d'un rendu à l'autre (restauration du focus)
  const vues = { dossier: vueDossier, masse: vueMasse, file: vueFile, regles: vueRegles, synchro: vueSynchro };
  const focus = document.activeElement && document.activeElement.id;
  app.replaceChildren(
    enTete(),
    onglets(),
    h("main", { class: "lbl-main" },
      S.message ? alerte(S.message.type, S.message.titre, S.message.texte) : null,
      S.occupe ? h("div", { class: "lbl-progression", role: "progressbar", "aria-label": "Traitement en cours" },
        h("div", { class: "lbl-progression__barre" })) : null,
      vues[S.onglet]()),
    modale());
  if (focus) { const el = document.getElementById(focus); if (el) el.focus(); }
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

grist.ready({ requiredAccess: "full", allowSelectBy: false });
grist.onRecord((rec) => { S.record = rec; if (S.onglet === "dossier") rendu(); });
grist.onRecords((recs) => { S.records = recs || []; if (S.onglet !== "dossier") rendu(); });
demarrer();
