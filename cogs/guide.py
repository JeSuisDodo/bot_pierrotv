import discord
from discord import app_commands
from discord.ext import commands


class Guide(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="guide", description="Explique le système de voitures et d'économie du serveur")
    async def guide(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🚗 Système de voitures — Guide",
            description="Gagne de l'argent en étant actif sur le serveur, et dépense-le pour te constituer un garage de rêve.",
            color=discord.Color.gold(),
        )

        embed.add_field(
            name="💰 Comment gagner de l'argent",
            value=(
                "**Messages** — 5 $ par message envoyé (cooldown de 60 secondes)\n"
                "**Vocal** — 10 $ par minute passée dans un salon vocal"
            ),
            inline=False,
        )

        embed.add_field(
            name="🏎️ La concession — `/shop`",
            value="Affiche toutes les voitures disponibles à l'achat, avec un menu déroulant pour acheter directement.",
            inline=False,
        )

        embed.add_field(
            name="🏠 Ton garage — `/garage [membre]`",
            value="Affiche ton inventaire de voitures. Ajoute un pseudo pour voir le garage de quelqu'un d'autre.",
            inline=False,
        )

        embed.add_field(
            name="💵 Ton argent — `/poche`",
            value="Affiche combien d'argent tu as actuellement.",
            inline=False,
        )

        embed.add_field(
            name="📊 Tes statistiques — `/infos`",
            value="Récapitule ton argent, tes messages envoyés, ton temps en vocal et ton nombre de voitures.",
            inline=False,
        )

        embed.add_field(
            name="🏦 L'hôtel des ventes — `/hdv`",
            value=(
                "Marché entre joueurs, en plus de la concession :\n"
                "`/vendre` — mets une de tes voitures en vente à ton prix\n"
                "`/acheter` — achète une voiture mise en vente par un autre joueur\n"
                "`/hdv` — consulte toutes les annonces actives"
            ),
            inline=False,
        )

        embed.set_footer(text="Sois actif, économise, et deviens le plus grand collectionneur du serveur 🏆")

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Guide(bot))
