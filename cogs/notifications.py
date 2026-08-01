import os
import discord
from discord.ext import commands, tasks
import aiohttp
import xml.etree.ElementTree as ET

# === CONFIGURATION ===
YOUTUBE_CHANNEL_ID = "UCuRpAIsm-4rksDB9EGwK4WA"          # ID de la chaîne YouTube
YOUTUBE_DISCORD_CHANNEL_ID = 1090383298615853187       # Salon Discord pour l'annonce YouTube

TIKTOK_USERNAME = "pierrotv_"                     # Sans le @
TIKTOK_DISCORD_CHANNEL_ID = 1090383298615853187        # Salon Discord pour l'annonce TikTok

TWITCH_USERNAME = "pierrotv_"
TWITCH_DISCORD_CHANNEL_ID = 1090383298615853187       # Salon Discord pour l'annonce Twitch

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")


class Notifications(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_video_id = None
        self.last_tiktok_id = None
        self.was_live = False
        self.twitch_token = None

        self.check_youtube.start()
        self.check_tiktok.start()
        self.check_twitch.start()

    def cog_unload(self):
        self.check_youtube.cancel()
        self.check_tiktok.cancel()
        self.check_twitch.cancel()

    # ---------- YOUTUBE ----------
    @tasks.loop(minutes=1)
    async def check_youtube(self):
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return
                    data = await resp.text()

            root = ET.fromstring(data)
            ns = {
                "atom": "http://www.w3.org/2005/Atom",
                "yt": "http://www.youtube.com/xml/schemas/2015",
            }
            entry = root.find("atom:entry", ns)
            if entry is None:
                return

            video_id = entry.find("yt:videoId", ns).text
            title = entry.find("atom:title", ns).text
            link = f"https://www.youtube.com/watch?v={video_id}"

            if self.last_video_id is None:
                self.last_video_id = video_id  # évite un spam au premier lancement
                return

            if video_id != self.last_video_id:
                self.last_video_id = video_id
                channel = self.bot.get_channel(YOUTUBE_DISCORD_CHANNEL_ID)
                if channel:
                    await channel.send(f"📺 Nouvelle vidéo YouTube : **{title}**\n{link}")
        except Exception as e:
            print(f"[YouTube] Erreur : {e}")

    @check_youtube.before_loop
    async def before_youtube(self):
        await self.bot.wait_until_ready()

    # ---------- TIKTOK ----------
    @tasks.loop(minutes=1)
    async def check_tiktok(self):
        url = f"https://www.tiktok.com/@{TIKTOK_USERNAME}"
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        return
                    html = await resp.text()

            # Recherche grossière du premier lien vidéo dans la page
            marker = f"/@{TIKTOK_USERNAME}/video/"
            idx = html.find(marker)
            if idx == -1:
                return

            start = idx + len(marker)
            end = html.find('"', start)
            video_id = html[start:end]

            if self.last_tiktok_id is None:
                self.last_tiktok_id = video_id  # évite un spam au premier lancement
                return

            if video_id != self.last_tiktok_id:
                self.last_tiktok_id = video_id
                link = f"https://www.tiktok.com/@{TIKTOK_USERNAME}/video/{video_id}"
                channel = self.bot.get_channel(TIKTOK_DISCORD_CHANNEL_ID)
                if channel:
                    await channel.send(f"🎵 Nouveau TikTok publié !\n{link}")
        except Exception as e:
            print(f"[TikTok] Erreur : {e}")

    @check_tiktok.before_loop
    async def before_tiktok(self):
        await self.bot.wait_until_ready()

    # ---------- TWITCH ----------
    async def get_twitch_token(self):
        url = "https://id.twitch.tv/oauth2/token"
        params = {
            "client_id": TWITCH_CLIENT_ID,
            "client_secret": TWITCH_CLIENT_SECRET,
            "grant_type": "client_credentials",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, params=params) as resp:
                data = await resp.json()
                return data.get("access_token")

    @tasks.loop(minutes=1)
    async def check_twitch(self):
        if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
            return

        try:
            if not self.twitch_token:
                self.twitch_token = await self.get_twitch_token()

            headers = {
                "Client-ID": TWITCH_CLIENT_ID,
                "Authorization": f"Bearer {self.twitch_token}",
            }
            url = f"https://api.twitch.tv/helix/streams?user_login={TWITCH_USERNAME}"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 401:
                        self.twitch_token = await self.get_twitch_token()
                        return
                    data = await resp.json()

            is_live = len(data.get("data", [])) > 0

            if is_live and not self.was_live:
                stream = data["data"][0]
                title = stream.get("title", "Stream en cours")
                link = f"https://www.twitch.tv/{TWITCH_USERNAME}"
                channel = self.bot.get_channel(TWITCH_DISCORD_CHANNEL_ID)
                if channel:
                    await channel.send(f"🔴 En live sur Twitch : **{title}**\n{link}")

            self.was_live = is_live
        except Exception as e:
            print(f"[Twitch] Erreur : {e}")

    @check_twitch.before_loop
    async def before_twitch(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Notifications(bot))
