import time
import discord
from discord.ext import commands, tasks

import db

# === CONFIGURATION ===
MESSAGE_REWARD = 5          # $ gagnés par message
MESSAGE_COOLDOWN = 60       # secondes entre deux messages récompensés (anti-spam)
VOICE_REWARD_PER_MINUTE = 10  # $ gagnés par minute passée en vocal
IGNORED_VOICE_CHANNEL_IDS = []  # ex: salon AFK à exclure des gains


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_message_reward = {}  # {user_id: timestamp}
        self.check_voice.start()

    def cog_unload(self):
        self.check_voice.cancel()

    # ---------- GAINS PAR MESSAGE ----------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return

        now = time.time()
        last = self.last_message_reward.get(message.author.id, 0)
        if now - last < MESSAGE_COOLDOWN:
            return

        self.last_message_reward[message.author.id] = now
        db.add_money(message.author, MESSAGE_REWARD)
        db.add_message_count(message.author, 1)

    # ---------- GAINS VOCAL ----------
    @tasks.loop(minutes=1)
    async def check_voice(self):
        for guild in self.bot.guilds:
            for voice_channel in guild.voice_channels:
                if voice_channel.id in IGNORED_VOICE_CHANNEL_IDS:
                    continue

                for member in voice_channel.members:
                    if member.bot:
                        continue

                    db.add_money(member, VOICE_REWARD_PER_MINUTE)
                    db.add_voicetime(member, 60)

    @check_voice.before_loop
    async def before_check_voice(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
