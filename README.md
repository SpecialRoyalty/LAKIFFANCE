# Telegram Railway Bot - FINAL_COMPLETE_V13

Version cohérente après remplacement des 60 vidéos par des liens récompenses.

## Corrections V13

- Suppression complète de l’ancien système “Vidéo ajoutée 1/60”.
- Plus aucun upload de vidéos récompenses.
- Tout passe par `🔗 Liens récompenses`.
- Les 4 liens requis sont : palier 1, 10, 50 et 60.
- `📢 Publier publicité` reste bloqué tant que les 4 liens ne sont pas renseignés.
- `🚫 Ban hash` : le prochain média envoyé en privé sert uniquement à bannir son hash.
- Média envoyé hors mode `Ban hash` : pas ajouté, message d’explication.
- Participation : validation uniquement avec photo/vidéo nouvelle.
- Anti-repost : hash média sur 10 jours.
- Ban hash : hash interdit reposté = ban direct.
- Admins/owner exemptés des liens et transferts.
- Non-admins : liens et transferts interdits.
- Messages d’entrée/sortie supprimés.
- Auto ouverture Europe/Paris 23h → 1h.
- Fermeture avec suppression des messages de session.
- Règles auto, broadcast, mode RAID, sanctions silencieuses, relance non-participants.

## Variables Railway

BOT_TOKEN=TON_NOUVEAU_TOKEN
BOT_USERNAME=TonBotUsername
ADMIN_IDS=5296696302
GROUP_ID=-1003812221754
DATABASE_URL=${{Postgres.DATABASE_URL}}
TIMEZONE=Europe/Paris
WEBHOOK_URL=https://TONAPP.up.railway.app
PORT=8080

## Vérification

Dans les logs Railway :

STARTING FINAL_COMPLETE_V13

Si tu vois encore “Vidéo ajoutée”, Railway tourne encore sur une ancienne version.
