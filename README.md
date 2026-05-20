# Telegram Railway Bot - FINAL_COMPLETE_V21

Version cohérente nettoyée.

## Corrections V18

- Suppression totale de l'affichage `Vidéos : x/60`.
- Suppression du bouton/ancienne logique `Vidéos 60/60`.
- Suppression du message `Vidéo ajoutée : x/60`.
- Le système de récompenses utilise uniquement `🔗 Liens récompenses`.
- La publicité est bloquée tant que les 4 liens ne sont pas remplis :
  - palier 1
  - palier 10
  - palier 50
  - palier 60
- Le panel affiche maintenant :
  - `🔗 Liens récompenses : ✅ complets` ou `❌ incomplets`
- Le reste de la V17 est conservé :
  - horaires dynamiques ;
  - countdown corrigé ;
  - trusted moderation ;
  - bilan trusted fin de session ;
  - participation ;
  - ban hash ;
  - anti-repost ;
  - règles auto ;
  - mode RAID ;
  - sanctions silencieuses.

## Vérification Railway

Dans les logs :

STARTING FINAL_COMPLETE_V21

Si tu vois encore `Vidéos : x/60`, c'est que Railway tourne encore sur une ancienne version.


## V19 - Priorité de modération corrigée

Ordre appliqué :
1. `/ban` et `/supprime` trusted en priorité via CommandHandler.
2. Commandes `/` normales supprimées ; récidive mute 1 mois.
3. Admins/owner exemptés.
4. Liens interdits = ban direct.
5. Transferts interdits = ban direct.
6. Photo + mention = ban direct.
7. Hash interdit = ban direct.
8. Repost média = suppression.
9. Mots interdits = sanctions.
10. Participation obligatoire seulement en dernier.

Donc si un non-participant envoie un lien, il est banni pour lien.


## V20 - Kick non-participants contrôlé

Ajout :
- bouton `🥾 Kick non-participants ON/OFF`
- si OFF : seulement dissuasion et identification
- si ON : kick automatique après 3 jours sans participation
- limite : 20 kicks / jour
- nettoyage de l'état participant après kick
- bilan privé envoyé aux ADMIN_IDS après kick

Message d'avertissement enrichi :
- obligation d'envoyer 1 photo ou 1 vidéo jamais déjà postée
- une seule participation suffit à vie
- compteur total déjà supprimés
- état kick automatique ON/OFF
- limite 20 suppressions/jour


## V21 - Suppression robuste + DB propre

- Si Telegram répond `Message to delete not found`, le bot nettoie l'entrée PostgreSQL et continue.
- Plus de blocage de fermeture à cause d'anciens messages déjà supprimés.
- Ajout d'un durcissement du schéma au démarrage avec `ADD COLUMN IF NOT EXISTS`.
- Compatible base neuve et ancienne base partiellement migrée.

Vérification Railway :
STARTING FINAL_COMPLETE_V21
