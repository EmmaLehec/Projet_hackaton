FROM nginx:alpine

# Le dashboard est une seule page statique, sans build ni dépendance.
COPY index.html /usr/share/nginx/html/index.html

EXPOSE 80
# nginx:alpine lance déjà nginx en foreground par défaut (pas de CMD à ajouter).
