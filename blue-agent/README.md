# Agent Blue Team — MiniHub

Un agent de détection qui surveille en continu les journaux de MiniHub, repère les comportements suspects, les fait analyser par un LLM, puis déclenche une réponse. 

## Installation

```bash
python -m venv venv
venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env
# éditer .env : mettre votre clé (Open Router par exemple)
```

## Test sans clé API (validation de la mécanique)

```bash
python test_blue_agent_mock.py
```

Génère un scénario d'attaque simulé (bruteforce, accès non authentifié,
chaîne upload → admin) et vérifie que le pipeline complet détecte bien
les 5 alertes attendues, sans appeler de vraie API.

## Lancement réel — mode CLI

```bash
python blue_agent.py
```

Tourne en continu (poll toutes les `BLUE_POLL_INTERVAL` secondes),
affiche chaque alerte en console au fur et à mesure.

## Lancement réel — mode API

Editer .env : clé API  (Open Router par exemple)

```bash
python api.py
```

Expose :
- `GET http://127.0.0.1:5001/api/alerts` — les 50 dernières alertes
- `GET http://127.0.0.1:5001/api/status` — statut de l'agent


## Blue-agent : Explication

Blue-agent est notre agent d'IA défenseur. Pendant que l'agent Red Team attaque MiniHub, lui observe et cherche à détecter l'attaque en cours.

Afin que notre agent défenseur soit le plus proche du réel possible, il est "aveugle" par défaut. Il ne voit pas le raisonnement de l'attaquant, il ne dispose que de ce que MiniHub enregistre de son côté, c'est-à-dire son journal d'accès (`target-env/app/logs/access.log`).

### Un pipeline en quatre temps

Pour chaque nouvel événement observé dans les logs, l'agent enchaîne quatre étapes :

1. Règles : L'événement passe d'abord dans une série de règles de détection rapides et gratuites.
2. Analyse LLM : Seulement si une règle se déclenche, l'événement suspect est envoyé à un LLM qui joue le rôle d'un analyste : il explique l'alerte en une phrase, donne un niveau de confiance et recommande une action.
3. Réponse (playbook) : L'agent exécute l'action recommandée (surveiller, alerter l'équipe, isoler le service, révoquer des identifiants).
4. Journalisation — tout est écrit dans un fichier d'alertes, que le dashboard lit pour afficher la colonne « Blue Team ».

---

## Architecture 

```
`blue_agent.py` exécute cette chaîne en boucle, indéfiniment :

  target-env/app/logs/access.log
            │
            ▼
     0. log_reader.py  ──►  lit les nouvelles lignes
            │
            ▼
     1. rules.py  ──────►  règles rapides : suspect ? oui / non
            │ (si suspect)
            ▼
     2. classifier.py  ──►  llm_client.py  ──►  API LLM (analyse : explication, confiance, action)
            │
            ▼
     3. playbook.py  ────►  exécute l'action recommandée (simulée)  ──►  logs/blue_agent_responses.log
            │
            ▼
     4. journalise l'alerte  ──►  logs/blue_agent_alerts.log
                                          │
                                          ▼
                                  lu par le dashboard (front)


Par-dessus tout ça, api.py enveloppe la boucle de détection dans une petite API web (Flask). La boucle tourne en tâche de fond et l'API expose les alertes générées pour que le dashboard puisse les afficher en direct.

```

- **`blue_agent.py`** : Tourne en boucle, récupère les nouveaux événements et les fait passer dans le pipeline (règles → classifieur → playbook → journalisation).
- **`log_reader.py`** : Lit les journaux et ne renvoie à chaque tour que les nouvelles lignes depuis la dernière lecture. Il retient sa position sur le disque, pour ne pas rejouer tout l'historique à chaque redémarrage.
- **`rules.py`** : Contient les règles de détection (filtre de détection d'une attaque sans utilisation de LLM).
- **`classifier.py`** : Enrichit une alerte en demandant une analyse au LLM.
- **`playbook.py`** : Exécute l'action de réponse recommandée.

---

## Contenu du dossier

```
blue-agent/
├── blue_agent.py            # Boucle principale : orchestre tout le pipeline
├── log_reader.py            # Lit les logs et ne renvoie que les nouvelles lignes
├── rules.py                 # Règles de détection rapides (le premier filtre)
├── classifier.py            # Analyse fine d'une alerte par le LLM
├── llm_client.py            # Appel générique à l'API LLM
├── playbook.py              # Actions de réponse (simulées)
├── api.py                   # Enveloppe la boucle dans une API web (Flask) pour que le dashboard puisse lire les alertes.
├── test_blue_agent_mock.py  # Test du pipeline complet sans clé API
├── requirements.txt        
├── Dockerfile               
├── .env.example            
├── logs/                    # Reçoit blue_agent_alerts.log et blue_agent_responses.log
└── state/                   # Mémorise la position de lecture dans les logs
```

---

## Les règles de détection

Chaque règle vise une classe de comportement, pas un scénario scripté précis. L'objectif est de repérer l'attaquant quel que soit l'ordre de ses actions.

| Règle | Gravité | Ce qu'elle repère |
|---|---|---|
| `internal_endpoint_access` | Elevée | Accès à un endpoint interne qu'aucun usage légitime ne cible |
| `suspicious_file_upload` | Elevée | Upload d'un fichier à l'extension dangereuse (`.pkl`, `.sh`, `.exe`…) |
| `login_bruteforce_attempts` | Moyenne | Série d'échecs de connexion consécutifs depuis une même IP |
| `login_bruteforce_pattern` | Moyenne | Connexion réussie juste après plusieurs échecs (force brute aboutie) |
| `sensitive_path_enumeration` | Moyenne | Une IP sonde plusieurs endpoints sensibles distincts (reconnaissance) |
| `upload_then_admin_access` | Moyenne | Accès à la zone admin peu après un upload (chaîne d'exploitation) |
| `red_agent_sensitive_tool_use` | Faible | Usage d'un outil sensible par l'agent Red Team (seulement hors mode aveugle) |

> Limite : une détection par règles ne voit que ce qu'on lui a appris à voir. Une version avancée ajouterait de la détection d'anomalies (comparaison à un comportement « normal » de référence) pour attraper l'inconnu.

---

## Les actions de réponse

Le LLM recommande une action parmi quatre, exécutée par le playbook. Ces exécutions sont simulées, elles écrivent donc un l'action effectuée dans un journal (blue_agent_response_log) plutôt que réellement effectuer l'action (suffisant pour une démonstration).

| Action | Sens | En production, on brancherait… |
|---|---|---|
| `monitor` | Anomalie mineure : surveiller sans agir | (rien, simple observation) |
| `alert_team` | Anomalie confirmée : intervention humaine rapide | un webhook Slack / Discord |
| `isolate_service` | Compromission active probable : isoler la cible | une coupure réseau du conteneur |
| `revoke_credentials` | Fuite de secrets probable : les invalider | l'API du fournisseur cloud |

---

### Test sans clé API

`test_blue_agent_mock.py` rejoue un scénario d'attaque simulé (force brute, accès non authentifié, chaîne upload → admin) et vérifie que le pipeline complet détecte bien les alertes attendues, sans appeler de vraie API LLM.

---

