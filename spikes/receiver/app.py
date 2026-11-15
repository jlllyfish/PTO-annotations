"""Récepteur de test (phase 0) — bibliothèque standard uniquement, à déployer sur l'hôte de test.

Routes :
  GET  /health                    → "ok"
  POST /hook/<secret>/<source>    → capture une notification (DN, Grist…) ; répond toujours 200
  GET  /events/<secret>           → 200 derniers événements capturés (JSON)
  GET  /widget                    → widget Grist de test pour getAccessToken
  POST /verify                    → vérifie côté serveur un jeton d'accès Grist émis par le widget

Variables : RECEIVER_SECRET (≥ 32 caractères, obligatoire), PORT (fourni par l'hébergeur),
GRIST_ALLOWED_HOST (défaut grist.numerique.gouv.fr), GRIST_PLUGIN_API_URL.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SECRET = os.environ.get("RECEIVER_SECRET", "")
if len(SECRET) < 32:
    sys.exit("RECEIVER_SECRET doit faire au moins 32 caractères (ex. : python -c 'import secrets; print(secrets.token_urlsafe(32))')")
PORT = int(os.environ.get("PORT", "8000"))
GRIST_HOST = os.environ.get("GRIST_ALLOWED_HOST", "grist.numerique.gouv.fr")
PLUGIN_API_URL = os.environ.get("GRIST_PLUGIN_API_URL", "https://docs.getgrist.com/grist-plugin-api.js")
PLUGIN_API_ORIGIN = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(PLUGIN_API_URL))

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 1_000_000
SOURCE_RE = re.compile(r"^[a-z0-9_-]{1,30}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9._~-]{10,1024}$")
DOC_PATH_RE = re.compile(r"^(/o/[A-Za-z0-9-]+)?/api/docs/[A-Za-z0-9]{10,64}$")
DROP_HEADERS = {"authorization", "cookie", "proxy-authorization", "x-api-key"}

EVENTS: deque = deque(maxlen=200)
LOCK = threading.Lock()
VERIFY_CALLS: deque = deque(maxlen=30)  # limitation simple : 30 vérifications / minute

BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Strict-Transport-Security": "max-age=31536000",
}
API_CSP = "default-src 'none'; frame-ancestors 'none'"
# 'unsafe-eval' : exigé par grist-plugin-api.js (eval interne). Pas de 'unsafe-inline' :
# aucun script inline n'est autorisé, et le widget n'affiche les données que via textContent.
WIDGET_CSP = (
    f"default-src 'none'; script-src 'self' 'unsafe-eval' {PLUGIN_API_ORIGIN}; style-src 'self'; "
    f"connect-src 'self'; img-src 'self' data:; frame-ancestors https://{GRIST_HOST}"
)


def secret_ok(candidate: str) -> bool:
    return hmac.compare_digest(candidate.encode(), SECRET.encode())


def parse_body(raw: bytes, content_type: str) -> object:
    text = raw.decode("utf-8", errors="replace")
    if "json" in content_type:
        try:
            return json.loads(text)
        except ValueError:
            pass
    if "x-www-form-urlencoded" in content_type:
        return {k: v if len(v) > 1 else v[0] for k, v in urllib.parse.parse_qs(text).items()}
    return text[:10_000]


def verify_grist_token(token: str, base_url: str) -> dict:
    """Appelle Grist avec le jeton du widget : s'il répond 200, l'appelant a bien accès au document."""
    url = urllib.parse.urlparse(base_url)
    if url.scheme != "https" or url.hostname != GRIST_HOST or url.port or not DOC_PATH_RE.fullmatch(url.path):
        return {"ok": False, "raison": "baseUrl refusée (hôte ou chemin inattendu)"}
    if not TOKEN_RE.fullmatch(token):
        return {"ok": False, "raison": "format de jeton inattendu"}
    target = f"https://{GRIST_HOST}{url.path}/tables?auth={urllib.parse.quote(token, safe='')}"
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(urllib.request.Request(target, headers={"User-Agent": "labels-dn-grist-spike"}), timeout=10) as resp:
            body = json.loads(resp.read(MAX_BODY))
            status = resp.status
    except urllib.error.HTTPError as err:
        return {"ok": False, "status": err.code, "ms": round((time.perf_counter() - start) * 1000)}
    except (urllib.error.URLError, TimeoutError, ValueError) as err:
        return {"ok": False, "raison": type(err).__name__}
    return {
        "ok": status == 200,
        "status": status,
        "ms": round((time.perf_counter() - start) * 1000),
        "doc_id": url.path.rsplit("/", 1)[-1],
        "nb_tables": len(body.get("tables", [])),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "spike"
    sys_version = ""

    def log_message(self, fmt: str, *args) -> None:  # journal sans les secrets d'URL
        path = re.sub(r"/(hook|events)/[^/]+", r"/\1/***", self.path)
        sys.stderr.write(f"{self.log_date_time_string()} {self.command} {path} {args[1] if len(args) > 1 else ''}\n")

    def send(self, status: int, body: bytes, ctype: str, csp: str = API_CSP) -> None:
        self.send_response(status)
        for k, v in BASE_HEADERS.items():
            self.send_header(k, v)
        self.send_header("Content-Security-Policy", csp)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: int, payload: object) -> None:
        self.send(status, json.dumps(payload, ensure_ascii=False, indent=2).encode(), "application/json; charset=utf-8")

    def read_body(self) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length < 0 or length > MAX_BODY:
            return None
        return self.rfile.read(length)

    def do_GET(self) -> None:
        parts = self.path.split("?", 1)[0].strip("/").split("/")
        if parts == ["health"]:
            return self.send(200, b"ok", "text/plain")
        if len(parts) == 2 and parts[0] == "events" and secret_ok(parts[1]):
            with LOCK:
                return self.send_json(200, list(EVENTS))
        static = {"widget": ("widget.html", "text/html; charset=utf-8"),
                  "widget.js": ("widget.js", "text/javascript; charset=utf-8"),
                  "widget.css": ("widget.css", "text/css; charset=utf-8")}
        if len(parts) == 1 and parts[0] in static:
            name, ctype = static[parts[0]]
            body = (STATIC / name).read_bytes()
            if name == "widget.html":
                body = body.replace(b"__PLUGIN_API_URL__", PLUGIN_API_URL.encode())
            return self.send(200, body, ctype, WIDGET_CSP)
        self.send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        parts = self.path.split("?", 1)[0].strip("/").split("/")
        raw = self.read_body()
        if raw is None:
            return self.send(413, b"corps invalide ou trop gros", "text/plain")

        if len(parts) == 3 and parts[0] == "hook" and secret_ok(parts[1]) and SOURCE_RE.fullmatch(parts[2]):
            event = {
                "recu_utc": datetime.now(timezone.utc).isoformat(),
                "source": parts[2],
                "headers": {k: v for k, v in self.headers.items() if k.lower() not in DROP_HEADERS},
                "body": parse_body(raw, self.headers.get("Content-Type", "")),
            }
            with LOCK:
                EVENTS.append(event)
            print(json.dumps(event, ensure_ascii=False), flush=True)
            return self.send_json(200, {"ok": True})

        if parts == ["verify"]:
            now = time.time()
            with LOCK:
                while VERIFY_CALLS and now - VERIFY_CALLS[0] > 60:
                    VERIFY_CALLS.popleft()
                if len(VERIFY_CALLS) >= VERIFY_CALLS.maxlen:
                    return self.send_json(429, {"ok": False, "raison": "trop de requêtes"})
                VERIFY_CALLS.append(now)
            try:
                data = json.loads(raw)
                token, base_url = str(data["token"]), str(data["baseUrl"])
            except (ValueError, KeyError, TypeError):
                return self.send_json(400, {"ok": False, "raison": "JSON attendu : {token, baseUrl}"})
            result = verify_grist_token(token, base_url)
            print(json.dumps({"verify": {k: v for k, v in result.items()}}), flush=True)  # jamais le jeton
            return self.send_json(200 if result.get("ok") else 403, result)

        self.send(404, b"not found", "text/plain")


if __name__ == "__main__":
    print(f"Récepteur à l'écoute sur le port {PORT} (Grist autorisé : {GRIST_HOST})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
