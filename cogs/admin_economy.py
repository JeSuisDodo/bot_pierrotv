import asyncio
import discord
from discord import app_commands
from discord.ext import commands

import db
from cars import CARS
from format import format

# ID du rôle modérateur autorisé à utiliser ces commandes
MOD_ROLE_ID = None  # remplace par l'ID du rôle, ex: 123456789012345678


def is_mod():
    """Vérifie que l'utilisateur a le rôle modérateur (ou la permission Gérer le serveur)"""

    def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.manage_guild:
            return True
        if MOD_ROLE_ID and any(role.id == MOD_ROLE_ID for role in interaction.user.roles):
            return True
        return False

    return app_commands.check(predicate)


class AdminEconomy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="give", description="[Modo] Donne de l'argent à un membre")
    @app_commands.describe(membre="Membre à créditer", montant="Montant en $")
    @is_mod()
    async def give(self, interaction: discord.Interaction, membre: discord.Member, montant: int):
        if montant <= 0:
            await interaction.response.send_message("Le montant doit être positif.", ephemeral=True)
            return

        await asyncio.to_thread(db.add_money, membre, montant)
        embed = discord.Embed(
            title="Argent donné",
            description=f"**{format(montant)} $** ajoutés à {membre.mention}",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="takeback", description="[Modo] Reprend de l'argent à un membre")
    @app_commands.describe(membre="Membre à débiter", montant="Montant en $")
    @is_mod()
    async def takeback(self, interaction: discord.Interaction, membre: discord.Member, montant: int):
        if montant <= 0:
            await interaction.response.send_message("Le montant doit être positif.", ephemeral=True)
            return

        await asyncio.to_thread(db.add_money, membre, -montant)
        embed = discord.Embed(
            title="Argent repris",
            description=f"**{format(montant)} $** retirés à {membre.mention}",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="delete", description="[Modo] Supprime une voiture de l'inventaire d'un membre")
    @app_commands.describe(membre="Membre concerné", voiture="Voiture à supprimer")
    @is_mod()
    async def delete(self, interaction: discord.Interaction, membre: discord.Member, voiture: str):
        removed = await asyncio.to_thread(db.remove_car, membre, voiture)
        if not removed:
            await interaction.response.send_message(
                f"{membre.mention} ne possède pas cette voiture.", ephemeral=True
            )
            return

        car_name = CARS.get(voiture, {}).get("name", voiture)
        embed = discord.Embed(
            title="Voiture supprimée",
            description=f"**{car_name}** retirée du garage de {membre.mention}",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed)

    @delete.autocomplete("voiture")
    async def delete_autocomplete(self, interaction: discord.Interaction, current: str):
        # Nécessite le membre déjà sélectionné dans la commande pour cibler son garage
        membre = interaction.namespace.membre
        if membre is None:
            return []
        cars = await asyncio.to_thread(db.get_cars, membre)
        unique_keys = sorted(set(cars))
        choices = []
        for key in unique_keys:
            name = CARS.get(key, {}).get("name", key)
            if current.lower() in name.lower():
                choices.append(app_commands.Choice(name=name, value=key))
        return choices[:25]

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message(
                "Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
            )
        else:
            raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminEconomy(bot))
