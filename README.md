# Dodo's Bot — Bot de modération et notifications Discord

Bot Discord modulaire (structure en cogs) pour la modération automatique, l'affichage d'infos via slash commands, et les notifications YouTube/TikTok/Twitch.

## Fonctionnalités

- **Modération automatique** : kick + suppression des messages récents (5 dernières minutes) de tout utilisateur postant dans un salon interdit (anti-spam / comptes hackés)
- **Slash commands** (`/`) avec embeds pour afficher des infos (setup, sensibilité, etc.)
- **Notifications automatiques** : annonce dans des salons dédiés lors d'une nouvelle vidéo YouTube, d'un nouveau TikTok, ou d'un lancement de stream Twitch
- Serveur Flask intégré pour rester actif 24/7 sur Render (via ping UptimeRobot)

## Structure du projet

```
bot_discord/
├── main.py                 # Point d'entrée : lance le bot, charge les cogs, sync les commandes
├── requirements.txt        # Dépendances Python
├── .env                    # Variables d'environnement (jamais commit)
├── .env.example             # Modèle de .env
├── .gitignore
└── cogs/
    ├── __init__.py
    ├── moderation.py        # Kick + purge des messages dans le salon interdit
    ├── info.py               # Slash commands + embeds
    └── notifications.py      # Notifications YouTube / TikTok / Twitch
```

## Installation

1. **Cloner le projet et installer les dépendances**
   ```bash
   pip install -r requirements.txt
   ```

2. **Créer un fichier `.env`** à la racine (copie de `.env.example`) et le remplir :
   ```
   TOKEN=ton_token_discord
   TWITCH_CLIENT_ID=ton_client_id_twitch
   TWITCH_CLIENT_SECRET=ton_client_secret_twitch
   ```

3. **Lancer le bot**
   ```bash
   python main.py
   ```

## Configuration

### Modération (`cogs/moderation.py`)
| Variable | Description |
|---|---|
| `FORBIDDEN_CHANNEL_ID` | ID du salon où personne ne doit écrire (kick + purge automatique) |
| `PURGE_MINUTES` | Fenêtre de suppression des messages de l'utilisateur (par défaut 5 min) |

### Notifications (`cogs/notifications.py`)
| Variable | Description |
|---|---|
| `YOUTUBE_CHANNEL_ID` | ID de la chaîne YouTube à surveiller |
| `YOUTUBE_DISCORD_CHANNEL_ID` | Salon Discord où poster l'annonce vidéo |
| `TIKTOK_USERNAME` | Pseudo TikTok (sans @) |
| `TIKTOK_DISCORD_CHANNEL_ID` | Salon Discord où poster l'annonce TikTok |
| `TWITCH_USERNAME` | Pseudo Twitch |
| `TWITCH_DISCORD_CHANNEL_ID` | Salon Discord où poster l'annonce de live |

Récupérer un ID Discord (salon/serveur) : activer le **mode développeur** (Discord → Paramètres → Avancés), puis clic droit → **Copier l'ID**.

Créer les identifiants Twitch : https://dev.twitch.tv/console/apps

### Commandes info (`cogs/info.py`)
Toutes les réponses sont centralisées dans le dictionnaire `INFO_DATA`. Pour modifier un texte ou ajouter une image :
```python
"souris": {
    "title": "Souris",
    "description": "Ton texte ici",
    "image": "https://lien-vers-image.png",  # ou None
},
```

## Déploiement sur Render (gratuit)

1. Push le projet sur un repo **GitHub privé** (le `.gitignore` protège déjà `.env`)
2. Sur [Render](https://render.com) : **New → Web Service** → connecter le repo
   - Build command : `pip install -r requirements.txt`
   - Start command : `python main.py`
3. Ajouter les variables d'environnement (`TOKEN`, `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`) dans l'onglet **Environment** de Render
4. Créer un moniteur sur [UptimeRobot](https://uptimerobot.com) (gratuit) qui ping l'URL Render toutes les 5 minutes, pour éviter la mise en veille du service gratuit

## Permissions Discord requises

Lors de l'invitation du bot (OAuth2 → URL Generator), cocher :
- `bot` (scope)
- `applications.commands` (pour les slash commands)
- Permissions : **Expulser des membres**, **Gérer les messages**, **Envoyer des messages**, **Lire l'historique des messages**

## Sécurité

- Ne **jamais** commit le token Discord ou les secrets Twitch dans le code ou sur GitHub, même en repo privé
- En cas de fuite du token, le régénérer immédiatement : Developer Portal → Bot → **Reset Token**
- `.env` doit toujours rester dans `.gitignore`

## Limitations connues

- **TikTok** : pas d'API officielle publique, la détection utilise du scraping léger — peut casser si TikTok modifie sa structure de page, ou être bloqué sur certains comptes
- **Sync des slash commands** : la synchronisation globale peut prendre jusqu'à 1h pour apparaître ; utiliser `bot.tree.copy_global_to(guild=...)` + `sync(guild=...)` pour un test instantané sur un serveur précis
- **Render free tier** : le service peut redémarrer occasionnellement, ce qui coupe temporairement le bot
