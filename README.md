# Telegram Railway Bot - FINAL_COMPLETE_V27

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

STARTING FINAL_COMPLETE_V27

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
STARTING FINAL_COMPLETE_V27


## V22 - Correction complète SQL / hash / anti-repost

Correction complète :
- `media_hashes.hash` existe toujours.
- `banned_hashes.hash` existe toujours.
- `hash` est en TEXT.
- `hash` est UNIQUE.
- `ON CONFLICT(hash)` fonctionne.
- anti-repost refonctionne.
- ban hash refonctionne.
- participation avec média nouveau refonctionne.
- nettoyage automatique des vieilles lignes nulles/doublons.
- réparation automatique des anciennes DB Railway partiellement migrées.

Important :
- si tu veux repartir 100% propre, tu peux supprimer toutes les tables puis relancer.
- sinon V22 tente de réparer automatiquement le schéma.

Vérification Railway :
STARTING FINAL_COMPLETE_V27

Test rapide :
1. envoie une photo ;
2. renvoie exactement la même photo ;
3. le bot doit supprimer la deuxième avec `♻️ C’est du vu et déjà vu.`


## V23 - Modération silencieuse premium

Changements :
- Les non-trusted utilisant `/ban` ou `/supprimer` :
  - commande supprimée ;
  - mute 2 jours ;
  - warning discret auto-delete.

- Les trusted :
  - `/ban` silencieux ;
  - `/supprimer` silencieux ;
  - commandes supprimées automatiquement.

- Suppression des messages techniques :
  - plus de message hash ;
  - plus de validation participation ;
  - plus de spam mode raid.

Vérification Railway :
STARTING FINAL_COMPLETE_V27


## V24 - Textes runtime corrigés

La logique V23 est conservée. Cette version corrige les textes réellement utilisés par les handlers :

- participation obligatoire ;
- anti-repost ;
- lien interdit ;
- transfert interdit ;
- mots interdits ;
- fake commandes modération ;
- avertissement non-participants ;
- lien privé ;
- récompense débloquée.

Messages techniques masqués :
- pas de mention hash en public ;
- pas de message mode raid ;
- pas de validation participation publique.


## V25 - Transferts autorisés

Changement :
- les messages transférés ne sont plus sanctionnés ;
- aucun ban/mute pour un forward ;
- tout le reste reste actif :
  - anti-liens ;
  - anti-repost ;
  - ban hash ;
  - participation obligatoire ;
  - trusted moderation ;
  - fake commandes `/ban` et `/supprimer` ;
  - kick non-participants.

Correction incluse :
- fix `MSG_FAKE_COMMAND` si la V24 contenait l'auto-référence cassée.

Vérification Railway :
STARTING FINAL_COMPLETE_V27


## V26 - Fix punish_ban + rapports admin

Corrections :
- `punish_ban()` accepte maintenant `custom_message=None`.
- Corrige l'erreur : `punish_ban() takes 3 positional arguments but 4 were given`.
- Les logs `Chat not found` pour les rapports admin sont clarifiés :
  l'admin doit ouvrir le bot en privé au moins une fois.
- Transferts toujours autorisés comme en V25.

Vérification Railway :
STARTING FINAL_COMPLETE_V27


## V27 - Hash robuste + message dissuasion modération

Ajouts :
- `MAX_HASH_FILE_MB=20`
- Si un média est trop gros :
  - pas de crash ;
  - pas de hash ;
  - participation non validée avec ce média ;
  - log : `HASH SKIPPED: file too big`.

Message dissuasion :
- toutes les 20 minutes pendant ouverture si sanctions > 0 ;
- supprimé automatiquement après 3 minutes ;
- affiche suppressions, exclusions et restrictions.

Vérification Railway :
STARTING FINAL_COMPLETE_V27
