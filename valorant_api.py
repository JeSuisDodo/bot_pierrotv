import os
import re

import aiohttp
from discord import app_commands

HENRIKDEV_API_KEY = os.getenv("HENRIKDEV_API_KEY")

REGIONS = [
    app_commands.Choice(name="Europe", value="eu"),
    app_commands.Choice(name="Amérique du Nord", value="na"),
    app_commands.Choice(name="Asie-Pacifique", value="ap"),
    app_commands.Choice(name="Corée", value="kr"),
    app_commands.Choice(name="Amérique Latine", value="latam"),
    app_commands.Choice(name="Brésil", value="br"),
]


def format_peak_season(season_short: str) -> str:
    """Convertit un code de saison HenrikDev ('e6a3') en texte lisible ('Épisode 6 Acte 3')."""
    match = re.fullmatch(r"e(\d+)a(\d+)", season_short or "")
    if not match:
        return season_short or "saison inconnue"
    episode, act = match.groups()
    return f"Épisode {episode} Acte {act}"


# Cache en mémoire des icônes de rang (tier id -> URL), rafraîchi une seule
# fois par démarrage du bot : la v3 de HenrikDev ne fournit plus d'images,
# on les récupère sur l'API officielle valorant-api.com (pas de clé requise).
_tier_icons_cache: dict[int, str] = {}


async def get_tier_icons(session: aiohttp.ClientSession) -> dict[int, str]:
    global _tier_icons_cache
    if _tier_icons_cache:
        return _tier_icons_cache

    try:
        async with session.get("https://valorant-api.com/v1/competitivetiers") as resp:
            if resp.status != 200:
                return {}
            payload = await resp.json()
    except Exception:
        return {}

    seasons = payload.get("data", [])
    if not seasons:
        return {}

    tiers = seasons[-1].get("tiers", [])  # dernière saison = paliers actuels
    _tier_icons_cache = {
        t["tier"]: t["largeIcon"] for t in tiers if t.get("largeIcon")
    }
    return _tier_icons_cache


def _headers() -> dict:
    return {"Authorization": HENRIKDEV_API_KEY} if HENRIKDEV_API_KEY else {}


# Cache mémoire des icônes déjà téléchargées (URL -> bytes PNG). Beaucoup de
# joueurs d'un même match partagent le même rang, donc le même icône.
_icon_bytes_cache: dict[str, bytes] = {}


async def fetch_image_bytes(session: aiohttp.ClientSession, url: str) -> bytes | None:
    """Télécharge une image (icône de rang) et la met en cache par URL. Renvoie
    None en cas d'échec plutôt que de lever une exception (image non bloquante)."""
    if not url:
        return None
    if url in _icon_bytes_cache:
        return _icon_bytes_cache[url]
    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            data = await resp.read()
    except Exception:
        return None
    _icon_bytes_cache[url] = data
    return data


async def fetch_mmr(session: aiohttp.ClientSession, name: str, tag: str, region: str) -> dict:
    """Appelle v3/mmr (current + peak). Renvoie le payload JSON brut, ou lève une exception
    (aiohttp.ClientResponseError) en cas de statut HTTP d'erreur, à charge de l'appelant."""
    url = f"https://api.henrikdev.xyz/valorant/v3/mmr/{region}/pc/{name}/{tag}"
    async with session.get(url, headers=_headers()) as resp:
        resp.raise_for_status()
        return await resp.json()


async def fetch_matchlist(
    session: aiohttp.ClientSession, name: str, tag: str, region: str, size: int = 5, mode: str | None = "competitive"
) -> list:
    """Appelle v4/matches (matchlist enrichie : chaque match contient déjà les stats complètes
    de tous les joueurs, pas besoin d'appeler l'endpoint match détaillé). Filtre les matchs
    non terminés. `mode` filtre par mode de jeu côté API (ex: "competitive" pour les parties
    classées) ; passer None pour ne pas filtrer. Renvoie une liste vide si l'appel échoue
    (compte neuf, région invalide, etc.)."""
    url = f"https://api.henrikdev.xyz/valorant/v4/matches/{region}/pc/{name}/{tag}?size={size}"
    if mode:
        url += f"&mode={mode}"
    try:
        async with session.get(url, headers=_headers()) as resp:
            if resp.status != 200:
                return []
            payload = await resp.json()
    except Exception:
        return []

    matches = payload.get("data", [])
    return [m for m in matches if m.get("metadata", {}).get("is_completed", True)]


def compute_player_match_stats(player: dict, rounds_played: int) -> dict:
    """Calcule ACS/ADR/HS% à partir des stats brutes d'un joueur pour un match
    (l'API ne fournit pas ces valeurs directement)."""
    stats = player.get("stats", {})
    kills = stats.get("kills", 0)
    deaths = stats.get("deaths", 0)
    assists = stats.get("assists", 0)
    score = stats.get("score", 0)
    damage_dealt = stats.get("damage", {}).get("dealt", 0)
    headshots = stats.get("headshots", 0)
    bodyshots = stats.get("bodyshots", 0)
    legshots = stats.get("legshots", 0)

    acs = score / rounds_played if rounds_played else 0
    adr = damage_dealt / rounds_played if rounds_played else 0
    total_shots = headshots + bodyshots + legshots
    hs_percent = (headshots / total_shots * 100) if total_shots else 0

    return {
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "acs": acs,
        "adr": adr,
        "hs_percent": hs_percent,
    }
