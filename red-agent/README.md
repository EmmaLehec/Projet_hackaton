# Agent Red Team — MiniHub

Agent LLM autonome (boucle ReAct) qui explore le bac à sable `target-env/`
(MiniHub) avec un objectif volontairement ambigu, pour illustrer le
phénomène de "dérive agentique" (goal drift) documenté dans l'incident
réel OpenAI × Hugging Face.

## Installation

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# éditer .env : mettre votre clé (Open Router par exemple)
```
## Test sans clé API (validation de la mécanique)

```bash
python test_agent_mock.py
```

Ce script rejoue un scénario scripté (sans appeler de vraie API LLM) pour
vérifier que les outils, la boucle et le logging fonctionnent.

## Lancement réel

Editer .env : mettre sa clé (Open Router par exemple)

```bash
python agent.py
```

Les décisions de l'agent sont journalisées dans `logs/red_agent_decisions.log`
(une ligne JSON par étape : pensée, outil appelé, résultat).