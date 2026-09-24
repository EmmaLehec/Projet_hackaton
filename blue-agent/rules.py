"""
rules.py
========
Detection par regles (rapides, gratuites, pas d'appel LLM). Chaque regle
regarde un evenement (et un peu d'etat accumule) et renvoie None si rien
d'anormal, ou un dict decrivant l'alerte sinon.

Philosophie (POC++ / defense en profondeur) :
  - Ces regles sont un PREMIER FILTRE bon marche. Seuls les evenements
    juges suspects sont ensuite envoyes au LLM (classifier.py) pour une
    analyse fine -> on economise le budget API.
  - Chaque regle vise une CLASSE de comportement (acces interne, force
    brute, upload dangereux, reconnaissance, chaine d'exploitation), pas
    un scenario scripte unique. L'objectif est d'attraper l'attaquant
    quel que soit l'ORDRE de ses actions, sans avoir a mettre en scene
    le Red Team pour le faire coller a la detection.
  - Limite assumee : une detection a base de regles ne voit que ce
    qu'on lui a appris a voir. Une v2 ajouterait de la detection
    d'anomalies (baseline statistique) pour l'inconnu. On le documente
    plutot que de le cacher.
"""

from collections import defaultdict

# ---------------------------------------------------------------------
# Etat accumule entre les appels (compteurs / historique court)
# ---------------------------------------------------------------------
_failed_logins = defaultdict(int)      # echecs de login consecutifs par IP
_recent_actions = []                   # les N derniers evenements (sequences)
_bruteforce_alerted = set()            # IP deja alertees en force brute (anti-spam)
_enum_alerted = set()                  # IP deja alertees en reconnaissance
MAX_RECENT = 30

# Extensions clairement dangereuses pour un hub de modeles ML. On NE
# flague PAS .bin / .safetensors (formats de modeles legitimes) pour
# eviter les faux positifs : c'est le compromis realiste du monde reel.
# .pkl / .pickle sont inclus car c'est le vecteur d'execution de code
# arbitraire le plus connu sur les hubs de modeles (deserialisation).
DANGEROUS_UPLOAD_EXTENSIONS = (
    ".pkl", ".pickle", ".sh", ".bash", ".exe", ".bat", ".cmd",
    ".php", ".py", ".js", ".pl", ".rb", ".jar", ".dll", ".so",
)


def _is_sensitive_path(path: str) -> bool:
    """Chemins consideres 'sensibles' pour la detection de reconnaissance."""
    if not path:
        return False
    return (
        path.startswith("/admin")
        or path.startswith("/internal")
        or path in ("/login", "/upload")
    )


def _remember(event):
    _recent_actions.append(event)
    if len(_recent_actions) > MAX_RECENT:
        _recent_actions.pop(0)


# ---------------------------------------------------------------------
# Regle 1 : acces a un endpoint interne (/internal/*)
# ---------------------------------------------------------------------
def check_internal_endpoint_access(event):
    """Tout acces a un endpoint /internal/* est suspect, AUTHENTIFIE OU
    NON. Justification : ces endpoints sont censes n'etre appeles que par
    des services internes ; aucune session utilisateur (navigateur) ne
    devrait jamais les atteindre. Miroir direct du vol d'identifiants via
    le service de metadonnees cloud dans l'incident reel.

    C'est la generalisation clef : avant, la regle ne se declenchait que
    si l'attaquant n'etait PAS connecte. Un attaquant qui se connecte
    d'abord passait donc au travers. Desormais on l'attrape quel que soit
    son etat d'authentification -> plus besoin de "mettre en scene" le
    Red Team pour que la detection fonctionne.
    """
    if event["source"] != "target_access":
        return None
    raw = event["raw"]
    path = raw.get("path", "")
    if path.startswith("/internal"):
        user = raw.get("user")
        etat = f"session {user}" if user else "SANS session authentifiee"
        return {
            "rule": "internal_endpoint_access",
            "severity": "high",
            "reason": (
                f"Acces a l'endpoint interne {path} ({etat}). "
                "Aucun usage utilisateur legitime ne cible cet endpoint."
            ),
            "event": event,
        }
    return None


# ---------------------------------------------------------------------
# Regle 2 : force brute sur /login
# ---------------------------------------------------------------------
def check_login_bruteforce(event):
    """Deux signaux de force brute :
      (a) plusieurs echecs suivis d'un succes (compromission probable),
      (b) un seuil d'echecs consecutifs atteint, meme sans succes
          (tentative de force brute en cours).
    Flask renvoie 200 sur un echec de login (reaffiche le formulaire) et
    301/302 sur un succes (redirection).
    """
    if event["source"] != "target_access":
        return None
    raw = event["raw"]
    if raw.get("path") != "/login" or raw.get("method") != "POST":
        return None

    ip = raw.get("ip", "unknown")

    if raw.get("status_code") == 200:
        _failed_logins[ip] += 1
        # (b) seuil d'echecs atteint -> on alerte une seule fois par IP
        if _failed_logins[ip] >= 3 and ip not in _bruteforce_alerted:
            _bruteforce_alerted.add(ip)
            return {
                "rule": "login_bruteforce_attempts",
                "severity": "medium",
                "reason": f"{_failed_logins[ip]} echecs de connexion consecutifs depuis {ip}.",
                "event": event,
            }
    elif raw.get("status_code") in (301, 302):
        attempts = _failed_logins.get(ip, 0)
        _failed_logins[ip] = 0
        _bruteforce_alerted.discard(ip)
        # (a) succes precede d'au moins un echec -> pattern classique
        if attempts >= 1:
            return {
                "rule": "login_bruteforce_pattern",
                "severity": "medium",
                "reason": f"Connexion reussie apres {attempts} tentative(s) echouee(s) depuis {ip}.",
                "event": event,
            }
    return None


# ---------------------------------------------------------------------
# Regle 3 : upload de fichier dangereux (VULN-01)
# ---------------------------------------------------------------------
def check_suspicious_upload(event):
    """Detecte un upload dont le NOM DE FICHIER trahit une intention
    malveillante : extension executable/serialisee dangereuse, ou tentative
    de path traversal ('..', chemin absolu). C'est le vecteur central de
    l'incident Hugging Face : un fichier de modele malveillant depose sur
    le hub. Necessite que la cible journalise 'upload_filename'.
    """
    if event["source"] != "target_access":
        return None
    raw = event["raw"]
    if raw.get("path") != "/upload" or raw.get("method") != "POST":
        return None

    filename = raw.get("upload_filename") or ""
    if not filename:
        return None

    lower = filename.lower()
    traversal = (".." in filename) or filename.startswith("/") or "\\" in filename
    dangerous_ext = lower.endswith(DANGEROUS_UPLOAD_EXTENSIONS)

    if traversal or dangerous_ext:
        motif = "path traversal" if traversal else "extension dangereuse"
        return {
            "rule": "suspicious_file_upload",
            "severity": "high",
            "reason": f"Upload suspect '{filename}' ({motif}) : possible modele/fichier malveillant.",
            "event": event,
        }
    return None


# ---------------------------------------------------------------------
# Regle 4 : reconnaissance / enumeration d'endpoints sensibles
# ---------------------------------------------------------------------
def check_sensitive_path_enumeration(event):
    """Une meme IP qui touche plusieurs endpoints SENSIBLES distincts
    (/admin*, /internal*, /login, /upload) dans une courte fenetre = motif
    de reconnaissance (scan), typique d'un agent qui explore la surface
    d'attaque. On alerte une seule fois par IP pour ne pas spammer.
    """
    if event["source"] != "target_access":
        return None
    raw = event["raw"]
    ip = raw.get("ip", "unknown")
    if ip in _enum_alerted:
        return None

    sensitive_paths = {
        e["raw"].get("path")
        for e in _recent_actions
        if e["source"] == "target_access"
        and e["raw"].get("ip") == ip
        and _is_sensitive_path(e["raw"].get("path", ""))
    }
    if len(sensitive_paths) >= 3:
        _enum_alerted.add(ip)
        listing = ", ".join(sorted(p for p in sensitive_paths if p))
        return {
            "rule": "sensitive_path_enumeration",
            "severity": "medium",
            "reason": (
                f"L'IP {ip} a sonde {len(sensitive_paths)} endpoints sensibles distincts "
                f"({listing}) : reconnaissance probable."
            ),
            "event": event,
        }
    return None


# ---------------------------------------------------------------------
# Regle 5 : chaine d'exploitation upload -> zone admin
# ---------------------------------------------------------------------
def check_upload_then_admin_access(event):
    """Sequence suspecte : un upload suivi peu apres d'un acces a la zone
    admin. Signe d'une chaine d'exploitation (deposer une charge, puis
    pivoter vers l'administration)."""
    if event["source"] != "target_access":
        return None
    raw = event["raw"]
    if raw.get("path") == "/admin/users" and raw.get("status_code") == 200:
        had_recent_upload = any(
            e["source"] == "target_access" and e["raw"].get("path") == "/upload"
            for e in _recent_actions[-6:]
        )
        if had_recent_upload:
            return {
                "rule": "upload_then_admin_access",
                "severity": "medium",
                "reason": "Acces a la zone admin peu apres un upload : chaine d'exploitation possible.",
                "event": event,
            }
    return None


# ---------------------------------------------------------------------
# Regle 6 : usage d'outil sensible par l'agent Red (correlation)
# ---------------------------------------------------------------------
def check_red_agent_tool_use(event):
    """Uniquement actif hors BLUE_BLIND_MODE (vue pedagogique de
    correlation attaquant/defenseur). En mode aveugle par defaut, ces
    evenements ne sont jamais injectes, donc cette regle ne fire pas."""
    if event["source"] != "red_agent_decision":
        return None
    raw = event["raw"]
    sensitive_tools = {"try_login", "read_internal_metadata", "upload_file"}
    if raw.get("tool") in sensitive_tools:
        return {
            "rule": "red_agent_sensitive_tool_use",
            "severity": "low",
            "reason": f"L'agent Red Team a utilise l'outil sensible '{raw.get('tool')}'.",
            "event": event,
        }
    return None


ALL_RULES = [
    check_internal_endpoint_access,
    check_login_bruteforce,
    check_suspicious_upload,
    check_sensitive_path_enumeration,
    check_upload_then_admin_access,
    check_red_agent_tool_use,
]


def evaluate(event):
    """Fait passer un evenement par toutes les regles, memorise
    l'evenement pour les regles a etat, et retourne la liste des alertes
    declenchees (peut etre vide)."""
    _remember(event)
    alerts = []
    for rule_fn in ALL_RULES:
        result = rule_fn(event)
        if result:
            alerts.append(result)
    return alerts


def reset_state():
    """Pour les tests : repart avec un etat vide."""
    _failed_logins.clear()
    _recent_actions.clear()
    _bruteforce_alerted.clear()
    _enum_alerted.clear()
