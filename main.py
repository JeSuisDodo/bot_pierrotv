import os
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

load_dotenv()
TOKEN = os.getenv("TOKEN")

# Salons où les commandes slash sont interdites
RESTRICTED_CHANNEL_IDS = {
    834429780916830283,   # discussion
    1335703030624030720,  # clip-réact
    1132759889089925200,  # clips
    1528031041267171398,  # trouver-un-mate
    1217967810177662986,  # médias
}


class RestrictedCommandTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.channel_id in RESTRICTED_CHANNEL_IDS:
            await interaction.response.send_message(
                "❌ Les commandes ne sont pas autorisées dans ce salon.",
                ephemeral=True,
            )
            return False
        return True
 
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
 
bot = commands.Bot(command_prefix="$", intents=intents, tree_cls=RestrictedCommandTree)
 
EXTENSIONS = [
    "cogs.moderation",
    "cogs.info",
    "cogs.notifications",
    "cogs.economy",
    "cogs.shop",
    "cogs.market",
    "cogs.admin_economy",
    "cogs.valorant",
    "cogs.profile",
    "cogs.guide",
    "cogs.mmr_markov"
]
 
GUILD_ID = discord.Object(id=834429780916830280)  # ton ID de serveur, comme avant

@bot.event
async def on_ready():
    for ext in EXTENSIONS:
        try:
            await bot.load_extension(ext)
        except Exception as e:
            print(f"Erreur lors du chargement de {ext} : {e}")

    # 1. Copier les commandes vers la guild AVANT de toucher au global
    bot.tree.copy_global_to(guild=GUILD_ID)
    synced = await bot.tree.sync(guild=GUILD_ID)
    print(f"{len(synced)} commandes slash synchronisées.")

    # 2. Nettoyer les anciennes commandes globales APRÈS (résidu du bug précédent)
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()

    print(f"Connecté en tant que {bot.user}")

bot.run(TOKEN)