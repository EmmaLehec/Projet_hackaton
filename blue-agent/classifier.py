"""
classifier.py
=============
Prend une alerte déclenchée par une règle (rules.py) et demande au LLM
une analyse plus fine : explication en langage naturel, niveau de
confiance, et action recommandée parmi une liste fermée. Ne sert que sur
les événements déjà jugés suspects par les règles -> peu d'appels, donc
peu coûteux en budget API.
"""

import json
import re

from llm_client import call_llm, LLMError

SYSTEM_PROMPT = """Tu es un analyste SOC (Security Operations Center) qui
reçoit des alertes brutes déclenchées par des règles de détection sur une
plateforme d'hébergement de modèles ML nommée MiniHub. Pour chaque
alerte, tu dois répondre avec UNIQUEMENT un objet JSON, rien d'autre
autour, au format :

{
  "explanation": "une explication claire en UNE SEULE phrase courte (moins de 30 mots), pour un humain non technique",
  "confidence": <nombre entre 0 et 1>,
  "recommended_action": "<une valeur parmi: monitor | alert_team | isolate_service | revoke_credentials>"
}

Reste très concis sur "explanation" -- une phrase, pas un paragraphe.
Critères de choix de l'action recommandée :
- "monitor" : anomalie mineure, à surveiller sans agir immédiatement.
- "alert_team" : anomalie confirmée nécessitant une intervention humaine rapide.
- "isolate_service" : compromission active probable, isoler le service cible.
- "revoke_credentials" : des identifiants/secrets ont potentiellement fuité, les révoquer.
"""


def extract_json(text: str) -> dict:
    if not isinstance(text, str):
        raise ValueError(f"Réponse LLM invalide (attendu str, reçu {type(text).__name__}): {text!r}")
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))

    # Repli : la réponse a probablement été tronquée avant la fermeture
    # du JSON (max_tokens atteint côté fournisseur). On tente de sauver
    # au moins le champ "explanation" par une extraction plus permissive
    # plutôt que de tout jeter -- une explication partielle reste plus
    # utile qu'un message d'erreur technique affiché à l'utilisateur.
    partial = re.search(r'"explanation"\s*:\s*"([^"]*)', text, re.DOTALL)
    if partial:
        return {
            "explanation": partial.group(1).strip() + "…",
            "confidence": 0.4,
            "recommended_action": "monitor",
            "_truncated": True,
        }
    raise ValueError("Aucun JSON exploitable dans la réponse du LLM (réponse probablement tronquée).")


def classify_alert(alert: dict) -> dict:
    """Enrichit une alerte brute (issue de rules.py) avec l'analyse du LLM.
    En cas d'erreur LLM (clé manquante, timeout...), retombe sur une
    explication par défaut basée uniquement sur la règle déclenchée, pour
    que le pipeline ne s'arrête jamais."""
    user_content = (
        f"Règle déclenchée : {alert['rule']}\n"
        f"Sévérité de la règle : {alert['severity']}\n"
        f"Raison : {alert['reason']}\n"
        f"Événement brut : {json.dumps(alert['event'], ensure_ascii=False)}"
    )

    try:
        raw_response = call_llm([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ], max_tokens=700)
        analysis = extract_json(raw_response)
    except LLMError as e:
        # Le LLM lui-même n'a pas répondu (clé manquante, timeout...)
        print(f"[classifier] LLM indisponible ({e}) -- repli sur la règle seule.")
        analysis = {
            "explanation": alert["reason"],
            "confidence": 0.5,
            "recommended_action": "alert_team" if alert["severity"] == "high" else "monitor",
        }
    except ValueError as e:
        # Le LLM a répondu mais le texte n'était pas exploitable (JSON
        # tronqué ou absent) -- on log le détail pour debug côté serveur,
        # mais on n'affiche jamais ce message technique dans l'alerte.
        print(f"[classifier] Réponse LLM inexploitable ({e}) -- repli sur la règle seule.")
        analysis = {
            "explanation": alert["reason"],
            "confidence": 0.4,
            "recommended_action": "alert_team" if alert["severity"] == "high" else "monitor",
        }

    return {**alert, "analysis": analysis}