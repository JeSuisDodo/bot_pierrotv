import os
import discord
from discord import app_commands
from discord.ext import commands
import aiohttp

HENRIKDEV_API_KEY = os.getenv("HENRIKDEV_API_KEY")

REGIONS = [
    app_commands.Choice(name="Europe", value="eu"),
    app_commands.Choice(name="Amérique du Nord", value="na"),
    app_commands.Choice(name="Asie-Pacifique", value="ap"),
    app_commands.Choice(name="Corée", value="kr"),
    app_commands.Choice(name="Amérique Latine", value="latam"),
    app_commands.Choice(name="Brésil", value="br"),
]

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


class Valorant(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="rank", description="Affiche le rank Valorant actuel d'un joueur")
    @app_commands.describe(
        pseudo="Riot ID complet, format Pseudo#Tag (ex: Dodo#1234)",
        region="Région du compte",
    )
    @app_commands.choices(region=REGIONS)
    async def rank(self, interaction: discord.Interaction, pseudo: str, region: app_commands.Choice[str]):
        if "#" not in pseudo:
            await interaction.response.send_message(
                "Format invalide. Utilise `Pseudo#Tag` (ex: `Dodo#1234`).",
                ephemeral=True,
            )
            return

        name, tag = pseudo.split("#", 1)

        try:
            await interaction.response.defer()
        except (discord.HTTPException, ConnectionError, OSError):
            return

        url = f"https://api.henrikdev.xyz/valorant/v3/mmr/{region.value}/pc/{name}/{tag}"
        headers = {"Authorization": HENRIKDEV_API_KEY} if HENRIKDEV_API_KEY else {}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 404:
                        await interaction.followup.send("Joueur introuvable. Vérifie le pseudo, le tag et la région.")
                        return
                    if resp.status != 200:
                        await interaction.followup.send(f"Erreur de l'API Valorant (code {resp.status}).")
                        return

                    data = await resp.json()

                current = data.get("data", {}).get("current", {})
                if not current:
                    await interaction.followup.send("Aucune donnée de rank disponible pour ce joueur.")
                    return

                tier = current.get("tier", {})
                rank_name = tier.get("name", "Non classé")
                rr = current.get("rr", 0)
                elo = current.get("elo", "N/A")

                icons = await get_tier_icons(session)
                rank_icon = icons.get(tier.get("id"))
        except Exception as e:
            await interaction.followup.send(f"Erreur lors de la récupération du rank : {e}")
            return

        embed = discord.Embed(
            title=f"🎯 Rank Valorant de {name}#{tag}",
            description=f"**{rank_name}** — {rr} RR",
            color=discord.Color.red(),
        )
        embed.add_field(name="Elo", value=str(elo), inline=True)
        embed.add_field(name="Région", value=region.name, inline=True)
        if rank_icon:
            embed.set_thumbnail(url=rank_icon)

        try:
            await interaction.followup.send(embed=embed)
        except (discord.HTTPException, ConnectionError, OSError):
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Valorant(bot))