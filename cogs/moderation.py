import discord
from discord.ext import commands
from datetime import datetime, timedelta, timezone
 
FORBIDDEN_CHANNEL_ID = 1522553435239616524  # ID du salon ou personne ne doit parler
PURGE_MINUTES = 5  # fenêtre de suppression des messages de l'utilisateur
 
class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
 
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
 
        if message.channel.id == FORBIDDEN_CHANNEL_ID:
            member = message.author
            guild = message.guild
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=PURGE_MINUTES)
 
            try:
                await message.delete()
            except discord.Forbidden:
                pass
 
            try:
                await guild.kick(member, reason="Message dans salon interdit (anti-spam/hack)")
            except discord.Forbidden:
                pass  # permissions insuffisantes
 
            # Purge des messages récents de l'utilisateur dans tous les salons texte
            for channel in guild.text_channels:
                try:
 
                    def is_target(m: discord.Message) -> bool:
                        return m.author.id == member.id and m.created_at >= cutoff
 
                    await channel.purge(after=cutoff, check=is_target, bulk=True)
                except discord.Forbidden:
                    pass  # pas de permission sur ce salon
                except discord.HTTPException:
                    pass  # messages trop vieux (>14j) pour un purge en masse


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
