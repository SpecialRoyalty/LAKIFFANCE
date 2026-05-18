# Telegram Railway Bot - FINAL_COMPLETE_V10

## Inclus

- Panel admin avec boutons via /start en privé
- PostgreSQL Railway avec DATABASE_URL
- Ouverture / fermeture par session
- Suppression de tous les messages entre ouverture et fermeture
- Suppression des messages Telegram d'entrée et sortie
- Anti-liens : ban
- Photo avec mention : ban
- Mots interdits : mute 1j, puis 1 semaine, puis ban
- Anti-repost média sur 4 jours
- Upload de 60 vidéos en privé par admin
- Bouton 📢 Publier publicité activé uniquement à 60/60 vidéos
- Publicité avec bouton 🎁 Recevoir mon lien privé
- Lien personnalisé par utilisateur
- Validation après 5 minutes côté bot, sans l'afficher dans la pub
- Envoi automatique des vidéos selon paliers
- Stats parrainage

## Variables Railway

BOT_TOKEN=TON_NOUVEAU_TOKEN
BOT_USERNAME=TonBotUsername
ADMIN_IDS=5296696302
GROUP_ID=-1003812221754
DATABASE_URL=${{Postgres.DATABASE_URL}}
TIMEZONE=Europe/Paris
WEBHOOK_URL=https://TONAPP.up.railway.app
PORT=8080

## Droits Telegram requis

Le bot doit être admin du groupe avec :
- supprimer messages
- bannir utilisateurs
- restreindre utilisateurs
- gérer permissions
- inviter via lien

## Vérification

Dans les logs Railway, tu dois voir :

STARTING FINAL_COMPLETE_V10

Dans le panel admin, tu dois voir :
- 📢 Publier publicité
- 📊 Stats parrainage


## V10
- Horaire Europe/Paris 23h-1h maintenu automatiquement.
- Ouverture auto même si le bot redémarre pendant la plage.
- Fermeture auto avec suppression de session.
- Admins/owner exemptés liens et transferts.
- Non-admins : liens et transferts interdits.
