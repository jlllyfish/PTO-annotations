"use strict";
// Tout l'affichage passe par textContent : aucune donnée n'est interprétée comme du HTML.
const out = document.getElementById("out");
const lines = [];
const log = (...msgs) => { lines.push(...msgs); out.textContent = lines.join("\n"); };

const withTimeout = (promise, ms, label) => Promise.race([
  promise,
  new Promise((_, reject) => setTimeout(() => reject(new Error(`${label} : pas de réponse après ${ms / 1000} s`)), ms)),
]);

if (typeof grist === "undefined") {
  log("❌ L'API Grist (grist-plugin-api.js) n'est pas chargée. Voir la console (F12).");
} else {
  grist.ready({ requiredAccess: "read table" });
  log("Widget prêt. Accès demandé : « read table ».");
  grist.onOptions((_options, interaction) => {
    if (interaction && interaction.accessLevel) log(`Niveau d'accès accordé par Grist : ${interaction.accessLevel}`);
  });
}

document.getElementById("go").addEventListener("click", async () => {
  const readOnly = document.getElementById("readonly").checked;
  log("", `--- Essai (readOnly = ${readOnly}) ---`, "Demande du jeton à Grist…");
  try {
    const t0 = performance.now();
    const info = await withTimeout(grist.docApi.getAccessToken({ readOnly }), 10000, "getAccessToken");
    log(`Jeton obtenu en ${Math.round(performance.now() - t0)} ms`);
    log(`baseUrl : ${info.baseUrl}`);
    log(`ttl : ${info.ttl} ms (${Math.round(info.ttl / 60000)} min)`);
    log("Vérification par le serveur…");
    const res = await withTimeout(fetch("/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: info.token, baseUrl: info.baseUrl }),
    }), 15000, "vérification serveur");
    log(`Vérification serveur (HTTP ${res.status}) :`, JSON.stringify(await res.json(), null, 2));
  } catch (err) {
    log(`❌ ${err && err.message ? err.message : String(err)}`);
  }
});
