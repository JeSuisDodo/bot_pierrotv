import discord
from discord import app_commands
from discord.ext import commands
import aiohttp

from valorant_api import HENRIKDEV_API_KEY, REGIONS


class Valorant(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="radiant", description="Affiche le seuil RR actuel pour être Radiant dans une région")
    @app_commands.describe(region="Région à consulter")
    @app_commands.choices(region=REGIONS)
    async def radiant(self, interaction: discord.Interaction, region: app_commands.Choice[str]):
        try:
            await interaction.response.defer()
        except (discord.HTTPException, ConnectionError, OSError):
            return

        url = f"https://api.henrikdev.xyz/valorant/v3/leaderboard/{region.value}/pc?start_index=1&size=500"
        headers = {"Authorization": HENRIKDEV_API_KEY} if HENRIKDEV_API_KEY else {}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        await interaction.followup.send(f"Erreur de l'API Valorant (code {resp.status}).")
                        return
                    payload = await resp.json()
        except Exception as e:
            await interaction.followup.send(f"Erreur lors de la récupération du classement : {e}")
            return

        data = payload.get("data", {})
        players = data.get("players", [])

        # Le nombre de joueurs Radiant n'est pas toujours exactement 500 (ça dépend
        # de la région/saison), donc se baser sur le RR du 500e joueur est peu fiable.
        # L'API renvoie directement le vrai seuil calculé par Riot dans "thresholds".
        radiant_threshold = next(
            (t for t in data.get("thresholds", []) if t.get("tier", {}).get("name") == "Radiant"),
            None,
        )

        if radiant_threshold is not None:
            threshold_rr = radiant_threshold.get("threshold", 300)
            description = (
                f"Le seuil actuel pour être Radiant en **{region.name}** est de **{threshold_rr} RR**.\n"
                f"C'est le seuil officiel calculé par Riot, renvoyé directement par l'API."
            )
        elif len(players) >= 500:
            player_500 = players[499]
            threshold_rr = player_500.get("rr", 300)
            player_name = player_500.get("name", "?")
            player_tag = player_500.get("tag", "?")
            description = (
                f"Le seuil actuel pour être Radiant en **{region.name}** est estimé à **{threshold_rr} RR**.\n"
                f"L'API n'a pas renvoyé de seuil officiel : estimation basée sur le RR du 500e joueur "
                f"du classement (`{player_name}#{player_tag}`)."
            )
        else:
            threshold_rr = 300
            description = (
                f"Moins de 500 joueurs classés au-delà d'Immortel en **{region.name}**, et l'API n'a "
                f"pas renvoyé de seuil officiel.\nLe seuil Radiant retombe donc sur le plancher "
                f"théorique : **{threshold_rr} RR**."
            )

        embed = discord.Embed(
            title="🏆 Seuil Radiant",
            description=description,
            color=discord.Color.red(),
        )
        embed.set_footer(text="Ce seuil bouge en continu avec l'activité du classement.")

        try:
            await interaction.followup.send(embed=embed)
        except (discord.HTTPException, ConnectionError, OSError):
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Valorant(bot))
