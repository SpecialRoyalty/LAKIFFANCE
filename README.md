# Bot Telegram Railway PostgreSQL - version boutons corrigée

## Variables Railway

BOT_TOKEN=TON_NOUVEAU_TOKEN
ADMIN_IDS=5296696302
GROUP_ID=-1003812221754
DATABASE_URL=${{Postgres.DATABASE_URL}}
TIMEZONE=Europe/Paris
WEBHOOK_URL=https://TONAPP.up.railway.app
PORT=8080

## Important

Le bot doit être admin du groupe avec ces droits :
- supprimer messages
- bannir utilisateurs
- restreindre utilisateurs
- gérer permissions du groupe

## Admin

L'admin envoie /start en privé au bot.
Si son ID est dans ADMIN_IDS, le panel admin s'affiche.

## Correction incluse

Cette version corrige l'erreur Telegram :
"Message is not modified"

Les boutons ON/OFF changent maintenant réellement le texte du panel.
