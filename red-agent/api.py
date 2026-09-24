"""
api.py
======
API Flask du Red Team — point d'entrée unique (comme pour le Blue Team).

Contrairement au Blue Team qui surveille EN CONTINU (une boucle infinie
coûte peu, elle n'appelle le LLM que sur événement anormal), le Red Team
mène des campagnes ponctuelles : chaque exploration complète coûte
jusqu'à MAX_STEPS appels LLM. Le faire tourner en boucle infinie
viderait le budget API pour rien. Cette API expose donc un
DÉCLENCHEMENT À LA DEMANDE plutôt qu'une boucle automatique :

    GET  http://127.0.0.1:5002/api/decisions   -> les 50 dernières décisions
    GET  http://127.0.0.1:5002/api/status       -> statut (dont agent_running)
    POST http://127.0.0.1:5002/api/run          -> lance une nouvelle exploration

Tu peux toujours lancer `python agent.py` séparément si tu préfères
l'ancien mode ligne de commande -- les deux écrivent dans le même
fichier de logs, donc tout reste cohérent.
"""

import json
import os
import threading
import time

from flask import Flask, jsonify

from agent import run_agent

API_HOST = os.environ.get("RED_API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("RED_API_PORT", "5002"))
DECISIONS_LOG_PATH = os.environ.get(
    "RED_AGENT_LOG_PATH", "./logs/red_agent_decisions.log"
)

app = Flask(__name__)
_started_at = time.time()
_agent_lock = threading.Lock()
_agent_running = False


@app.after_request
def _add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


def _read_all_decisions() -> list:
    if not os.path.exists(DECISIONS_LOG_PATH):
        return []
    decisions = []
    with open(DECISIONS_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                decisions.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return decisions


def _run_agent_in_background():
    global _agent_running
    try:
        run_agent()
    except Exception as e:
        # Comme côté Blue Team : une erreur pendant l'exploration ne doit
        # jamais laisser l'API dans un état incohérent (agent_running
        # bloqué à true pour toujours).
        print(f"[api.py] Erreur pendant l'exploration (ignorée) : {e}")
    finally:
        with _agent_lock:
            _agent_running = False


@app.route("/api/decisions")
def get_decisions():
    decisions = _read_all_decisions()
    return jsonify(decisions[-50:])


@app.route("/api/status")
def get_status():
    decisions = _read_all_decisions()
    with _agent_lock:
        running = _agent_running
    return jsonify({
        "status": "running",
        "agent_running": running,
        "uptime_seconds": round(time.time() - _started_at, 1),
        "total_decisions": len(decisions),
    })


@app.route("/api/run", methods=["POST"])
def trigger_run():
    global _agent_running
    with _agent_lock:
        if _agent_running:
            return jsonify({"started": False, "reason": "Une exploration est déjà en cours."}), 409
        _agent_running = True
    thread = threading.Thread(target=_run_agent_in_background, daemon=True)
    thread.start()
    return jsonify({"started": True})


if __name__ == "__main__":
    print(f"API Red Team disponible sur http://{API_HOST}:{API_PORT}/api/decisions")
    print(f"Déclenche une exploration avec : curl -X POST http://{API_HOST}:{API_PORT}/api/run")
    app.run(host=API_HOST, port=API_PORT, debug=False, threaded=True)

