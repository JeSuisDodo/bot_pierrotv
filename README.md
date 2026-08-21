# Dodo's Bot — Bot Discord (modération, économie/voitures, Valorant)

Bot Discord modulaire (structure en cogs) : modération automatique, système économique avec voitures à collectionner, statistiques Valorant, notifications YouTube/TikTok/Twitch, et diverses commandes d'infos.

## Sommaire

- [Fonctionnalités](#fonctionnalités)
- [Structure du projet](#structure-du-projet)
- [Installation](#installation)
- [Variables d'environnement](#variables-denvironnement)
- [Commandes disponibles](#commandes-disponibles)
- [Système économie & voitures](#système-économie--voitures)
- [Déploiement sur Render](#déploiement-sur-render-gratuit)
- [Permissions Discord requises](#permissions-discord-requises)
- [Sécurité](#sécurité)
- [Limitations connues](#limitations-connues)

## Fonctionnalités

- **Modération automatique** : kick + suppression des messages récents (5 dernières minutes) de tout utilisateur postant dans un salon interdit (anti-spam / comptes hackés)
- **Économie & voitures** : les membres gagnent de l'argent en étant actifs (messages, vocal) et le dépensent pour acheter des voitures à la concession (`/shop`), les revendre entre eux (`/hdv`) ou constituer leur garage (`/garage`)
- **Valorant** : profil complet d'un joueur avec navigation façon tracker (`/profil`) — rank, peak rank, 5 dernières parties classées cliquables et leur scoreboard (rang actuel + peak par joueur, en image), avec possibilité de sauter au profil de n'importe quel joueur d'une partie —, seuil RR pour être Radiant (`/radiant`), et graphique de progression du MMR basé sur une chaîne de Markov (`/mmr`)
- **Slash commands d'infos** (`/`) avec embeds pour le setup gaming (crosshair, souris, clavier, sensibilité...)
- **Notifications automatiques** : annonce dans des salons dédiés lors d'une nouvelle vidéo YouTube, d'un nouveau TikTok, ou d'un lancement de stream Twitch
- Serveur Flask intégré pour rester actif 24/7 sur Render (via ping UptimeRobot)

## Structure du projet

```
bot/
├── main.py                 # Point d'entrée : lance le bot, charge les cogs, sync les commandes
├── db.py                    # Accès MongoDB (profils membres, annonces du marché)
├── cars.py                  # Catalogue des voitures (clé, nom, prix, image)
├── format.py                 # Utilitaires de formatage (nombres, durées)
├── valorant_api.py            # Client HenrikDev partagé (mmr, matchlist, icônes de rang, calcul ACS/ADR/HS%)
├── requirements.txt         # Dépendances Python
├── .env                     # Variables d'environnement (jamais commit)
├── .env.example              # Modèle de .env
├── .gitignore
└── cogs/
    ├── __init__.py
    ├── moderation.py         # Kick + purge des messages dans le salon interdit
    ├── info.py                # Slash commands d'infos + /commandes
    ├── notifications.py       # Notifications YouTube / TikTok / Twitch
    ├── economy.py             # Gains passifs d'argent (messages, vocal)
    ├── shop.py                 # /shop, /garage, /poche, /infos
    ├── market.py               # /hdv, /vendre, /acheter (hôtel des ventes entre joueurs)
    ├── admin_economy.py        # /give, /takeback, /delete (commandes modérateur)
    ├── guide.py                 # /guide — explique le système économie/voitures
    ├── valorant.py              # /radiant
    ├── profile.py                # /profil — profil, matchs récents et scoreboards navigables
    └── mmr_markov.py            # /mmr — graphique de progression MMR (chaîne de Markov)
```

## Installation

1. **Cloner le projet et installer les dépendances**
   ```bash
   pip install -r requirements.txt
   ```

2. **Créer un fichier `.env`** à la racine (copie de `.env.example`) et le remplir avec tes propres identifiants (voir [Variables d'environnement](#variables-denvironnement))

3. **Lancer le bot**
   ```bash
   python main.py
   ```

## Variables d'environnement

| Variable | Requis pour | Description |
|---|---|---|
| `TOKEN` | Bot (toujours) | Token du bot Discord (Developer Portal → Bot → Token) |
| `DBSTRING` | Économie/voitures | Chaîne de connexion MongoDB Atlas (`cogs/economy.py`, `shop.py`, `market.py`, `admin_economy.py` en dépendent via `db.py`) |
| `HENRIKDEV_API_KEY` | Valorant | Clé API [HenrikDev](https://docs.henrikdev.xyz/) pour `/rank`, `/radiant` et `/mmr` |
| `TWITCH_CLIENT_ID` | Notifications Twitch | Client ID d'une application Twitch |
| `TWITCH_CLIENT_SECRET` | Notifications Twitch | Client secret de cette application |

Récupérer un ID Discord (salon/serveur) : activer le **mode développeur** (Discord → Paramètres → Avancés), puis clic droit → **Copier l'ID**.

Créer les identifiants Twitch : https://dev.twitch.tv/console/apps

> ⚠️ Sans `DBSTRING`, les cogs `economy`, `shop`, `market` et `admin_economy` planteront au chargement (erreur affichée dans les logs au démarrage, le bot continue de tourner avec les autres cogs). Sans `HENRIKDEV_API_KEY`, `/profil` et `/mmr` échoueront et `/radiant` retombera sur le seuil plancher (300 RR).

## Commandes disponibles

### 🛠️ Modération
Automatique, pas de slash command : voir `FORBIDDEN_CHANNEL_ID` et `PURGE_MINUTES` dans `cogs/moderation.py`.

### 🖥️ Setup gaming (`cogs/info.py`)
| Commande | Description |
|---|---|
| `/crosshair` | Crosshair Valorant utilisé |
| `/clavier`, `/keybord` | Clavier utilisé |
| `/souris`, `/mouse` | Souris utilisée |
| `/tapis`, `/mousepad` | Tapis de souris utilisé |
| `/ecran`, `/monitor` | Écran utilisé |
| `/casque`, `/headphone` | Casque utilisé |
| `/sensi`, `/sens`, `/sensibilite` | Sensibilité de souris |
| `/resolution`, `/res` | Résolution de jeu |
| `/kovaak` | Scénarios Kovaak's utilisés à l'entraînement |
| `/commandes` | Résumé de toutes les commandes, organisé par catégorie |

### 🎯 Valorant
| Commande | Description |
|---|---|
| `/profil <pseudo> <région>` | Profil complet d'un joueur : rank actuel, peak rank, et 5 dernières parties classées cliquables (scoreboard image avec rang par joueur, puis navigation vers le profil des autres joueurs de la partie) (`cogs/profile.py`) |
| `/radiant <région>` | Seuil RR actuel pour être Radiant dans une région (`cogs/valorant.py`) |
| `/mmr <pseudo> <région>` | Graphique de progression du MMR, modélisé par une chaîne de Markov d'ordre 2 (`cogs/mmr_markov.py`) — limité à **1 utilisation par semaine et par membre** |

### 🚗 Économie & voitures
| Commande | Description |
|---|---|
| `/guide` | Explique tout le système d'argent et de voitures du serveur |
| `/poche` | Affiche l'argent disponible du membre |
| `/shop` | Ouvre la concession pour acheter une voiture neuve |
| `/garage [membre]` | Affiche l'inventaire de voitures (le sien ou celui d'un autre membre) |
| `/infos` | Statistiques complètes : argent, messages envoyés, temps en vocal, nombre de voitures |
| `/hdv` | Consulte les annonces actives de l'hôtel des ventes |
| `/vendre <voiture> <prix>` | Met une de ses voitures en vente sur l'hôtel des ventes |
| `/acheter <id_annonce>` | Achète une voiture mise en vente par un autre joueur |

### 🔧 Administration (modérateur, `cogs/admin_economy.py`)
| Commande | Description |
|---|---|
| `/give <membre> <montant>` | Donne de l'argent à un membre |
| `/takeback <membre> <montant>` | Reprend de l'argent à un membre |
| `/delete <membre> <voiture>` | Supprime une voiture de l'inventaire d'un membre |

Réservées à `manage_guild` ou au rôle défini par `MOD_ROLE_ID` dans `cogs/admin_economy.py`.

## Système économie & voitures

- **Gains d'argent** (`cogs/economy.py`) : 5 $ par message (cooldown de 60s anti-spam), 10 $ par minute passée en vocal
- **Catalogue des voitures** (`cars.py`) : dictionnaire de clés → `{name, price, image}`, modifiable directement dans le fichier
- **Persistance** (`db.py`) : MongoDB Atlas, base `discord`
  - collection `members` : profil économique de chaque membre (`id`, `name`, `money`, `messages`, `voicetime`, `cars`)
  - collection `market` : annonces actives de l'hôtel des ventes (`seller_id`, `car_key`, `price`)
- Les profils membres sont créés automatiquement à la première interaction (aucune init manuelle nécessaire)

## Déploiement sur Render (gratuit)

1. Push le projet sur un repo **GitHub privé** (le `.gitignore` protège déjà `.env`)
2. Sur [Render](https://render.com) : **New → Web Service** → connecter le repo
   - Build command : `pip install -r requirements.txt`
   - Start command : `python main.py`
3. Ajouter toutes les [variables d'environnement](#variables-denvironnement) nécessaires dans l'onglet **Environment** de Render
4. Créer un moniteur sur [UptimeRobot](https://uptimerobot.com) (gratuit) qui ping l'URL Render toutes les 5 minutes, pour éviter la mise en veille du service gratuit

## Permissions Discord requises

Lors de l'invitation du bot (OAuth2 → URL Generator), cocher :
- `bot` (scope)
- `applications.commands` (pour les slash commands)
- Permissions : **Expulser des membres**, **Gérer les messages**, **Envoyer des messages**, **Lire l'historique des messages**

## Sécurité

- Ne **jamais** commit le token Discord, la chaîne MongoDB ou les secrets Twitch/HenrikDev dans le code ou sur GitHub, même en repo privé
- En cas de fuite du token, le régénérer immédiatement : Developer Portal → Bot → **Reset Token**
- `.env` doit toujours rester dans `.gitignore`

## Limitations connues

- **TikTok** : pas d'API officielle publique, la détection utilise du scraping léger — peut casser si TikTok modifie sa structure de page, ou être bloqué sur certains comptes
- **Sync des slash commands** : `main.py` synchronise directement sur la guild définie par `GUILD_ID` (variable codée en dur, à adapter à ton serveur) pour une mise à jour quasi instantanée
- **`/mmr`** : le MMR réel n'étant pas publié par Riot, la courbe simulée est une approximation statistique (chaîne de Markov d'ordre 2) et non la vraie formule ; la commande est volontairement limitée à 1 utilisation/semaine/membre car le calcul est lourd (appels API + simulation)
- **Render free tier** : le service peut redémarrer occasionnellement, ce qui coupe temporairement le bot
