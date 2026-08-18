import discord
from discord import app_commands
from discord.ext import commands

# Centralise tes réponses ici : title, description, et image (optionnelle)
INFO_DATA = {
    "crosshair": {
        "title": "Crosshair",
        "description": "0;c;1;s;1;P;u;000000FF;o;1;d;1;f;0;m;1;0b;0;1b;0;S;o;1",
        "image": "https://cdn.discordapp.com/attachments/1133105362086678588/1533073949821374535/image.png?ex=6a6f29e0&is=6a6dd860&hm=007f5dc840e4d8e8865bbce79c7e135811364d4ab183760a8d951b062c8c2dfd&",
    },
    "clavier/keybord": {
        "title": "Clavier",
        "description": "mchose ace 68 turbo\nhttps://maxesport.gg/fr/p/mchose-ace-68-turbo-he-ansi-us-cyber-black",
        "image": "https://cdn.discordapp.com/attachments/1090383298615853187/1533074582477471905/MCHOSE-Ace-68-Turbo-Magnetic-ANSI-US-Cyber-Black-1-640x640.png?ex=6a6f2a77&is=6a6dd8f7&hm=4c4c3012f80379dee3d9835a031aab70d72644fa7dc1d6956ccc722b404cd83f&",
    },
    "souris/mouse": {
        "title": "Souris",
        "description": "WL mouse beast X mini Pro 8K edition DRG\nhttps://maxesport.gg/fr/p/wlmouse-beast-x-max-wireless-noir",
        "image": "https://cdn.discordapp.com/attachments/1090383298615853187/1533075379152097370/images.png?ex=6a6f2b35&is=6a6dd9b5&hm=6a148855cb3e3a15aff022c5ed3d2e3576ea481a03c17659fc3bea70659b9a4e&",
    },
    "tapis/mousepad": {
        "title": "Tapis",
        "description": "Artisan TYPE 99 XSOFT\nhttps://maxesport.gg/fr/p/artisan-fx-type-99-xsoft-xxl-noir/",
        "image": "https://cdn.discordapp.com/attachments/1090383298615853187/1533075729049456792/Artisan-FX-TYPE-99-Black-1.png?ex=6a6f2b88&is=6a6dda08&hm=bb4e88f80067d406bd676ffc324067b977998bd91f2f90bc404efce7b089839e&",
    },
    "ecran/monitor": {
        "title": "Écran",
        "description": "Asus Rog Strix 610HZ Esport TN\nhttps://www.amazon.fr/ASUS-Esports-Gaming-Moniteur-XG248QSG/dp/B0FP19ZP37/ref=asc_df_B0FP19ZP37",
        "image": "https://cdn.discordapp.com/attachments/1090383298615853187/1533076316767912078/Asus_ROG_Strix_Ace_Esports_24.1-inch_FHD_610Hz_Gaming_Monitor_-_Black_XG248QSG_01.png?ex=6a6f2c15&is=6a6dda95&hm=d92f6a460c8ba445ca81a592a7ada76c1e5ab8eb49e947049246f3666c9f1e3c&",
    },
    "casque/headphone": {
        "title": "Casque",
        "description": "Logitech G Pro X\nhttps://www.logitechg.com/fr-fr/shop/p/pro-x-wireless-headset.981-000907",
        "image": "https://cdn.discordapp.com/attachments/1090383298615853187/1533072698278809660/images.png?ex=6a6f28b6&is=6a6dd736&hm=02a578d22e305a50458c416e9fd0be08e8866e132f71716d5d70f4491411a2ac&",
    },
    "sensibilite/sensi/sens": {
        "title": "Sensibilité",
        "description": "0.138 @ 1600 dpi",
        "image": None,
    },
    "kovaak": {
        "title": "Kovaak's",
        "description": (
            "**Switching** : CampingGhostpeekedShotgun\n"
            "**Tracking** : CallingGearedDunk\n"
            "**Clicking** : BunnyhoppingFraggedTag"
        ),
        "image": None,
    },
    "resolution/res": {
        "title": "Résolution",
        "description": "1280x960",
        "image": None,
    },
}


def build_embed(key: str) -> discord.Embed:
    data = INFO_DATA[key]
    embed = discord.Embed(
        title=data["title"],
        description=data["description"],
        color=discord.Color.blue(),
    )
    if data["image"]:
        embed.set_image(url=data["image"])
    return embed


class Info(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="commandes", description="Liste toutes les commandes disponibles")
    async def commandes(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📜 Commandes disponibles",
            description="Voici toutes les commandes utilisables sur le serveur.",
            color=discord.Color.green(),
        )

        embed.add_field(
            name="🖥️ Setup gaming",
            value=(
                "`/crosshair` — Crosshair Valorant utilisé\n"
                "`/clavier` (ou `/keybord`) — Clavier utilisé\n"
                "`/souris` (ou `/mouse`) — Souris utilisée\n"
                "`/tapis` (ou `/mousepad`) — Tapis de souris utilisé\n"
                "`/ecran` (ou `/monitor`) — Écran utilisé\n"
                "`/casque` (ou `/headphone`) — Casque utilisé\n"
                "`/sensi` (ou `/sens`, `/sensibilite`) — Sensibilité de souris\n"
                "`/resolution` (ou `/res`) — Résolution de jeu\n"
                "`/kovaak` — Scénarios Kovaak's utilisés à l'entraînement"
            ),
            inline=False,
        )

        embed.add_field(
            name="🎯 Valorant",
            value=(
                "`/rank <pseudo> <région>` — Rank actuel d'un joueur\n"
                "`/radiant <région>` — Seuil RR actuel pour être Radiant dans une région\n"
                "`/mmr <pseudo> <région>` — Graphique de progression du MMR (1 utilisation/semaine)"
            ),
            inline=False,
        )

        embed.add_field(
            name="🚗 Économie & voitures",
            value=(
                "`/guide` — Explique tout le système d'argent et de voitures du serveur : "
                "comment gagner de l'argent, la concession, ton garage, l'hôtel des ventes..."
            ),
            inline=False,
        )

        embed.set_footer(text="Utilise /guide pour tout savoir sur l'économie et les voitures du serveur.")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="crosshair", description="Affiche le crosshair")
    async def crosshair(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_embed("crosshair"))

    @app_commands.command(name="clavier", description="Affiche le clavier")
    async def clavier(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_embed("clavier/keybord"))

    @app_commands.command(name="keybord", description="Affiche le clavier")
    async def keybord(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_embed("clavier/keybord"))

    @app_commands.command(name="souris", description="Affiche la souris")
    async def souris(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_embed("souris/mouse"))

    @app_commands.command(name="mouse", description="Affiche la souris")
    async def mouse(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_embed("souris/mouse"))

    @app_commands.command(name="tapis", description="Affiche le tapis")
    async def tapis(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_embed("tapis/mousepad"))

    @app_commands.command(name="mousepad", description="Affiche le tapis")
    async def mousepad(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_embed("tapis/mousepad"))

    @app_commands.command(name="ecran", description="Affiche l'écran")
    async def ecran(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_embed("ecran/monitor"))

    @app_commands.command(name="monitor", description="Affiche l'écran")
    async def monitor(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_embed("ecran/monitor"))

    @app_commands.command(name="casque", description="Affiche le casque")
    async def casque(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_embed("casque/headphone"))

    @app_commands.command(name="headphone", description="Affiche le casque")
    async def headphone(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_embed("casque/headphone"))

    @app_commands.command(name="sensi", description="Affiche la sensibilité")
    async def sensi(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_embed("sensibilite/sensi/sens"))

    @app_commands.command(name="sens", description="Affiche la sensibilité")
    async def sens(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_embed("sensibilite/sensi/sens"))

    @app_commands.command(name="sensibilite", description="Affiche la sensibilité")
    async def sensibilite(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_embed("sensibilite/sensi/sens"))

    @app_commands.command(name="kovaak", description="Affiche les scenarios Kovaak's")
    async def kovaak(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_embed("kovaak"))

    @app_commands.command(name="resolution", description="Affiche la résolution")
    async def resolution(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_embed("resolution/res"))

    @app_commands.command(name="res", description="Affiche la résolution")
    async def res(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_embed("resolution/res"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))
