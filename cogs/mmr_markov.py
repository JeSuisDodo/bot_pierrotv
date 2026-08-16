"""
cogs/mmr_markov.py
===================

Commande Discord `/mmr` qui adapte le script `valorant_mmr_markov.py` :
récupère l'historique MMR réel d'un joueur via l'API HenrikDev, modélise
sa progression comme une chaîne de Markov contrôlée, et renvoie le
graphique de comparaison (réel vs. simulé) directement dans Discord.

Le calcul (appels API + numpy + matplotlib) est lourd et bloquant, donc il
tourne dans un thread séparé (asyncio.to_thread) pour ne jamais geler le
bot, avec un defer() immédiat pour laisser le temps nécessaire.
"""

import io
import os
import time
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import discord
import numpy as np
import requests
from discord import app_commands
from discord.ext import commands

import matplotlib
matplotlib.use("Agg")  # pas d'affichage graphique sur un serveur
import matplotlib.pyplot as plt

HENRIKDEV_API_KEY = os.getenv("HENRIKDEV_API_KEY")

REGIONS = [
    app_commands.Choice(name="Europe", value="eu"),
    app_commands.Choice(name="Amérique du Nord", value="na"),
    app_commands.Choice(name="Asie-Pacifique", value="ap"),
    app_commands.Choice(name="Corée", value="kr"),
    app_commands.Choice(name="Amérique Latine", value="latam"),
    app_commands.Choice(name="Brésil", value="br"),
]


# --------------------------------------------------------------------------- #
# 1. Récupération des données réelles (proxy du MMR)
# --------------------------------------------------------------------------- #

@dataclass
class MatchPoint:
    date: str
    elo: int
    rr_delta: int
    result: str  # "win" ou "loss"


@dataclass
class Config:
    name: str
    tag: str
    region: str = "eu"
    platform: str = "pc"
    state_width: int = 25
    api_key: Optional[str] = field(default_factory=lambda: HENRIKDEV_API_KEY)
    base_url: str = "https://api.henrikdev.xyz/valorant/v2/mmr-history"


def _parse_entries(entries: list[dict]) -> list[MatchPoint]:
    points: list[MatchPoint] = []
    for entry in entries:
        elo = entry.get("elo")
        delta = entry.get("last_change", entry.get("mmr_change_to_last_game", 0))
        date = entry.get("date", "")
        if elo is None:
            continue
        result = "win" if delta >= 0 else "loss"
        points.append(MatchPoint(date=date, elo=elo, rr_delta=delta, result=result))
    points.reverse()
    return _filter_valid_elo(points)


def _filter_valid_elo(points: list[MatchPoint]) -> list[MatchPoint]:
    """Retire les points à elo=0 : resets de saison / placements non classés,
    qui ne reflètent pas un vrai MMR et faussent le graphique."""
    return [p for p in points if p.elo > 0]


def _get(url: str, api_key: str) -> dict:
    resp = requests.get(url, headers={"Authorization": api_key}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_mmr_history(cfg: Config, min_matches: int = 10, max_matches: Optional[int] = 300) -> list[MatchPoint]:
    if not cfg.api_key:
        raise RuntimeError("Aucune clé API HenrikDev configurée (HENRIKDEV_API_KEY).")

    url = f"{cfg.base_url}/{cfg.region}/{cfg.platform}/{cfg.name}/{cfg.tag}"
    payload = _get(url, cfg.api_key)
    data = payload.get("data", {})
    entries = data.get("history", []) if isinstance(data, dict) else (data or [])
    points = _parse_entries(entries)

    # On ne s'arrête ici que si on a DÉJÀ assez de matchs pour satisfaire max_matches.
    # Sinon (cas fréquent : mmr-history ne couvre que l'acte en cours, ~20 matchs),
    # on va chercher le reste via l'historique paginé stored-mmr-history.
    if len(points) >= min_matches and (max_matches is None or len(points) >= max_matches):
        return points[-max_matches:] if max_matches else points

    stored_points = fetch_stored_history_paginated(cfg, max_matches=max_matches)
    return stored_points if len(stored_points) > len(points) else points


def fetch_stored_history_paginated(
    cfg: Config, max_matches: Optional[int] = 300, page_size: int = 100, max_pages: int = 10
) -> list[MatchPoint]:
    base = f"https://api.henrikdev.xyz/valorant/v2/stored-mmr-history/{cfg.region}/{cfg.platform}/{cfg.name}/{cfg.tag}"
    all_entries: list[dict] = []
    total_available: Optional[int] = None
    page = 1

    while page <= max_pages:
        url = f"{base}?page={page}&size={page_size}"
        try:
            payload = _get(url, cfg.api_key)
        except requests.exceptions.HTTPError:
            break

        results_meta = payload.get("results", {}) if isinstance(payload, dict) else {}
        if total_available is None and "total" in results_meta:
            total_available = results_meta["total"]

        entries = payload.get("data", [])
        if not entries:
            break

        all_entries.extend(entries)

        got_enough = max_matches is not None and len(all_entries) >= max_matches
        last_page = len(entries) < page_size
        hit_total = total_available is not None and len(all_entries) >= total_available
        if got_enough or last_page or hit_total:
            break

        page += 1
        time.sleep(0.3)

    if max_matches is not None:
        all_entries = all_entries[:max_matches]

    return _parse_entries(all_entries)


# --------------------------------------------------------------------------- #
# 2. Chaîne de Markov contrôlée d'ordre 2
# --------------------------------------------------------------------------- #

def to_state(elo: int, width: int) -> int:
    return elo // width


class ControlledMarkovChainOrder2:
    order = 2
    START = "start"

    def __init__(self, width: int):
        self.width = width
        self.counts: dict[str, dict[tuple, dict[int, int]]] = {
            "win": defaultdict(lambda: defaultdict(int)),
            "loss": defaultdict(lambda: defaultdict(int)),
        }
        self.states: set[int] = set()

    def fit(self, history: list[MatchPoint]) -> None:
        for i in range(len(history) - 1):
            bucket_i = to_state(history[i].elo, self.width)
            prev_result = history[i].result if i > 0 else self.START
            aug_state = (bucket_i, prev_result)

            bucket_next = to_state(history[i + 1].elo, self.width)
            next_result = history[i + 1].result

            self.states.add(bucket_i)
            self.states.add(bucket_next)
            self.counts[next_result][aug_state][bucket_next] += 1

    def transition_row(self, result: str, aug_state: tuple) -> dict[int, float]:
        row = self.counts[result].get(aug_state)
        if not row:
            bucket, _ = aug_state
            merged: dict[int, int] = defaultdict(int)
            for (b, _prev), sub_row in self.counts[result].items():
                if b == bucket:
                    for j, c in sub_row.items():
                        merged[j] += c
            if merged:
                total = sum(merged.values())
                return {j: c / total for j, c in merged.items()}
            return {bucket: 1.0}
        total = sum(row.values())
        return {j: c / total for j, c in row.items()}

    def sample_next_state(self, result: str, aug_state: tuple, rng: np.random.Generator) -> int:
        row = self.transition_row(result, aug_state)
        outcomes, probs = zip(*row.items())
        return int(rng.choice(outcomes, p=probs))


def win_rate(history: list[MatchPoint]) -> float:
    wins = sum(1 for m in history if m.result == "win")
    return wins / len(history) if history else 0.5


def conditional_win_rates(history: list[MatchPoint]) -> dict[str, float]:
    overall = win_rate(history)
    tallies: dict[str, list[int]] = {"win": [0, 0], "loss": [0, 0]}
    for prev, curr in zip(history, history[1:]):
        tallies.setdefault(prev.result, [0, 0])
        tallies[prev.result][1] += 1
        if curr.result == "win":
            tallies[prev.result][0] += 1

    rates = {key: (w / t if t > 0 else overall) for key, (w, t) in tallies.items()}
    rates[ControlledMarkovChainOrder2.START] = overall
    return rates


def simulate_order2(
    chain: ControlledMarkovChainOrder2,
    start_state: int,
    n_steps: int,
    cond_win_rates: dict[str, float],
    n_runs: int = 200,
    seed: int = 0,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    trajectories = np.zeros((n_runs, n_steps + 1), dtype=int)
    trajectories[:, 0] = start_state
    default_p_win = cond_win_rates.get(ControlledMarkovChainOrder2.START, 0.5)

    for run in range(n_runs):
        state = start_state
        prev_result = ControlledMarkovChainOrder2.START
        for t in range(1, n_steps + 1):
            p_win = cond_win_rates.get(prev_result, default_p_win)
            result = "win" if rng.random() < p_win else "loss"
            aug_state = (state, prev_result)
            state = chain.sample_next_state(result, aug_state, rng)
            trajectories[run, t] = state
            prev_result = result

    return trajectories * chain.width


def plot_comparison(history: list[MatchPoint], sims: np.ndarray, name: str, tag: str) -> io.BytesIO:
    real_elo = [m.elo for m in history]
    mean_sim = sims.mean(axis=0)
    std_sim = sims.std(axis=0)

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(real_elo, label="Elo réel (proxy MMR)", color="black", linewidth=2)
    x_sim = range(len(mean_sim))
    ax.plot(x_sim, mean_sim, label="Chaîne de Markov ordre 2 (moyenne simulée)", color="tab:red")
    ax.fill_between(
        x_sim, mean_sim - std_sim, mean_sim + std_sim,
        color="tab:red", alpha=0.2, label="Écart-type simulé",
    )
    ax.set_xlabel("Numéro de match")
    ax.set_ylabel("Elo (proxy du MMR)")
    ax.set_title(f"Progression MMR de {name}#{tag}")
    ax.legend()
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


def build_mmr_graph(name: str, tag: str, region: str) -> io.BytesIO:
    """Fonction bloquante complète : fetch + fit + simulate + plot. À lancer via asyncio.to_thread."""
    cfg = Config(name=name, tag=tag, region=region)
    history = fetch_mmr_history(cfg, min_matches=10, max_matches=300)

    if len(history) < 10:
        raise ValueError(
            f"Seulement {len(history)} match(s) classé(s) trouvé(s) (minimum requis : 10)."
        )

    start_state = to_state(history[0].elo, cfg.state_width)
    chain = ControlledMarkovChainOrder2(width=cfg.state_width)
    chain.fit(history)
    cond_rates = conditional_win_rates(history)
    sims = simulate_order2(chain, start_state, len(history) - 1, cond_rates, n_runs=200)

    return plot_comparison(history, sims, name, tag)


# --------------------------------------------------------------------------- #
# 3. Cog Discord
# --------------------------------------------------------------------------- #

class MMRMarkov(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="mmr", description="Affiche la progression du MMR d'un joueur (modèle statistique)")
    @app_commands.describe(
        pseudo="Riot ID complet, format Pseudo#Tag (ex: Dodo#1234)",
        region="Région du compte",
    )
    @app_commands.choices(region=REGIONS)
    async def mmr(self, interaction: discord.Interaction, pseudo: str, region: app_commands.Choice[str]):
        if "#" not in pseudo:
            await interaction.response.send_message(
                "Format invalide. Utilise `Pseudo#Tag` (ex: `Dodo#1234`).",
                ephemeral=True,
            )
            return

        name, tag = pseudo.split("#", 1)
        await interaction.response.defer()

        try:
            image_buffer = await asyncio.to_thread(build_mmr_graph, name, tag, region.value)
        except ValueError as e:
            await interaction.followup.send(str(e))
            return
        except RuntimeError as e:
            await interaction.followup.send(str(e))
            return
        except requests.exceptions.HTTPError as e:
            await interaction.followup.send(f"Erreur de l'API Valorant : {e}")
            return
        except Exception as e:
            await interaction.followup.send(f"Erreur inattendue : {e}")
            return

        file = discord.File(image_buffer, filename="mmr_progression.png")
        embed = discord.Embed(
            title=f"📈 Progression MMR — {name}#{tag}",
            description=(
                "Modèle statistique (chaîne de Markov d'ordre 2) : la courbe noire est le MMR réel "
                "(proxy), la rouge la moyenne simulée, la zone rose l'écart-type. Riot ne publie pas "
                "la vraie formule, ceci est une approximation."
            ),
            color=discord.Color.red(),
        )
        embed.set_image(url="attachment://mmr_progression.png")
        await interaction.followup.send(embed=embed, file=file)


async def setup(bot: commands.Bot):
    await bot.add_cog(MMRMarkov(bot))
