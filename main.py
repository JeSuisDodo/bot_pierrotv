import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from flask import Flask
from threading import Thread
 
load_dotenv()
TOKEN = os.getenv("TOKEN")
 
# Serveur Flask pour garder le bot éveillé sur Render (via UptimeRobot)
app = Flask('')
 
@app.route('/')
def home():
    return "Bot en ligne"
 
def run():
    app.run(host='0.0.0.0', port=8080)
 
Thread(target=run).start()
 
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # nécessaire pour le ban
 
bot = commands.Bot(command_prefix="$", intents=intents)
 
EXTENSIONS = [
    "cogs.moderation",
    "cogs.info",
    "cogs.notifications",
    "cogs.economy",
    "cogs.shop",
    "cogs.market",
    "cogs.admin_economy",
    "cogs.valorant",
    "cogs.guide",
]
 
 
@bot.event
async def on_ready():
    for ext in EXTENSIONS:
        try:
            await bot.load_extension(ext)
        except Exception as e:
            print(f"Erreur lors du chargement de {ext} : {e}")
 
    synced = await bot.tree.sync()
    print(f"{len(synced)} commandes slash synchronisées.")
    print(f"Connecté en tant que {bot.user}")
 
bot.run(TOKEN)