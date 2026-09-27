# Dashboard 

Une seule page HTML autonome qui affiche en direct :
- à gauche, les actions du Red Team (`red-agent/api.py`, port 5002)
- à droite, les alertes du Blue Team (`blue-agent/api.py`, port 5001)

## Lancement en local

Ouvrir au préalable l'application Docker Desktop

```bash
# Terminal ouvert depuis dossier front/
python -m http.server 8000
```

Ouvrir `http://127.0.0.1:8000/` dans le navigateur. 

Cliquer en haut à droite sur Paramètres de connexion et remplacer les URLs des API par : 
- URL locale Red agent : http://127.0.0.1:5002/
- URL locale Blue agent : http://127.0.0.1:5001/

Vérifier/attendre que les pastilles de Red et Blue team soient vertes.

Dans la colonne de gauche, lancer une exploration à la demande pour lancer le Red agent (via `POST /api/run`) et suivre ses décisions exposées.
Il n'y a pas de boucle automatique, pour ne pas vider le budget API à chaque rafraîchissement de la page.

Regarder la colonne de droite pour voir les alertes affichées en direct au fur et à mesure que le Red agent exploite l'environnement.


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



