# Telegram Railway Bot - FINAL_COMPLETE_V15

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

STARTING FINAL_COMPLETE_V15

Si tu vois encore “Vidéo ajoutée”, Railway tourne encore sur une ancienne version.


## V14

Horaires :
- semaine : 22h00 → 00h00
- samedi : 23h00 → 01h00
- dimanche : 22h30 → 00h15

Countdown corrigé :
- heures avant dernière heure
- minutes pendant dernière heure
- fermeture : 30 min, 15 min puis minute par minute.


## V15 - Modération externe trusted

Ajout de :

TRUSTED_IDS=111111111,222222222

Commandes trusted dans le groupe, uniquement en réponse à un message :

/supprime
- supprime le message ciblé ;
- ajoute 1 strike à l’auteur ;
- à 2 strikes dans la même session :
  - mute 7 jours ;
  - suppression de tous ses messages de session.

/ban
- bannit l’auteur ciblé ;
- supprime tous ses messages de session ;
- récupère les hash de ses médias déjà postés ;
- ajoute ces hash dans banned_hashes.

Limites :
- 20 /supprime maximum par trusted par session ;
- 20 /ban maximum par trusted par session.

Protection :
- impossible de cibler owner ;
- impossible de cibler admin Telegram ;
- impossible de cibler ADMIN_IDS ;
- impossible de cibler TRUSTED_IDS.

Vérification logs Railway :
STARTING FINAL_COMPLETE_V15
