import os
import discord
import pymongo
from dotenv import load_dotenv

load_dotenv()


def get_db():
    """Connexion à la base MongoDB Atlas"""
    CONNECTION_STRING = os.getenv("DBSTRING")
    client = pymongo.MongoClient(CONNECTION_STRING)
    return client["discord"]


# ---------- MEMBRES ----------
def get_members():
    db = get_db()
    return db["members"]


def get_member(member: discord.Member) -> dict:
    """Récupère (ou crée) le profil économique d'un membre"""
    collection = get_members()
    doc = collection.find_one({"id": member.id})
    if doc is None:
        doc = {
            "id": member.id,
            "name": member.name,
            "money": 0,
            "messages": 0,
            "voicetime": 0,  # en secondes
            "cars": [],  # liste de clés (voir cars.py)
        }
        collection.insert_one(doc)
    return doc


def get_money(member: discord.Member) -> int:
    return get_member(member)["money"]


def get_cars(member: discord.Member) -> list:
    return get_member(member)["cars"]


def add_money(member: discord.Member, amount: int) -> None:
    """Ajoute (ou retire si négatif) de l'argent à un membre"""
    collection = get_members()
    collection.update_one(
        {"id": member.id},
        {
            "$setOnInsert": {"name": member.name, "cars": []},
            "$inc": {"money": amount},
        },
        upsert=True,
    )


def add_message_count(member: discord.Member, amount: int = 1) -> None:
    collection = get_members()
    collection.update_one(
        {"id": member.id},
        {
            "$setOnInsert": {"name": member.name, "cars": []},
            "$inc": {"messages": amount},
        },
        upsert=True,
    )


def add_voicetime(member: discord.Member, seconds: int) -> None:
    collection = get_members()
    collection.update_one(
        {"id": member.id},
        {
            "$setOnInsert": {"name": member.name, "cars": []},
            "$inc": {"voicetime": seconds},
        },
        upsert=True,
    )


def add_car(member: discord.Member, car_key: str) -> None:
    collection = get_members()
    collection.update_one(
        {"id": member.id},
        {"$push": {"cars": car_key}},
        upsert=True,
    )


def remove_car(member: discord.Member, car_key: str) -> bool:
    """Retire une voiture de l'inventaire (une seule occurrence). Renvoie False si absente."""
    collection = get_members()
    member_doc = get_member(member)
    if car_key not in member_doc["cars"]:
        return False
    collection.update_one({"id": member.id}, {"$pull": {"cars": car_key}})
    # $pull retire TOUTES les occurrences, donc on réinsère les doublons restants si besoin
    remaining = member_doc["cars"].count(car_key) - 1
    for _ in range(remaining):
        collection.update_one({"id": member.id}, {"$push": {"cars": car_key}})
    return True


# ---------- MARCHÉ (HDV) ----------
def get_market():
    db = get_db()
    return db["market"]


def create_listing(seller: discord.Member, car_key: str, price: int) -> str:
    """Crée une annonce sur le marché, renvoie l'ID court de l'annonce"""
    collection = get_market()
    result = collection.insert_one(
        {
            "seller_id": seller.id,
            "seller_name": seller.name,
            "car_key": car_key,
            "price": price,
        }
    )
    return str(result.inserted_id)[-6:]  # ID court affiché aux utilisateurs


def get_listings() -> list:
    collection = get_market()
    return list(collection.find())


def get_listing_by_short_id(short_id: str) -> dict:
    """Retrouve une annonce à partir de son ID court (6 derniers caractères)"""
    for listing in get_listings():
        if str(listing["_id"])[-6:] == short_id:
            return listing
    return None


def remove_listing(listing_id) -> None:
    collection = get_market()
    collection.delete_one({"_id": listing_id})


# ---------- GIVEAWAYS ----------
def get_giveaways():
    db = get_db()
    return db["giveaways"]


def create_giveaway(prize: str, winner_count: int, channel_id: int, created_by: int, ends_at) -> str:
    """Crée un giveaway et renvoie son _id (ObjectId)"""
    collection = get_giveaways()
    result = collection.insert_one(
        {
            "prize": prize,
            "winner_count": winner_count,
            "channel_id": channel_id,
            "message_id": None,
            "created_by": created_by,
            "ends_at": ends_at,
            "participants": [],
            "ended": False,
            "winners": [],
        }
    )
    return result.inserted_id


def set_giveaway_message(giveaway_id, message_id: int) -> None:
    collection = get_giveaways()
    collection.update_one({"_id": giveaway_id}, {"$set": {"message_id": message_id}})


def get_active_giveaway(channel_id: int) -> dict:
    """Renvoie le giveaway en cours pour ce salon, ou None s'il n'y en a pas"""
    collection = get_giveaways()
    return collection.find_one({"channel_id": channel_id, "ended": False})


def get_expired_giveaways(now) -> list:
    collection = get_giveaways()
    return list(collection.find({"ended": False, "ends_at": {"$lte": now}}))


def add_giveaway_participant(giveaway_id, user_id: int) -> bool:
    """Ajoute un participant s'il n'est pas déjà inscrit (opération atomique, pas de
    doublon possible). Renvoie False s'il participait déjà à ce giveaway."""
    collection = get_giveaways()
    result = collection.update_one(
        {"_id": giveaway_id, "participants": {"$ne": user_id}},
        {"$push": {"participants": user_id}},
    )
    return result.modified_count > 0


def end_giveaway(giveaway_id, winners: list) -> None:
    collection = get_giveaways()
    collection.update_one({"_id": giveaway_id}, {"$set": {"ended": True, "winners": winners}})
