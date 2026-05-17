# Bot Telegram Railway PostgreSQL

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
- gérer les permissions du groupe

## Admin

Il n'y a pas de commande admin générale.
L'admin envoie /start en privé au bot.
Si son ID est dans ADMIN_IDS, le panel admin s'affiche.

## Tables créées

- settings
- messages
- media_hashes
- banned_words
- user_violations
- reward_videos
- referrals
- pending_joins

## Suppression fermeture

Le bot enregistre chaque message du groupe dans la table messages.
Quand l'admin clique sur Fermer + effacer, le bot supprime tous les messages stockés puis vide la table.

## Vidéos

Envoie les vidéos au bot en privé depuis le compte admin.
Elles sont ajoutées automatiquement de 1 à 60.
