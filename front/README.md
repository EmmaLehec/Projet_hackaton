# Dashboard — Salle d'opérations MiniHub

Une seule page HTML autonome (`index.html`, pas de build, pas de
dépendances) qui affiche en direct :
- à gauche, les actions du **Red Team** (`red-agent/api.py`, port 5002)
- à droite, les alertes du **Blue Team** (`blue-agent/api.py`, port 5001)

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

## Si les points de statut restent rouges

Les deux petits points en haut à droite ("Red Team" / "Blue Team")
passent au vert dès que la page arrive à joindre l'API correspondante.
S'ils restent rouges (`.down`), vérifie que les APIs tournent bien sur
les bons ports (`5001` et `5002`).

## Pointer vers d'autres URLs (déploiement cloud)

Clique sur "Paramètres de connexion" en haut de la page pour changer les
URLs des deux APIs — utile une fois que tu auras déployé sur ta VM Azure
(tu mettras alors `http://<ton-ip-publique>:5001` etc. à la place de
`127.0.0.1`). Le choix est mémorisé dans le navigateur (`localStorage`),
pas besoin de le refaire à chaque ouverture.

## Ce que la page ne fait PAS

Elle n'a aucun rôle dans la détection elle-même — elle ne fait qu'afficher
ce que les deux APIs renvoient. Toute la logique (règles, LLM, playbook)
reste dans `blue-agent/`, et l'exploration reste dans `red-agent/`. Si tu
fermes cette page, rien ne s'arrête côté agents.
