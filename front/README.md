# Dashboard 

Une seule page HTML autonome qui affiche en direct :
- à gauche, les actions du Red Team (`red-agent/api.py`, port 5002)
- à droite, les alertes du Blue Team (`blue-agent/api.py`, port 5001)

## Lancement

Il te faut **3 terminaux** en parallèle (plus besoin de lancer
`agent.py` séparément — l'API s'en charge à la demande) :

```bash
# Terminal 1 — la cible
cd target-env && docker compose up --build

# Terminal 2 — l'API du Red Team (expose ses décisions + un déclenchement à la demande)
cd red-agent && python3 api.py

# Terminal 3 — l'API du Blue Team (détection continue + alertes)
cd blue-agent && python3 api.py
```

Puis ouvre `http://127.0.0.1:8000/` dans ton navigateur. Le bouton **"Lancer
une exploration"** au-dessus de la colonne Red Team déclenche une
nouvelle campagne d'exploration à la demande (via `POST /api/run`) — pas
de boucle automatique, pour ne pas cramer ton budget API à chaque
rafraîchissement de la page.
---

## Front : Explication

`front` est l'interface de visualisation du projet depuis laquelle on observe l'affrontement de la Red Team et Blue Team en temps réel. C'est aussi depuis cette page qu'on **déclenche une attaque** d'un simple clic.

Le dashboard ne détecte rien et n'attaque rien lui-même. Il ne fait qu'afficher ce que les deux agents produisent de leur côté. 

---

## Architecture

Le dashboard interroge en boucle les deux agents via leurs API et redessine l'écran à partir de leurs réponses. Il ne parle jamais directement à MiniHub : il ne connaît que les deux agents.

```
                     interroge (toutes les 2,5 s)
   ┌─────────────────────────────────────────────────┐
   │                                                  ▼
 index.html                                    red-agent (API, port 5002)
 (le dashboard)  ◄── décisions de l'attaquant ──┘
   │
   │                                            blue-agent (API, port 5001)
   └────────────── alertes du défenseur ───────────────┘
```

- Le dashboard appelle `GET /api/decisions` sur l'agent Red Team et affiche, étape par étape, ce que l'attaquant a pensé, l'action qu'il a menée et le résultat obtenu.
- Il appelle aussi `GET /api/alerts` sur l'agent Blue Team et affiche les alertes détectées, avec leur niveau de gravité (faible, moyen, élevé, critique).
- Bouton « Lancer une exploration » : envoie un `POST /api/run` à l'agent Red Team pour démarrer une nouvelle campagne d'attaque.

Le tout se met à jour automatiquement toutes les 2,5 secondes. Deux points de statut, en haut de la page, passent au vert quand la page arrive à joindre chaque API, et au rouge sinon.

---

## Contenu du dossier

```
front/
├── index.html  
├── Dockerfile    
└── README.md    
```



