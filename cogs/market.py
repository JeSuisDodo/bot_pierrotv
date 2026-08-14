import asyncio
import discord
from discord import app_commands
from discord.ext import commands
 
import db
from cars import CARS
from format import format
 
 
class Market(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
 
    @app_commands.command(name="hdv", description="Affiche les annonces de l'hôtel des ventes")
    async def hdv(self, interaction: discord.Interaction):
        listings = await asyncio.to_thread(db.get_listings)
        if not listings:
            description = "Aucune annonce en ce moment."
        else:
            lines = []
            for listing in listings:
                car_name = CARS.get(listing["car_key"], {}).get("name", listing["car_key"])
                short_id = str(listing["_id"])[-6:]
                lines.append(
                    f"`{short_id}` — **{car_name}** — {format(listing['price'])} $ "
                    f"(vendeur : {listing['seller_name']})"
                )
            description = "\n".join(lines)
 
        embed = discord.Embed(
            title="🏦 Hôtel des ventes",
            description=description,
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed)
 
    @app_commands.command(name="vendre", description="Met une de tes voitures en vente sur l'hôtel des ventes")
    @app_commands.describe(voiture="Voiture à vendre (tape pour voir tes voitures)", prix="Prix de vente en $")
    async def vendre(self, interaction: discord.Interaction, voiture: str, prix: int):
        if voiture not in CARS:
            await interaction.response.send_message(
                "Cette voiture n'existe pas. Vérifie l'orthographe (ex: `honda_civic_eg6`).",
                ephemeral=True,
            )
            return
 
        if prix <= 0:
            await interaction.response.send_message("Le prix doit être positif.", ephemeral=True)
            return
 
        await interaction.response.defer()
 
        removed = await asyncio.to_thread(db.remove_car, interaction.user, voiture)
        if not removed:
            await interaction.followup.send(
                "Tu ne possèdes pas cette voiture. Vérifie ton `/garage`.",
                ephemeral=True,
            )
            return
 
        car = CARS[voiture]
        short_id = await asyncio.to_thread(db.create_listing, interaction.user, voiture, prix)
 
        embed = discord.Embed(
            title="Annonce créée",
            description=f"**{car['name']}** mise en vente pour {format(prix)} $\nID de l'annonce : `{short_id}`",
            color=discord.Color.orange(),
        )
        await interaction.followup.send(embed=embed)
 
    @vendre.autocomplete("voiture")
    async def vendre_autocomplete(self, interaction: discord.Interaction, current: str):
        cars = await asyncio.to_thread(db.get_cars, interaction.user)
        unique_keys = sorted(set(cars))
        choices = []
        for key in unique_keys:
            name = CARS.get(key, {}).get("name", key)
            if current.lower() in name.lower():
                choices.append(app_commands.Choice(name=name, value=key))
        return choices[:25]  # Discord limite à 25 suggestions
 
    @app_commands.command(name="acheter", description="Achète une voiture sur l'hôtel des ventes")
    @app_commands.describe(id_annonce="Annonce à acheter (tape pour voir les annonces)")
    async def acheter(self, interaction: discord.Interaction, id_annonce: str):
        await interaction.response.defer()
 
        listing = await asyncio.to_thread(db.get_listing_by_short_id, id_annonce)
        if listing is None:
            await interaction.followup.send("Annonce introuvable.", ephemeral=True)
            return
 
        if listing["seller_id"] == interaction.user.id:
            await interaction.followup.send("Tu ne peux pas acheter ta propre annonce.", ephemeral=True)
            return
 
        buyer_money = await asyncio.to_thread(db.get_money, interaction.user)
        if buyer_money < listing["price"]:
            await interaction.followup.send(
                f"Tu n'as pas assez d'argent ({format(listing['price'])} $ requis, "
                f"tu as {format(buyer_money)} $).",
                ephemeral=True,
            )
            return
 
        car_key = listing["car_key"]
        car = CARS[car_key]
 
        # Transaction
        await asyncio.to_thread(db.add_money, interaction.user, -listing["price"])
        await asyncio.to_thread(db.add_car, interaction.user, car_key)
        await asyncio.to_thread(db.remove_listing, listing["_id"])
 
        seller = interaction.guild.get_member(listing["seller_id"])
        if seller:
            await asyncio.to_thread(db.add_money, seller, listing["price"])
 
        embed = discord.Embed(
            title="Achat réussi",
            description=f"Tu as acheté **{car['name']}** pour {format(listing['price'])} $ 🚗",
            color=discord.Color.green(),
        )
        await interaction.followup.send(embed=embed)
 
 
    @acheter.autocomplete("id_annonce")
    async def acheter_autocomplete(self, interaction: discord.Interaction, current: str):
        listings = await asyncio.to_thread(db.get_listings)
        choices = []
        for listing in listings:
            if listing["seller_id"] == interaction.user.id:
                continue  # on ne propose pas ses propres annonces
            short_id = str(listing["_id"])[-6:]
            car_name = CARS.get(listing["car_key"], {}).get("name", listing["car_key"])
            label = f"{car_name} — {format(listing['price'])} $ ({short_id})"
            if current.lower() in label.lower():
                choices.append(app_commands.Choice(name=label, value=short_id))
        return choices[:25]
 
 
async def setup(bot: commands.Bot):
    await bot.add_cog(Market(bot))