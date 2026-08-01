import discord
from discord import app_commands
from discord.ext import commands

import db
from cars import CARS
from format import format, format_seconds


class BuySelect(discord.ui.Select):
    def __init__(self, page_cars: dict):
        options = [
            discord.SelectOption(
                label=data["name"],
                description=f"{format(data['price'])} $",
                value=key,
            )
            for key, data in page_cars.items()
        ]
        super().__init__(placeholder="Choisis une voiture à acheter...", options=options)

    async def callback(self, interaction: discord.Interaction):
        car_key = self.values[0]
        car = CARS[car_key]
        member = interaction.user

        money = db.get_money(member)
        if money < car["price"]:
            await interaction.response.send_message(
                f"Tu n'as pas assez d'argent pour **{car['name']}** "
                f"({format(car['price'])} $, tu as {format(money)} $).",
                ephemeral=True,
            )
            return

        db.add_money(member, -car["price"])
        db.add_car(member, car_key)

        await interaction.response.send_message(
            f"Achat réussi : **{car['name']}** pour {format(car['price'])} $ 🚗",
            ephemeral=True,
        )


class BuyView(discord.ui.View):
    def __init__(self, all_cars: dict):
        super().__init__(timeout=60)
        items = list(all_cars.items())
        # Discord limite un Select à 25 options : on ajoute un 2e menu si besoin
        for i in range(0, len(items), 25):
            self.add_item(BuySelect(dict(items[i:i + 25])))


class Shop(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="poche", description="Affiche ton argent disponible")
    async def poche(self, interaction: discord.Interaction):
        money = db.get_money(interaction.user)
        embed = discord.Embed(
            title="💰 Ta poche",
            description=f"Tu as **{format(money)} $**",
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="garage", description="Affiche l'inventaire de voitures d'un membre")
    @app_commands.describe(membre="Membre à consulter (toi-même par défaut)")
    async def garage(self, interaction: discord.Interaction, membre: discord.Member = None):
        target = membre or interaction.user
        cars = db.get_cars(target)
        if not cars:
            description = "Ce garage est vide." if membre else "Ton garage est vide. Utilise `/shop` pour acheter une voiture !"
        else:
            counts = {}
            for key in cars:
                counts[key] = counts.get(key, 0) + 1
            lines = []
            for key, count in counts.items():
                name = CARS.get(key, {}).get("name", key)
                lines.append(f"🚗 {name}" + (f" x{count}" if count > 1 else ""))
            description = "\n".join(lines)

        embed = discord.Embed(
            title=f"🏠 Garage de {target.display_name}",
            description=description,
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="infos", description="Affiche toutes tes statistiques")
    async def infos(self, interaction: discord.Interaction):
        member_doc = db.get_member(interaction.user)
        cars_count = len(member_doc["cars"])

        embed = discord.Embed(
            title=f"📊 Statistiques de {interaction.user.display_name}",
            color=discord.Color.purple(),
        )
        embed.add_field(name="Argent", value=f"{format(member_doc['money'])} $", inline=True)
        embed.add_field(name="Messages envoyés", value=format(member_doc["messages"]), inline=True)
        embed.add_field(name="Temps en vocal", value=format_seconds(member_doc["voicetime"]), inline=True)
        embed.add_field(name="Voitures possédées", value=str(cars_count), inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="shop", description="Ouvre la concession pour acheter une voiture neuve")
    async def shop(self, interaction: discord.Interaction):
        items = list(CARS.items())
        lines = [f"**{data['name']}** — {format(data['price'])} $" for _, data in items]

        embed = discord.Embed(
            title="🏎️ Concession",
            description="\n".join(lines),
            color=discord.Color.green(),
        )

        # Discord limite un Select à 25 options, géré automatiquement dans BuyView
        view = BuyView(CARS)
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Shop(bot))
