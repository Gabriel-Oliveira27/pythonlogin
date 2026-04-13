"""
app.py — Proxy Worker (Python/Flask)
=====================================
Replica exatamente o comportamento do Cloudflare Worker:
- Recebe POST do front
- Repassa para o Google Apps Script (com redirect: follow)
- Devolve a resposta JSON
- Trata CORS para as origens permitidas
- Usado como 5º fallback quando os 4 Workers Cloudflare falham
"""

import os
import json
import requests
from flask import Flask, request, Response
from flask_cors import CORS

# ─────────────────────────────────────────────
# CONFIG — igual ao Worker Cloudflare
# ─────────────────────────────────────────────
GOOGLE_APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbwXAIcu3bVQe-aQOhQFMxK_9gOi2UC_CG6b-6zDw1Jw9biUyzJ5Mejn99cY4XFpRWDs/exec"

ALLOWED_ORIGINS = [
    "https://gabriel-oliveira27.github.io/AtivosZ",
    "https://gabriel-oliveira27.github.io/FuncZ",
    "http://localhost:5500",
]

app = Flask(__name__)

# ─────────────────────────────────────────────
# CORS helper — mesma lógica do Worker
# ─────────────────────────────────────────────
def get_allow_origin(origin):
    return origin if origin in ALLOWED_ORIGINS else "*"


def cors_headers(origin):
    return {
        "Access-Control-Allow-Origin":  get_allow_origin(origin),
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
    }


# ─────────────────────────────────────────────
# PREFLIGHT — OPTIONS
# ─────────────────────────────────────────────
@app.route("/", methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def options(path=""):
    origin = request.headers.get("Origin", "")
    return Response(
        status=204,
        headers=cors_headers(origin),
    )


# ─────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    origin = request.headers.get("Origin", "")
    body   = json.dumps({"ok": True, "worker": "python-render", "version": "1.0.0"})
    return Response(body, status=200, mimetype="application/json",
                    headers=cors_headers(origin))


# ─────────────────────────────────────────────
# PROXY PRINCIPAL — replica o handleRequest
# ─────────────────────────────────────────────
@app.route("/", methods=["POST"])
@app.route("/<path:path>", methods=["POST"])
def proxy(path=""):
    origin = request.headers.get("Origin", "")

    # Método não permitido (GET sem ser health)
    # (POST já está sendo tratado aqui)

    try:
        # Lê o body cru — igual ao `request.text()` do Worker
        raw_body = request.get_data(as_text=True)

        # Repassa para o Apps Script com redirect: follow
        # (requests segue redirects por padrão — equivalente ao redirect:"follow")
        resp = requests.post(
            GOOGLE_APPS_SCRIPT_URL,
            data=raw_body,
            headers={
                "Content-Type": "application/json",
                "Accept":       "application/json",
            },
            allow_redirects=True,   # ← equivalente ao redirect: "follow"
            timeout=30,
        )

        raw_text = resp.text

        # Tenta fazer parse do JSON — mesma lógica de fallback do Worker
        try:
            json_data = resp.json()
        except Exception:
            print(f"[WARN] Resposta não-JSON do Apps Script: {raw_text[:500]}")
            json_data = {
                "ok":     False,
                "error":  "Resposta inválida do servidor remoto",
                "detail": raw_text[:200],
            }

        status_code = 200 if resp.ok else resp.status_code
        body        = json.dumps(json_data)

        headers = {
            "Content-Type":                "application/json",
            "Access-Control-Allow-Origin": get_allow_origin(origin),
        }

        return Response(body, status=status_code, headers=headers)

    except requests.exceptions.Timeout:
        body = json.dumps({"ok": False, "error": "Timeout ao conectar com o servidor remoto"})
        return Response(body, status=504, mimetype="application/json",
                        headers={"Access-Control-Allow-Origin": get_allow_origin(origin)})

    except Exception as err:
        print(f"[ERROR] {err}")
        body = json.dumps({"ok": False, "error": str(err)})
        return Response(body, status=500, mimetype="application/json",
                        headers={"Access-Control-Allow-Origin": "*"})


# ─────────────────────────────────────────────
# GET — método não permitido (igual ao Worker)
# ─────────────────────────────────────────────
@app.route("/", methods=["GET"])
@app.route("/<path:path>", methods=["GET"])
def not_allowed(path=""):
    if path == "health":
        return health()
    origin = request.headers.get("Origin", "")
    body   = json.dumps({"ok": False, "error": "Método não permitido"})
    return Response(body, status=405, mimetype="application/json",
                    headers={"Access-Control-Allow-Origin": get_allow_origin(origin)})


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[proxy-worker] rodando na porta {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
