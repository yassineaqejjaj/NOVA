# ADR 001 — Identité fédérée (OIDC) et espace/projet communs à ORION

* **Statut** : proposé (cadrage et contrats). **Aucune implémentation, aucun changement d'authentification.**
* **Date** : 2026-10-16 · **Ticket** : NOV-100 (audit ORION du 13/10/2026, parent NOV-65)
* **Périmètre** : NOVA, ORBIT, FORGE. Ce document est de la documentation : l'implémentation fait l'objet des tickets de
  suite listés au §10 (Backlog), pas de la livraison avant la mise en production.

## 1. Contexte : l'existant (vérifié dans le code, 13–16/10/2026)

| Service | Authentification aujourd'hui | Autorisations | Clearance (C0–C3) | Espace / projet |
|---|---|---|---|---|
| **NOVA** | Keycloak OIDC (BFF, Authorization Code + PKCE) : cookie de session `nova_session` (HS256) ou jeton d'accès Keycloak validé (JWKS, issuer, audience `nova-web`) ; connexion mot de passe NOVA (compte local) ; mode `dev` interdit en production | rôle de realm `nova-admin` = administrateur ; rôles de projet locaux `viewer ⊂ editor ⊂ owner` (`ProjectMember`) | celle du compte ORBIT lié, sinon C1 par défaut (`DEFAULT_CLEARANCE`) | `Project` NOVA (UUID + slug) relié à un projet ORBIT par `ProjectReference` ; pas d'entité « espace » |
| **ORBIT** | mot de passe (argon2) + session (cookie / Bearer JWT HS256) ; clés d'agent `orb_…` par projet ; **ni SSO ni MFA** | `User.is_admin` ; rôle de projet `viewer ⊂ editor ⊂ owner` (membre du projet) | `User.clearance` et `clearance` de la clé d'agent (0–3, défaut 1) | projet identifié par `{slug}` ; pas d'entité « espace » |
| **FORGE** | e-mail + mot de passe (argon2), JWT HS256 ; clés de service `fgk_<prefix>_<secret>` ; **aucun OIDC** | rôles **globaux** `viewer ⊂ evaluator ⊂ editor ⊂ maintainer ⊂ admin` | `clearance` 0–3 de l'utilisateur / de la clé | **aucun modèle d'organisation, de projet ou d'équipe** |

Conséquences observées : le même mot (« viewer », « editor », « admin ») n'a pas la même portée d'un service à l'autre ;
NOVA agit auprès d'ORBIT avec **une session ORBIT liée par utilisateur qui expire** (repli sur la clé d'agent du projet,
avec sa clearance réduite : NOV-93, état visible dans `GET /api/v1/me/links`) ; FORGE ne sait pas séparer deux
entreprises ou deux projets ; trois bases d'identité à synchroniser à la main, sans MFA ni révocation centralisée.

## 2. Décision

1. **Un seul fournisseur OIDC pour les trois services** : le Keycloak d'ORION (realm commun `orion`, clients `nova-web`,
   `orbit` et `forge`, plus des comptes de service pour le service-à-service ; le realm `nova` actuel est renommé ou
   migré dans le ticket 1). NOVA utilise déjà Keycloak ; ORBIT et FORGE
   deviennent des *relying parties* (Authorization Code + PKCE pour les navigateurs, validation JWKS / issuer / audience
   pour les API). L'authentification forte (MFA, politique de mots de passe, verrouillage) est portée par l'IdP.
2. **Chaque service garde ses autorisations.** Le jeton prouve *qui* est l'utilisateur et *dans quel espace* ; il
   n'accorde jamais, à lui seul, un droit dans un service. Chaque service convertit les claims en rôle et en habilitation
   **avec sa propre table** (§4) et conserve ses appartenances locales (membres d'un projet ORBIT / NOVA). Les
   sémantiques de rôle restent propres à chaque service : on mappe, on ne les fusionne pas.
3. **Identifiants communs d'espace et de projet** : `orion_workspace_id` et `orion_project_id` (§5), portés par le jeton
   et stockés par chaque service ; les slugs actuels restent des alias lisibles.
4. **Délégation explicite** : NOVA n'utilise plus une session ORBIT liée par l'utilisateur ; elle échange le jeton de
   l'utilisateur (OAuth 2.0 Token Exchange, RFC 8693, *on-behalf-of*) contre un jeton court à l'audience du service cible
   (§6).
5. **Clés d'agent et service-à-service conservées** (`orb_…`, `fgk_…`, jeton entrant de NOVA), rattachées à un espace /
   projet, jamais substituées à une identité utilisateur (§7).
6. **Migration progressive des comptes existants**, sans coupure, avec retour arrière (§8).
7. **Isolation d'espace = contrat testé** (§9), pas seulement une convention de requête.

Alternatives écartées : (a) un IdP par service (statu quo, pas de SSO ni de MFA commun) ; (b) un jeton « super-admin »
partagé qui porte les rôles de tous les services (une fuite donne tout ; sémantiques incompatibles) ; (c) fusionner les
bases d'utilisateurs en une seule table partagée (couplage de schémas, déploiements liés) ; (d) transmettre tel quel le
jeton utilisateur d'un service à l'autre (audience ignorée, rejeu possible, durée trop longue).

## 3. Contrat des claims du jeton d'accès

Le jeton d'accès est un JWT signé par l'IdP (RS256, JWKS) ; chaque service le valide (signature, `iss`, `aud`, `exp`,
`nbf`) avant de lire quoi que ce soit d'autre. Tout claim inconnu est ignoré.

| Claim | Type | Obligatoire | Sens | Utilisé par |
|---|---|---|---|---|
| `iss` | URL | oui | émetteur : le realm `orion` | tous (validation) |
| `sub` | chaîne opaque, stable | oui | identité de l'utilisateur (ou du compte de service) ; **clé de rapprochement des comptes** | tous |
| `aud` | chaîne / liste | oui | service destinataire : `nova-web`, `orbit`, `forge` (un jeton par audience) | tous (validation) |
| `exp`, `iat`, `nbf` | entiers | oui | validité courte (5–15 min pour un jeton délégué, §6) | tous |
| `email`, `email_verified` | chaîne, booléen | oui | rapprochement initial des comptes (seulement si `email_verified`) | migration §8 |
| `name` | chaîne | non | affichage | tous |
| `orion_workspace_id` | UUID | oui pour un utilisateur | **espace** de l'utilisateur : frontière d'isolation (§9) | tous |
| `orion_project_id` | UUID | non | **projet actif** de la requête ; présent surtout dans un jeton échangé (§6) ; l'appartenance au projet reste vérifiée localement | NOVA, ORBIT, FORGE (après le modèle projet) |
| `realm_access.roles` | liste | non | rôles de realm nommés `<service>-<rôle>` (`nova-admin`, `orbit-admin`, `forge-editor`…) ; seuls les rôles du préfixe du service lisant le jeton comptent | chaque service pour lui-même |
| `orion_clearance` | entier 0–3 | non | **plafond** de classification accordé par l'organisation ; ne relève jamais l'habilitation locale (§4) | tous |
| `act` | objet `{sub, client_id}` | seulement si délégué | acteur qui agit au nom de `sub` (RFC 8693) : la trace d'audit garde les deux | tous (audit) |
| `scope` | liste | non | portée demandée, ex. `orion:context.read`, `orion:run.execute` ; un service refuse ce qu'il n'a pas listé | tous |
| `amr` | liste | non | méthode d'authentification (`pwd`, `mfa`, `sso`) ; une opération sensible peut exiger `mfa` | NOVA, ORBIT |

Règles : un utilisateur appartient à **un** espace dans le jeton (`orion_workspace_id`) ; l'appartenance à plusieurs
espaces se traduit par plusieurs sessions, jamais par une liste dans un même jeton. Un jeton sans
`orion_workspace_id` n'ouvre aucune ressource d'espace.

## 4. Claims → rôle et habilitation, par service

Règle commune : **effective clearance = min(habilitation locale, `orion_clearance` si présent)** ; une absence de claim ne
donne jamais plus que le défaut local. Rôle effectif = rôle local (appartenance), plafonné par le rôle de realm si
celui-ci existe.

| Entrée | NOVA | ORBIT | FORGE |
|---|---|---|---|
| `aud` attendu | `nova-web` | `orbit` | `forge` |
| Administrateur de la plateforme | rôle de realm `nova-admin` → `is_admin` (déjà en place) | rôle `orbit-admin` → `User.is_admin` | rôle `forge-admin` → rôle `admin` |
| Rôle fonctionnel | rôle de **projet** local `viewer ⊂ editor ⊂ owner` (`ProjectMember`) ; aucun rôle de realm n'en accorde un | rôle de **projet** local `viewer ⊂ editor ⊂ owner` (membre du projet `orion_project_id`) | rôle de realm `forge-viewer`, `forge-evaluator`, `forge-editor`, `forge-maintainer` → le plus élevé ; rôle **global** à l'espace tant que le modèle projet n'existe pas (§10, ticket 4) |
| Habilitation (C0–C3) | `min(clearance du compte ORBIT lié / délégué, orion_clearance)` ; C1 sans lien (inchangé) | `min(User.clearance, orion_clearance)` | `min(clearance locale, orion_clearance)` |
| Sensibilité C3 / secret | accès tant que l'habilitation effective ≥ 3 ; sinon refus (`CLASSIFICATION_REFUSED`) | filtre déjà appliqué par la recherche (jamais en dessous de la classification de la source) | idem pour les scénarios privés ; jamais d'envoi à un LLM au-dessus du plafond (`llm_max_classification`) |
| Espace | filtre `orion_workspace_id` sur toute requête (tâches, artefacts, projets, liens) | filtre sur tout projet / document / mémoire | filtre sur agents, scénarios, runs, jeux de données, clés (après le modèle espace) |
| Opération sensible | `amr` ∋ `mfa` pour lier un service, publier vers ORBIT, administrer | `amr` ∋ `mfa` pour administrer, gérer les clés d'agent | `amr` ∋ `mfa` pour administrer, gérer les clés et identifiants |
| Compte de service (client credentials) | rôle technique `service` (déjà : `is_service`, jamais une session utilisateur) | clé d'agent équivalente, clearance explicite | clé `fgk_…` équivalente, rôle explicite |

Équivalences à ne **pas** supposer : `viewer` NOVA (lire contexte et artefacts d'un projet) ≠ `viewer` FORGE (tout lire
sauf le contenu masqué des scénarios privés) ≠ `viewer` ORBIT (lire les sources du projet selon ACL et classification).
Les tests de contrat de claims (§10) fixent ces correspondances.

## 5. Espace et projet communs

* **`orion_workspace_id`** (UUID v4 ou v7, immuable) : l'*espace* = la frontière d'isolation et de facturation d'une
  entreprise (multi-entreprises). Créé et gouverné dans l'IdP (attribut d'organisation) ; copié dans chaque service à la
  création du compte et de chaque ressource.
* **`orion_project_id`** (UUID, immuable, unique **globalement**, rattaché à un seul espace) : le *projet* ORION au sens du
  métier. Chaque service y rattache sa représentation locale : le projet ORBIT (aujourd'hui `{slug}`), le `Project` NOVA
  (aujourd'hui relié par `ProjectReference`), le futur projet FORGE. Le slug devient un alias modifiable ; l'identifiant
  fait foi dans les jetons, les journaux, les snapshots, les runs FORGE et les tags d'évaluation.
* **Annuaire** : la table de correspondance `orion_project_id` ↔ identifiants locaux est tenue par chaque service
  (aucun service ne lit la base d'un autre). Un projet inconnu d'un service reste invisible (404) : on ne distingue pas
  « inexistant » de « autre espace » (§9).
* **Transport** : `orion_workspace_id` / `orion_project_id` dans le jeton (§3), et en en-têtes `X-Orion-Workspace` /
  `X-Orion-Project` ignorés pour l'autorisation (information de corrélation seulement) pour les appels par clé d'agent.

## 6. Délégation (token exchange / on-behalf-of)

Remplace « NOVA relie un compte ORBIT par session qui expire ».

1. L'utilisateur se connecte à NOVA par l'IdP ; NOVA détient son jeton d'accès (ou un jeton de rafraîchissement
   chiffré, selon la politique de l'IdP).
2. Pour appeler ORBIT ou FORGE **pour lui**, NOVA demande à l'IdP un jeton par *Token Exchange* : `subject_token` = jeton
   de l'utilisateur, `audience` = `orbit` ou `forge`, `scope` demandé (le plus petit utile), `resource` / paramètre
   `orion_project_id` = projet cible. Le jeton obtenu a une durée courte (5 min), `sub` = l'utilisateur, `act` = NOVA, et
   n'est ni stocké ni réutilisé pour un autre projet.
3. Le service cible valide, applique **ses** autorisations (§4) à `sub`, et journalise `sub` **et** `act`.
4. NOVA ne peut pas obtenir plus que ce que l'utilisateur a : politique d'échange limitée par client, audience et scopes ;
   refus si l'utilisateur est désactivé ou n'est plus membre du projet (la révocation prend effet à l'expiration de 5 min
   au plus, ou immédiatement via les événements de révocation déjà reçus d'ORBIT, NOV-81).
5. Sans utilisateur (tâche planifiée, protocole FORGE → NOVA) : compte de service explicite (§7), jamais l'identité d'un
   utilisateur « empruntée ».

L'écran de santé des liens (`/me/links`, NOV-93) devient la vue de ce mécanisme : voir §11.

## 7. Clés d'agent et service-à-service

* **`orb_…` (ORBIT) et `fgk_…` (FORGE)** restent valides en parallèle de l'OIDC (compatibilité, intégrations existantes,
  CI). Chaque clé est **rattachée à un `orion_workspace_id` et à un `orion_project_id`** (ou à un espace seulement
  pour une clé d'administration), porte sa **clearance explicite** et son rôle, et s'authentifie avec ses propres
  secrets hachés comme aujourd'hui.
* Une clé n'agit **jamais** pour un utilisateur : l'audit montre « clé X », pas un utilisateur. La délégation passe par le
  §6.
* Le jeton entrant de NOVA pour FORGE (`forge_inbound_token`) est remplacé à terme par un jeton de compte de service
  (client credentials, audience `nova-web`, scope `orion:run.execute`) ; en attendant il est conservé, comparé en temps
  constant (déjà le cas).
* Rotation : durée de vie maximale et rotation documentées par type de clé ; une clé d'un projet sortant de l'espace est
  révoquée.

## 8. Plan de migration des comptes existants

Principe : **additif, réversible, sans changer les identifiants des données** (les UUID d'utilisateur locaux ne bougent
pas ; on ajoute `sub` OIDC comme identifiant externe).

| Phase | Action | Condition de sortie | Retour arrière |
|---|---|---|---|
| 0. Inventaire (lecture seule) | exporter par service : e-mail, rôle, clearance, dernière connexion, comptes de service et clés ; détecter doublons et e-mails non vérifiables ; décider l'espace de chacun | tableau de rapprochement validé par les propriétaires | aucun effet |
| 1. IdP prêt en préproduction | realm `orion`, clients, mappers des claims du §3, utilisateurs importés (sans mot de passe) | connexion OIDC OK en préprod sur les trois services | supprimer le realm de test |
| 2. Double pile | chaque service accepte OIDC **en plus** de son mot de passe actuel ; liaison `sub` ↔ compte local lors de la 1re connexion SSO, par e-mail vérifié **et confirmation de l'utilisateur** (jamais automatique par le seul e-mail) | tous les comptes actifs liés ou explicitement exclus | désactiver le bouton SSO ; les mots de passe fonctionnent encore |
| 3. SSO par défaut | le mot de passe local est désactivé pour les comptes liés (reste : un compte *break-glass* administrateur par service, hors SSO, détenu hors ligne) ; MFA exigée par l'IdP | 30 jours sans incident, aucun compte actif non lié | réactiver le mot de passe d'un compte (drapeau) |
| 4. Nettoyage | suppression des mots de passe locaux et des liaisons de session ORBIT de NOVA ; clés d'agent conservées | revue de sécurité | restauration depuis la sauvegarde de la phase 3 |

Cas particuliers : un compte sans correspondance reste local (marqué « à rapprocher ») ; deux comptes locaux pour un
même `sub` sont fusionnés par un administrateur, jamais automatiquement ; l'espace d'un compte vient de l'inventaire,
pas déduit du domaine de l'e-mail. **Aucune étape de cette migration n'est exécutée en production avant la levée du gel
et la validation des tickets de suite en préproduction.**

## 9. Isolation d'espace : un contrat testé

Invariants :

1. toute ressource appartient à **exactement un** `orion_workspace_id` (colonne obligatoire, non modifiable) ;
2. l'espace de la requête vient **du jeton validé** (ou de la clé), jamais d'un paramètre, d'un en-tête ou d'un corps ;
3. un accès hors espace répond comme une ressource **inexistante** (404), identique à un identifiant inconnu ;
4. un administrateur d'espace n'administre que son espace ; l'administration de la plateforme est un rôle distinct,
   audité, qui ne lit pas les contenus ;
5. les caches, files, index de recherche, journaux, exports, webhooks, sorties de traces et clés de déduplication
   incluent l'espace dans leur clé ou leur filtre ;
6. un jeton délégué d'un espace A ne peut pas viser un `orion_project_id` de l'espace B (échec à l'échange **et** au
   service cible).

Tests d'isolation (spécification, à réaliser dans le ticket de suite 4) : jeu de fixtures à **deux espaces** (A, B), deux
projets chacun, des documents C1 à C3 synthétiques, des utilisateurs de chaque rôle ; exécutables **sans IdP** avec des
jetons signés par une clé de test. Cas obligatoires par service : lecture / liste / recherche / export entre espaces ;
écriture et suppression entre espaces ; identifiant d'un autre espace (404 indiscernable) ; jeton A avec projet B ; clé
d'agent A sur projet B ; cache et recherche (aucune fuite par la clé de cache) ; webhooks et événements ; tâches de
fond ; administrateur d'espace A sur B ; rôle global de plateforme sans lecture de contenu. Un test d'inventaire échoue
quand une nouvelle table ou route n'a pas de filtre d'espace déclaré (liste d'exceptions explicite et revue).

## 10. Tickets de suite à créer (Backlog, non créés par NOV-100)

| # | Ticket proposé | Dépend de | Remarque |
|---|---|---|---|
| 1 | **IdP commun** : realm `orion`, clients `nova-web` / `orbit` / `forge`, mappers de claims (§3), comptes de service, politique MFA ; préprod d'abord | — | prérequis de tous les autres |
| 2 | **OIDC pour FORGE** : relying party (PKCE + validation JWKS), mapping rôles / clearance (§4), liaison `sub` ↔ compte, maintien de `fgk_…` | 1 | demandé par NOV-100 |
| 3 | **OIDC pour ORBIT** : idem pour ORBIT (SSO + MFA par l'IdP), maintien des clés d'agent `orb_…` et du mot de passe en double pile | 1 | demandé par NOV-100 |
| 4 | **Modèle espace / projet dans FORGE** : `orion_workspace_id` / `orion_project_id` sur agents, scénarios, jeux de données, runs, expériences, clés ; migration des données existantes ; rôles par projet | 1 | demandé par NOV-100 ; levier majeur d'isolation |
| 5 | **Entité espace dans ORBIT et NOVA** : `orion_workspace_id` sur utilisateurs et projets, `orion_project_id` aligné avec les projets existants (`ProjectReference`) | 1 | complète le modèle commun |
| 6 | **Tests d'isolation d'espace** (§9) : jeu à deux espaces, test d'inventaire des filtres, dans les trois dépôts, en CI | 4, 5 | demandé par NOV-100 |
| 7 | **Délégation par Token Exchange** NOVA → ORBIT / FORGE (§6), remplacement de la session ORBIT liée, audit `sub` + `act` | 1, 2, 3 | retire l'expiration de session côté utilisateur |
| 8 | **Comptes de service et clés** : rattachement des clés `orb_…` / `fgk_…` à un espace / projet, clearance explicite, rotation, jeton entrant de NOVA en client credentials (§7) | 4, 5 | |
| 9 | **Migration des comptes** (§8) : outil d'inventaire et de rapprochement (dry-run), liaison confirmée, drapeaux de bascule, comptes *break-glass* | 2, 3 | exécution en production après la levée du gel |
| 10 | **Écran de santé des liens fédérés** : champs du §11 dans `GET /me/links` et l'écran NOVA | 7 | étend NOV-93 |
| 11 | **Tests de contrat de claims** : fixtures de jetons (claims du §3) et table §4 testée dans les trois services, sans IdP | 1 | s'appuie sur `docs/CONTRACTS.md` |

## 11. Spécification de l'écran de santé des liens (réalisé côté NOVA dans le ticket dédié)

L'écran existant (`GET /api/v1/me/links`, NOV-93) montre déjà, par lien ORBIT et FORGE : état (`ok`, `degraded`,
`expired`, `fallback`, `agent_key`, `unlinked`, `not_configured`), dernier succès / dernière erreur (statut seulement,
jamais un corps de réponse, une URL avec identifiants ni une clé) et point d'accès public (schéma, hôte, port). Après
ce cadrage il affiche, **par service lié**, sans jamais exposer un jeton ni un secret :

| Élément | Contenu |
|---|---|
| **Identité** | qui agit : `sub` abrégé, e-mail, émetteur (`iss`), méthode (`amr`), et `act` quand NOVA délègue ; mention « clé d'agent » quand l'identité est une clé |
| **Projet cible** | `orion_project_id`, nom, alias local (slug ORBIT / FORGE) et espace (`orion_workspace_id`) |
| **Expiration** | date et durée restante du jeton / de la liaison ; prochain renouvellement ; état « expire bientôt » à seuil configurable |
| **Périmètre** | scopes obtenus, rôle effectif dans le service, habilitation effective (`min` du §4), raison d'un plafonnement |
| **Dernier aller-retour** | horodatage, opération, statut HTTP, latence ; dernière erreur ; compteur d'erreurs consécutives |
| **États** | `ok`, `expire bientôt`, `expiré`, `révoqué` (membre retiré, NOV-81), `dégradé`, `repli sur clé d'agent`, `non lié`, `non configuré` |
| **Actions** | reconnecter, révoquer la délégation, tester le lien (appel de santé sans donnée) |

Contraintes : lecture seule pour tout membre sur ses propres liens ; un administrateur voit l'état des liens de l'espace
sans voir de contenu ; les valeurs affichées proviennent de ce que le service a déjà enregistré (pas d'appel
supplémentaire aux services à l'ouverture de l'écran) ; chaque libellé est traduit comme le reste de l'interface.

## 12. Conséquences

* **Positives** : SSO et MFA uniques, révocation centralisée, plus d'expiration de session ORBIT côté NOVA, base
  d'isolation multi-entreprises vérifiable, audit des délégations (`sub` + `act`).
* **Coûts / risques** : dépendance forte à l'IdP (haute disponibilité, procédure *break-glass*) ; travail structurant
  côté FORGE (aucun modèle espace / projet aujourd'hui) ; migration de données et de comptes à jouer en préproduction ;
  latence de l'échange de jeton (mise en cache du jeton délégué le temps de sa validité, par utilisateur et projet).
* **Hors périmètre de cet ADR** : choix de l'hébergement de l'IdP, politique de mots de passe, facturation par espace,
  consentement utilisateur détaillé, fédération avec les IdP d'entreprise (SAML / OIDC) au-delà de Keycloak.
