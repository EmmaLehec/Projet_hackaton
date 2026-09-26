"""
log_reader.py
=============
Lit en continu deux sources de logs différentes et les normalise en un
flux unique d'événements, triés par ordre chronologique :

  1. Les logs d'accès HTTP de MiniHub (target-env/app/logs/access.log)
     -> un événement par requête HTTP reçue par la cible.
  2. Les logs de décisions de l'agent Red Team (red-agent/logs/red_agent_decisions.log)
     -> un événement par action décidée par l'agent (pensée + outil + résultat).

Chaque lecteur retient sa position (offset en octets) pour ne renvoyer,
à chaque appel, que les NOUVELLES lignes depuis la dernière lecture
(comme un "tail -f" piloté par code plutôt que par un processus).

IMPORTANT : les offsets sont persistés sur disque (fichier JSON dans
STATE_DIR), pas seulement en mémoire. Sans ça, relancer `api.py` ou
`blue_agent.py` repart de zéro et REJOUE tout l'historique des logs à
chaque redémarrage -> avalanche d'anciennes alertes qui donne
l'impression que l'agent "n'arrête jamais".

Pour repartir d'une lecture propre (avant une démo par exemple), il
suffit de supprimer le dossier STATE_DIR (par défaut ./state/), ou
d'appeler reset_offsets().

C'est cette fonction que l'agent Blue Team appelle en boucle pour obtenir
son flux d'événements à analyser.
"""

import json
import os

import requests

# En DEPLOIEMENT (services separes, pas de disque partage) : on lit le
# journal de la cible via HTTP. Definis TARGET_ACCESS_LOG_URL pour activer
# ce mode, ex. "https://ton-target.onrender.com/internal/access-log".
# En LOCAL : laisse cette variable vide -> on relit le fichier sur disque
# comme avant (TARGET_ACCESS_LOG).
TARGET_ACCESS_LOG_URL = os.environ.get("TARGET_ACCESS_LOG_URL", "")
# Doit correspondre a ACCESS_LOG_TOKEN cote target si tu as active le token.
ACCESS_LOG_TOKEN = os.environ.get("ACCESS_LOG_TOKEN", "")

TARGET_ACCESS_LOG = os.environ.get(
    "TARGET_ACCESS_LOG", "../target-env/app/logs/access.log"
)
RED_AGENT_LOG = os.environ.get(
    "RED_AGENT_LOG", "../red-agent/logs/red_agent_decisions.log"
)

# IMPORTANT (réalisme de la démo) : un vrai défenseur n'a JAMAIS accès au
# raisonnement interne de l'attaquant, seulement à ce que son propre
# système observe. Par défaut, la détection ne lit donc QUE access.log.
# Mets BLUE_BLIND_MODE=false uniquement si tu veux volontairement montrer
# la corrélation attaquant/défenseur à des fins pédagogiques (voir
# attacker_trace_viewer.py pour une vue séparée, hors pipeline d'alerte).
BLUE_BLIND_MODE = os.environ.get("BLUE_BLIND_MODE", "true").lower() == "true"

STATE_DIR = os.environ.get("BLUE_STATE_DIR", "./state")
OFFSETS_FILE = os.path.join(STATE_DIR, "log_offsets.json")


def _load_offsets() -> dict:
    if os.path.exists(OFFSETS_FILE):
        try:
            with open(OFFSETS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"access": 0, "red_agent": 0}


def _save_offsets(offsets: dict):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(OFFSETS_FILE, "w", encoding="utf-8") as f:
        json.dump(offsets, f)


_offsets = _load_offsets()


def _read_new_lines(path, offset_key):
    """Lit les nouvelles lignes d'un fichier depuis la dernière position
    connue (persistée sur disque). Tolère un fichier qui n'existe pas
    encore (retourne [])."""
    if not os.path.exists(path):
        return []
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        f.seek(_offsets[offset_key])
        for line in f:
            line = line.strip()
            if line:
                lines.append(line)
        _offsets[offset_key] = f.tell()
    return lines


def _read_new_lines_http(url, offset_key):
    """Comme _read_new_lines, mais lit le journal via HTTP (deploiement).
    On telecharge le contenu courant, puis on ne garde que ce qui suit
    l'offset (en octets) deja traite. Tolere le service endormi / une
    erreur reseau (retourne []) et une remise a zero du journal cote
    cible (ex. redemarrage du service -> fichier plus court)."""
    params = {"token": ACCESS_LOG_TOKEN} if ACCESS_LOG_TOKEN else None
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
    except requests.RequestException:
        return []

    text = resp.text
    start = _offsets.get(offset_key, 0)
    # Si le journal distant est plus court qu'avant, il a ete remis a zero
    # (redemarrage de la cible) -> on repart du debut.
    if start > len(text):
        start = 0

    new_part = text[start:]
    # On ne consomme que jusqu'au dernier saut de ligne complet, pour ne
    # pas couper une ligne JSON en deux entre deux appels.
    cut = new_part.rfind("\n")
    if cut == -1:
        return []
    consumed = new_part[: cut + 1]
    _offsets[offset_key] = start + len(consumed)

    return [ln.strip() for ln in consumed.splitlines() if ln.strip()]


def poll_events():
    """Retourne la liste des nouveaux événements normalisés (triés par
    timestamp) depuis les deux sources de logs, depuis le dernier appel."""
    events = []

    # Source access.log : par HTTP en deploiement, sinon par fichier (local).
    if TARGET_ACCESS_LOG_URL:
        access_lines = _read_new_lines_http(TARGET_ACCESS_LOG_URL, "access")
    else:
        access_lines = _read_new_lines(TARGET_ACCESS_LOG, "access")

    for line in access_lines:
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append({
            "source": "target_access",
            "timestamp": raw.get("timestamp"),
            "summary": f"{raw.get('method')} {raw.get('path')} -> {raw.get('status_code')} (user={raw.get('user')})",
            "raw": raw,
        })

    for line in _read_new_lines(RED_AGENT_LOG, "red_agent"):
        if BLUE_BLIND_MODE:
            # En mode réaliste (par défaut), on avance quand même
            # l'offset pour ne pas accumuler ce fichier indéfiniment,
            # mais on n'injecte PAS ces événements dans la détection :
            # un vrai défenseur ne les verrait jamais.
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append({
            "source": "red_agent_decision",
            "timestamp": raw.get("timestamp"),
            "summary": f"step {raw.get('step')}: {raw.get('tool')}({raw.get('args')}) -- {raw.get('thought')}",
            "raw": raw,
        })

    events.sort(key=lambda e: e["timestamp"] or "")

    if events:
        _save_offsets(_offsets)

    return events


def reset_offsets():
    """Utile pour les tests, ou pour repartir d'une lecture propre avant
    une démo : repart de zéro sur les deux fichiers ET efface le fichier
    d'état sur disque."""
    _offsets["access"] = 0
    _offsets["red_agent"] = 0
    if os.path.exists(OFFSETS_FILE):
        os.remove(OFFSETS_FILE)

