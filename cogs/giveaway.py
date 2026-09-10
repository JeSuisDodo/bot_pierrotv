import asyncio
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import db

# Seul salon où les entrées "!giveway" sont acceptées
GIVEAWAY_CHANNEL_ID = 1547704236001726505
ENTRY_KEYWORD = "!giveway"

# ID du rôle modérateur autorisé (même logique que cogs/admin_economy.py)
MOD_ROLE_ID = None


def is_mod():
    """Vérifie que l'utilisateur a le rôle modérateur (ou la permission Gérer le serveur)"""

    def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.manage_guild:
            return True
        if MOD_ROLE_ID and any(role.id == MOD_ROLE_ID for role in interaction.user.roles):
            return True
        return False

    return app_commands.check(predicate)


# Durée façon "1j12h30m" (jours/heures/minutes/secondes, combinables), même
# convention que l'affichage de cooldown dans cogs/mmr_markov.py.
_DURATION_PATTERN = re.compile(r"(\d+)\s*(j|h|m|s)", re.IGNORECASE)
_DURATION_UNIT_SECONDS = {"j": 86400, "h": 3600, "m": 60, "s": 1}


def parse_duration(text: str) -> Optional[timedelta]:
    """Parse une durée du type '1j12h30m'. Renvoie None si aucune unité valide
    n'est reconnue ou si la durée totale est nulle/négative."""
    matches = _DURATION_PATTERN.findall(text.strip())
    if not matches:
        return None
    total_seconds = sum(int(value) * _DURATION_UNIT_SECONDS[unit.lower()] for value, unit in matches)
    if total_seconds <= 0:
        return None
    return timedelta(seconds=total_seconds)


class Giveaway(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_giveaways.start()

    def cog_unload(self):
        self.check_giveaways.cancel()

    @staticmethod
    def _build_announcement_embed(component: str, winner_count: int, ends_at: datetime) -> discord.Embed:
        embed = discord.Embed(
            title="🎉 Giveaway !",
            description=(
                f"**À gagner : {component}**\n\n"
                f"Tape `{ENTRY_KEYWORD}` dans ce salon pour participer !\n"
                f"Fin <t:{int(ends_at.timestamp())}:R>"
            ),
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="⚠️ Attention",
            value=f"Ce salon est réservé aux participations : tout message différent de `{ENTRY_KEYWORD}` sera automatiquement supprimé.",
            inline=False,
        )
        embed.set_footer(text=f"{winner_count} gagnant(s)")
        return embed

    @app_commands.command(name="giveaway", description="[Modo] Lance un giveaway dans le salon dédié")
    @app_commands.describe(
        composant="Le composant à gagner (ex: RTX 4070, 16 Go RAM Corsair...)",
        duree="Durée du giveaway (ex: 1j, 12h, 30m, combinable comme 1j12h)",
        gagnants="Nombre de gagnants (1 par défaut)",
    )
    @is_mod()
    async def giveaway(self, interaction: discord.Interaction, composant: str, duree: str, gagnants: int = 1):
        if gagnants < 1:
            await interaction.response.send_message("Le nombre de gagnants doit être d'au moins 1.", ephemeral=True)
            return

        delta = parse_duration(duree)
        if delta is None:
            await interaction.response.send_message(
                "Durée invalide. Utilise un format comme `1j`, `12h`, `30m` "
                "(jours/heures/minutes/secondes, combinables : `1j12h`).",
                ephemeral=True,
            )
            return

        channel = self.bot.get_channel(GIVEAWAY_CHANNEL_ID)
        if channel is None:
            await interaction.response.send_message("Salon de giveaway introuvable.", ephemeral=True)
            return

        existing = await asyncio.to_thread(db.get_active_giveaway, GIVEAWAY_CHANNEL_ID)
        if existing:
            await interaction.response.send_message(
                "Un giveaway est déjà en cours dans ce salon. Termine-le avec `/giveaway_end` avant d'en lancer un nouveau.",
                ephemeral=True,
            )
            return

        ends_at = datetime.now(timezone.utc) + delta
        giveaway_id = await asyncio.to_thread(
            db.create_giveaway, composant, gagnants, GIVEAWAY_CHANNEL_ID, interaction.user.id, ends_at
        )

        message = await channel.send(embed=self._build_announcement_embed(composant, gagnants, ends_at))
        await asyncio.to_thread(db.set_giveaway_message, giveaway_id, message.id)

        await interaction.response.send_message(f"Giveaway lancé dans {channel.mention} !", ephemeral=True)

    @app_commands.command(name="giveaway_end", description="[Modo] Termine immédiatement le giveaway en cours")
    @is_mod()
    async def giveaway_end(self, interaction: discord.Interaction):
        giveaway = await asyncio.to_thread(db.get_active_giveaway, GIVEAWAY_CHANNEL_ID)
        if giveaway is None:
            await interaction.response.send_message("Aucun giveaway en cours.", ephemeral=True)
            return

        await interaction.response.send_message("Giveaway terminé.", ephemeral=True)
        await self._draw_winners(giveaway)

    async def _draw_winners(self, giveaway: dict) -> None:
        participants = giveaway.get("participants", [])
        winner_count = giveaway.get("winner_count", 1)
        winners = random.sample(participants, min(winner_count, len(participants))) if participants else []

        await asyncio.to_thread(db.end_giveaway, giveaway["_id"], winners)

        channel = self.bot.get_channel(giveaway["channel_id"])
        if channel is None:
            return

        if not winners:
            await channel.send(f"🎉 Le giveaway pour **{giveaway['component']}** est terminé, mais personne n'a participé.")
            return

        mentions = ", ".join(f"<@{uid}>" for uid in winners)
        await channel.send(f"🎉 Le giveaway pour **{giveaway['component']}** est terminé ! Félicitations {mentions} !")

        for uid in winners:
            try:
                user = self.bot.get_user(uid) or await self.bot.fetch_user(uid)
                await user.send(f"🎉 Félicitations, tu as gagné **{giveaway['component']}** !")
            except discord.HTTPException:
                pass

    @tasks.loop(seconds=30)
    async def check_giveaways(self):
        now = datetime.now(timezone.utc)
        expired = await asyncio.to_thread(db.get_expired_giveaways, now)
        for giveaway in expired:
            await self._draw_winners(giveaway)

    @check_giveaways.before_loop
    async def before_check_giveaways(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.channel.id != GIVEAWAY_CHANNEL_ID:
            return

        is_entry = message.content.strip().lower() == ENTRY_KEYWORD

        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass

        if not is_entry:
            # Salon réservé aux participations : tout le reste est supprimé (voir
            # l'avertissement dans l'annonce), sans DM ni traitement supplémentaire.
            return

        giveaway = await asyncio.to_thread(db.get_active_giveaway, GIVEAWAY_CHANNEL_ID)
        if giveaway is None:
            try:
                await message.author.send("Il n'y a aucun giveaway en cours actuellement.")
            except discord.HTTPException:
                pass
            return

        added = await asyncio.to_thread(db.add_giveaway_participant, giveaway["_id"], message.author.id)
        try:
            if added:
                await message.author.send(f"✅ Tu participes maintenant au giveaway pour **{giveaway['component']}** !")
            else:
                await message.author.send(f"Tu participes déjà au giveaway pour **{giveaway['component']}**.")
        except discord.HTTPException:
            pass

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message(
                "Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
            )
        else:
            raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaway(bot))
