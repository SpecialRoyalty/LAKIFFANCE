# SESSION_CLEAN_V6

Version qui supprime uniquement les messages de la session entre ouverture et fermeture.

## Fonctionnement

- Ouvrir session crée une session.
- Tous les messages envoyés pendant la session sont stockés avec session_id.
- Fermer + effacer session supprime tous les messages de cette session.
- Le message "Groupe ouvert" appartient à la session, donc il est supprimé à la fermeture.
- Le message final "Groupe fermé" est envoyé après nettoyage, donc il reste seul.

## Logs Railway attendus

STARTING BOT VERSION: SESSION_CLEAN_V6_2026_05_18
TABLES IN DATABASE: [...]

## Variables

BOT_TOKEN=TON_NOUVEAU_TOKEN
ADMIN_IDS=5296696302
GROUP_ID=-1003812221754
DATABASE_URL=${{Postgres.DATABASE_URL}}
TIMEZONE=Europe/Paris
WEBHOOK_URL=https://TONAPP.up.railway.app
PORT=8080
