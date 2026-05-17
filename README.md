# Bot Telegram Railway PostgreSQL - vraie version corrigée

## Correction de cette version

- Les messages envoyés par le bot dans le groupe sont maintenant enregistrés dans la table messages.
- Quand le groupe ferme, les anciens messages "Groupe ouvert" et anciens "Groupe fermé" sont supprimés aussi.
- Le message actuel "Groupe fermé" reste affiché après la fermeture.
- Le menu Mots interdits a maintenant de vrais boutons :
  - Ajouter un mot
  - Supprimer un mot
  - Voir les mots
- Une table admin_states est ajoutée pour savoir si l'admin est en mode ajout ou suppression.
- Toutes les tables PostgreSQL sont créées au démarrage.

## Variables Railway

BOT_TOKEN=TON_NOUVEAU_TOKEN
ADMIN_IDS=5296696302
GROUP_ID=-1003812221754
DATABASE_URL=${{Postgres.DATABASE_URL}}
TIMEZONE=Europe/Paris
WEBHOOK_URL=https://TONAPP.up.railway.app
PORT=8080

## Droits du bot dans le groupe

Le bot doit être admin avec :
- supprimer messages
- bannir utilisateurs
- restreindre utilisateurs
- gérer permissions du groupe

## Admin

En privé avec le bot :
/start

## Tables

settings
messages
media_hashes
banned_words
user_violations
reward_videos
referrals
pending_joins
admin_states
