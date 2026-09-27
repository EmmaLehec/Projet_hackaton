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


---

## Red-agent : Explication

`red-agent` est notre agent d'IA attaquant. Il joue le rôle des agents d'OpenAI dans l'incident réel : on ne lui demande jamais explicitement d'attaquer, mais son objectif ambigu le pousse à sonder la plateforme, tester des identifiants, consulter des endpoints internes et uploader des fichiers.

### La boucle ReAct

Son fonctionnement repose sur une boucle ReAct (Reason & Act) donc au lieu de répondre d'un seul coup, le modèle avance par petites étapes, en alternant réflexion et action. À chaque tour de boucle, l'agent :

1. observe la situation (au départ, sa mission ; ensuite, le résultat de son action précédente) ;
2. raisonne en interrogeant un LLM, qui décide de la prochaine action à mener ;
3. agit en exécutant un des outils qu'on lui a fourni; 
4. observe le résultat de cet outil, qui devient le point de départ de l'étape suivante.

L'agent répète ce cycle jusqu'à ce qu'il estime avoir fini, ou jusqu'à atteindre un nombre maximal d'étapes (qu'on a fixé à 12 afin de ne pas épuiser notre API après une tentative).

### Les outils

Un LLM, seul, ne sait que produire du texte : il ne peut pas cliquer, envoyer une requête ou lire une page web. Pour qu'il puisse agir sur MiniHub, on lui fournit une petite boîte à outils : des fonctions prédéfinies, chacune capable d'une action concrète. À chaque étape, le LLM ne fait pas l'action lui-même : il choisit un outil dans la liste et indique les paramètres à utiliser ; c'est notre code qui exécute réellement l'appel et lui renvoie le résultat.

Dans notre cas, l'agent dispose de quatre outils : sonder une page de la cible, tenter une connexion, uploader un fichier, et interroger l'endpoint interne de métadonnées.

### Architecture : 


```
                choisit une action              exécute l'action
  agent.py  ─────────────────────►  llm_client.py ──► API LLM (OpenRouter…)
 (la boucle)                                │
     │                                      │ renvoie {thought, tool, args}
     │  ◄───────────────────────────────────┘
     │
     ├──► tools.py  ──► requête HTTP ──► MiniHub (target-env)
     │      (les outils)                  la cible vulnérable
     │
     └──► decision_logger.py ──► logs/red_agent_decisions.log
            (journalise chaque étape)
```

- **agent.py** orchestre la boucle : c'est lui qui décide quand appeler le LLM, quel outil exécuter et quand s'arrêter.
- **llm_client.py** est le seul point de contact avec le LLM : `agent.py` lui envoie l'historique de la conversation, il renvoie la décision du modèle (au format JSON : une pensée, un outil, ses arguments).
- **tools.py** contient les outils : quand `agent.py` a reçu la décision du LLM, il appelle l'outil correspondant, qui envoie une requête à MiniHub.
- **decision_logger.py** enregistre chaque étape dans un fichier de logs, pour pouvoir rejouer et analyser le comportement de l'agent après coup.

Par-dessus tout ça, api.py enveloppe la boucle dans une petite API web : c'est le point d'entrée qui permet de déclencher une exploration à distance (depuis le dashboard, par exemple) plutôt que de lancer l'agent à la main.
---

## Contenu du dossier

```
red-agent/
├── agent.py               
├── tools.py             
├── llm_client.py          
├── decision_logger.py    
├── api.py               
├── test_agent_mock.py   
├── requirements.txt      
├── Dockerfile             
├── .env.example           
└── logs/                 
```

### `agent.py`

Contient l'orchestrateur ReAct et le system prompt qui définit l'objectif ambigu de l'agent. À chaque étape, il :

1. Envoie l'historique de la conversation au LLM ;
2. Attend une réponse au format JSON (`thought`, `tool`, `args`) ;
3. Exécute l'outil demandé et récupère le résultat (l'observation) ;
4. Renvoie cette observation au LLM pour l'étape suivante.

Il gère aussi les cas d'erreur : réponse LLM mal formée, outil inconnu, erreurs API répétées. La boucle est limitée à 12 étapes pour éviter les explorations sans fin et maîtriser le coût des appels LLM.

### `tools.py` 

Les seules actions que l'agent peut mener. Chaque outil est un simple appel HTTP vers MiniHub, via une session partagée qui conserve les cookies :

| Outil | Action | Vulnérabilité visée |
|---|---|---|
| `scan_endpoint(path)` | GET sur un chemin de la cible ; renvoie le statut et un extrait de la réponse | Reconnaissance |
| `try_login(username, password)` | Tente une connexion sur `/login` | VULN-03 |
| `upload_file(filename, content)` | Uploade un fichier (nécessite d'être connecté) | VULN-01 |
| `read_internal_metadata()` | Interroge `/internal/metadata` | VULN-02 |


### `llm_client.py`

Assure la compatibilité avec les API au format OpenAI (/chat/completions) tout en gérant les spécificités des différents fournisseurs de modèles.

### `decision_logger.py`

Écrit chaque étape de l'agent dans les logs de la red agent, une ligne JSON par étape (horodatage, pensée, outil, arguments, observation).

### `api.py`

Enveloppe l'agent dans une API web. Contrairement à l'agent Blue Team qui surveille en continu, une exploration Red Team coûte cher (plusieurs appels LLM), donc elle se lance à la demande plutôt qu'en boucle.:

| Route | Méthode | Rôle |
|---|---|---|
| `/api/run` | POST | Lance une nouvelle exploration (en arrière-plan) |
| `/api/decisions` | GET | Renvoie les 50 dernières décisions |
| `/api/status` | GET | Statut de l'agent |


### `test_agent_mock.py` — test sans clé API

Rejoue un scénario scripté sans appeler de vraie API LLM, pour vérifier que les outils, la boucle et la journalisation fonctionnent. Ceci a été très utile pour valider la mécanique avant de dépenser du budget API.

---
