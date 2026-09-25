"""
llm_client.py
=============
Client LLM générique pour l'agent Blue Team.

  - le modèle stealth "Ling 3.0 Flash Sante (free)" via OpenRouter, gratuit
    
  - pour changer de LLM : on change juste l'URL/le nom du modèle dans le .env
"""

import json
import os
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv est optionnel ; sinon exporte tes variables manuellement

LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "")


class LLMError(RuntimeError):
    pass


def call_llm(messages, tools=None, temperature=0.2, max_tokens=800):
    """
    Appelle le backend LLM configuré avec une liste de messages au format
    OpenAI-like: [{"role": "system"|"user"|"assistant", "content": "..."}]

    Retourne le texte de la réponse (str).
    """
    
    url, key, model = LLM_BASE_URL, LLM_API_KEY, LLM_MODEL


    if not key:
        raise LLMError(
            f"Clé API manquante pour le backend. "
            f"Définis la variable d'environnement correspondante."
        )

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        data=json.dumps(payload),
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    try:
        message = data["choices"][0]["message"]
        content = message.get("content")
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(
            f"Structure de réponse inattendue de l'API : "
            f"{json.dumps(data, ensure_ascii=False)[:500]}"
        ) from e

    if not content or not content.strip():
        # Certains modèles (raisonnement) renvoient le texte dans un
        # champ différent au lieu de "content" -> on tente un repli
        # avant d'abandonner, et on affiche la réponse brute pour debug.
        content = message.get("reasoning_content") or message.get("reasoning")
        if not content or not content.strip():
            raise LLMError(
                f"Champ 'content' vide (ou juste des espaces) dans la réponse "
                f"du backend (modèle '{model}'). Réponse brute : "
                f"{json.dumps(data, ensure_ascii=False)[:500]}"
            )

    return content
