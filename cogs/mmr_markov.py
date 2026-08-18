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

# Correspondance elo -> rang, valable UNIQUEMENT en dessous d'Immortel
# (paliers fixes de 100, RR remis à 0 à chaque changement de rang)
RANK_TIERS: list[tuple[int, str]] = [
    (0, "Fer 1"), (100, "Fer 2"), (200, "Fer 3"),
    (300, "Bronze 1"), (400, "Bronze 2"), (500, "Bronze 3"),
    (600, "Argent 1"), (700, "Argent 2"), (800, "Argent 3"),
    (900, "Or 1"), (1000, "Or 2"), (1100, "Or 3"),
    (1200, "Platine 1"), (1300, "Platine 2"), (1400, "Platine 3"),
    (1500, "Diamant 1"), (1600, "Diamant 2"), (1700, "Diamant 3"),
    (1800, "Ascendant 1"), (1900, "Ascendant 2"), (2000, "Ascendant 3"),
]

# Elo où débute l'Immortel (fin du dernier palier Ascendant 3, qui fait
# lui-même 100 de large comme les autres rangs classiques)
IMMORTAL_START = 2100

# Seuil RR par défaut pour Radiant si le classement live n'a pas pu être
# récupéré (300 RR est le plancher théorique minimum avant même de
# pouvoir prétendre à une place dans le top 500)
DEFAULT_RADIANT_THRESHOLD_RR = 300


def elo_to_rank_and_rr(elo: float, radiant_threshold_rr: int = DEFAULT_RADIANT_THRESHOLD_RR) -> tuple[str, int]:
    """Convertit une valeur d'elo en (nom du rang, RR).

    En dessous d'Immortel : chaque rang fait 100 RR de large, le RR est
    remis à 0 à chaque changement de rang (fonctionnement classique).

    À partir d'Immortel : le RR est CUMULATIF et ne se remet JAMAIS à 0.
    On passe Immortel 2 à 100 RR cumulés, Immortel 3 à 200 RR cumulés.
    Au-delà de 300 RR (ou du seuil réel du 500e joueur du classement live
    si connu via radiant_threshold_rr), le joueur devient Radiant SEULEMENT
    s'il est effectivement dans le top 500 de sa région — en dessous de ce
    seuil de classement, il reste Immortel 3 même avec un RR très élevé.
    Cette fonction ne connaît pas le classement historique exact à chaque
    match ; radiant_threshold_rr est le seuil utilisé au moment du calcul,
    donc une approximation pour les points anciens de l'historique."""
    if elo < IMMORTAL_START:
        idx = max(0, min(int(elo // 100), len(RANK_TIERS) - 1))
        threshold, name = RANK_TIERS[idx]
        rr = int(round(elo - threshold))
        rr = max(0, min(rr, 99))
        return name, rr

    total_rr = max(0, int(round(elo - IMMORTAL_START)))
    if total_rr >= radiant_threshold_rr:
        return "Radiant", total_rr
    if total_rr >= 200:
        return "Immortel 3", total_rr
    if total_rr >= 100:
        return "Immortel 2", total_rr
    return "Immortel 1", total_rr


def format_rank_rr(elo: float, radiant_threshold_rr: int = DEFAULT_RADIANT_THRESHOLD_RR) -> str:
    rank, rr = elo_to_rank_and_rr(elo, radiant_threshold_rr)
    return f"{rank} ({rr} RR)"


def fetch_radiant_threshold_rr(region: str, platform: str = "pc") -> int:
    """Récupère le RR du 500e joueur du classement live (seuil réel d'entrée
    en Radiant pour cette région). Si le classement compte moins de 500
    joueurs (région peu peuplée), on retombe sur le seuil plancher de 300 RR.

    On récupère les 500 premiers joueurs d'un coup (size=500) plutôt que de
    se fier au paramètre de pagination start_index=500 seul : certains CDN/
    caches renvoient la première page par défaut quand start_index est
    utilisé isolément, ce qui donnerait le RR du joueur classé 1er au lieu
    du 500e."""
    if not HENRIKDEV_API_KEY:
        return DEFAULT_RADIANT_THRESHOLD_RR

    url = f"https://api.henrikdev.xyz/valorant/v3/leaderboard/{region}/{platform}?start_index=1&size=500"
    try:
        resp = requests.get(url, headers={"Authorization": HENRIKDEV_API_KEY}, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        players = payload.get("data", {}).get("players", [])
        if len(players) >= 500:
            player_500 = players[499]
            # Garde-fou : si le rang renvoyé n'est pas proche de 500, la
            # pagination n'a probablement pas été respectée par l'API/CDN.
            reported_rank = player_500.get("leaderboard_rank")
            if reported_rank is not None and abs(reported_rank - 500) > 20:
                return DEFAULT_RADIANT_THRESHOLD_RR
            return int(player_500.get("rr", DEFAULT_RADIANT_THRESHOLD_RR))
    except Exception:
        pass
    return DEFAULT_RADIANT_THRESHOLD_RR


def find_local_extrema(
    values: np.ndarray, window: int = 15, max_points: int = 8
) -> list[tuple[int, float, str]]:
    """Repère les pics/creux locaux significatifs (indice, valeur, 'max' ou 'min'),
    en fusionnant les points trop proches et en limitant le nombre affiché
    pour garder le graphique lisible. Le maximum et le minimum globaux de
    toute la courbe sont TOUJOURS inclus, même si l'algorithme de fenêtre
    glissante ne les aurait pas retenus."""
    n = len(values)
    if n == 0:
        return []

    global_max_idx = int(np.argmax(values))
    global_min_idx = int(np.argmin(values))
    guaranteed = [
        (global_max_idx, float(values[global_max_idx]), "max"),
        (global_min_idx, float(values[global_min_idx]), "min"),
    ]

    if n < 2 * window + 1:
        # Historique trop court pour la détection par fenêtre : on renvoie
        # au moins les extremums globaux garantis.
        return sorted(guaranteed, key=lambda c: c[0])

    candidates: list[tuple[int, float, str]] = []
    for i in range(window, n - window):
        segment = values[i - window : i + window + 1]
        if values[i] == segment.max() and values[i] > values[i - 1] and values[i] >= values[i + 1]:
            candidates.append((i, float(values[i]), "max"))
        elif values[i] == segment.min() and values[i] < values[i - 1] and values[i] <= values[i + 1]:
            candidates.append((i, float(values[i]), "min"))

    # Fusionne les extremums trop proches (garde le plus marqué)
    merged: list[tuple[int, float, str]] = []
    for cand in candidates:
        if merged and abs(cand[0] - merged[-1][0]) < window:
            same_kind = cand[2] == merged[-1][2]
            more_extreme = (cand[2] == "max" and cand[1] > merged[-1][1]) or (
                cand[2] == "min" and cand[1] < merged[-1][1]
            )
            if same_kind and more_extreme:
                merged[-1] = cand
            continue
        merged.append(cand)

    # S'assure que le max/min global est présent (fusionné avec un candidat
    # proche existant, sinon ajouté explicitement)
    for g_idx, g_val, g_kind in guaranteed:
        near = next((c for c in merged if abs(c[0] - g_idx) < window), None)
        if near is None:
            merged.append((g_idx, g_val, g_kind))
        elif near[1] != g_val:
            merged[merged.index(near)] = (g_idx, g_val, g_kind)
    merged.sort(key=lambda c: c[0])

    # Limite au N points les plus marqués (par écart à la médiane), en gardant
    # TOUJOURS le max et le min globaux, puis complète avec les plus notables
    if len(merged) > max_points:
        median = float(np.median(values))
        mandatory_idx = {global_max_idx, global_min_idx}
        mandatory = [c for c in merged if c[0] in mandatory_idx]
        rest = [c for c in merged if c[0] not in mandatory_idx]
        rest.sort(key=lambda c: abs(c[1] - median), reverse=True)
        remaining_slots = max(0, max_points - len(mandatory))
        merged = mandatory + rest[:remaining_slots]
        merged.sort(key=lambda c: c[0])

    return merged

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


def plot_comparison(
    history: list[MatchPoint],
    sims: np.ndarray,
    name: str,
    tag: str,
    radiant_threshold_rr: int = DEFAULT_RADIANT_THRESHOLD_RR,
) -> io.BytesIO:
    real_elo = np.array([m.elo for m in history], dtype=float)
    mean_sim = sims.mean(axis=0)
    std_sim = sims.std(axis=0)
    n = len(real_elo)

    fig, ax = plt.subplots(figsize=(11, 6.5))
    ax.plot(real_elo, label="Rang réel (proxy MMR)", color="black", linewidth=2)
    x_sim = range(len(mean_sim))
    ax.plot(x_sim, mean_sim, label="Chaîne de Markov ordre 2 (moyenne simulée)", color="tab:red")
    ax.fill_between(
        x_sim, mean_sim - std_sim, mean_sim + std_sim,
        color="tab:red", alpha=0.2, label="Écart-type simulé",
    )

    # --- Axe des ordonnées en rangs plutôt qu'en elo brut ---
    y_min, y_max = ax.get_ylim()

    # Rangs classiques en dessous d'Immortel (paliers fixes de 100, RR reset)
    ticks = [t for t, _ in RANK_TIERS if y_min - 100 <= t <= min(y_max + 100, IMMORTAL_START)]
    labels = [name_ for t, name_ in RANK_TIERS if y_min - 100 <= t <= min(y_max + 100, IMMORTAL_START)]

    # À partir d'Immortel, on n'affiche que deux repères : le début
    # d'Immortel 3 (200 RR cumulés) et le début de Radiant (seuil live
    # actuel), sans graduation intermédiaire tous les 100 RR.
    immortel3_elo = IMMORTAL_START + 200
    radiant_elo = IMMORTAL_START + radiant_threshold_rr

    if y_min - 100 <= immortel3_elo <= y_max + 100:
        ticks.append(immortel3_elo)
        labels.append("Immortel 3")

    if y_min - 100 <= radiant_elo <= y_max + 100:
        ticks.append(radiant_elo)
        labels.append("Radiant")

    ax.set_yticks(ticks)
    ax.set_yticklabels(labels)
    ax.grid(axis="y", alpha=0.2)

    # --- Extremums (dont le max/min global garanti), annotés avec rang + RR ---
    extrema = find_local_extrema(real_elo)
    for idx, val, kind in extrema:
        offset = (0, 12) if kind == "max" else (0, -16)
        va = "bottom" if kind == "max" else "top"
        ax.annotate(
            format_rank_rr(val, radiant_threshold_rr),
            xy=(idx, val),
            xytext=offset,
            textcoords="offset points",
            ha="center",
            va=va,
            fontsize=8,
            color="black",
            arrowprops=dict(arrowstyle="-", color="gray", lw=0.7),
        )

    # --- Rang + RR actuel affiché à droite de la courbe simulée (rouge) ---
    padding = max(int(n * 0.15), 10)
    ax.set_xlim(0, n - 1 + padding)
    ax.annotate(
        format_rank_rr(mean_sim[-1], radiant_threshold_rr),
        xy=(len(mean_sim) - 1, mean_sim[-1]),
        xytext=(10, 0),
        textcoords="offset points",
        va="center",
        ha="left",
        fontsize=10,
        fontweight="bold",
        color="tab:red",
    )

    ax.set_xlabel("Numéro de match")
    ax.set_ylabel("Rang")
    ax.set_title(f"Progression MMR de {name}#{tag}")
    ax.legend(loc="upper left")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


def build_mmr_graph(name: str, tag: str, region: str) -> tuple[io.BytesIO, int]:
    """Fonction bloquante complète : fetch + fit + simulate + plot. À lancer via asyncio.to_thread.
    Renvoie (image, seuil_radiant_rr_utilisé)."""
    cfg = Config(name=name, tag=tag, region=region)
    history = fetch_mmr_history(cfg, min_matches=10, max_matches=300)

    if len(history) < 10:
        raise ValueError(
            f"Seulement {len(history)} match(s) classé(s) trouvé(s) (minimum requis : 10)."
        )

    radiant_threshold_rr = fetch_radiant_threshold_rr(region)

    start_state = to_state(history[0].elo, cfg.state_width)
    chain = ControlledMarkovChainOrder2(width=cfg.state_width)
    chain.fit(history)
    cond_rates = conditional_win_rates(history)
    sims = simulate_order2(chain, start_state, len(history) - 1, cond_rates, n_runs=200)

    image = plot_comparison(history, sims, name, tag, radiant_threshold_rr)
    return image, radiant_threshold_rr


# --------------------------------------------------------------------------- #
# 3. Cog Discord
# --------------------------------------------------------------------------- #

class MMRMarkov(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    async def _safe_followup(interaction: discord.Interaction, content: str) -> None:
        """Envoie un followup en avalant les erreurs réseau/expiration d'interaction,
        pour éviter un traceback brut dans les logs sur un simple aléa de connexion."""
        try:
            await interaction.followup.send(content)
        except (discord.HTTPException, ConnectionError, OSError):
            pass

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

        try:
            await interaction.response.defer()
        except (discord.HTTPException, ConnectionError, OSError):
            # Coupure réseau transitoire lors du defer initial : l'interaction
            # est probablement déjà expirée côté Discord, impossible de répondre.
            return

        try:
            image_buffer, radiant_threshold_rr = await asyncio.to_thread(build_mmr_graph, name, tag, region.value)
        except ValueError as e:
            await self._safe_followup(interaction, str(e))
            return
        except RuntimeError as e:
            await self._safe_followup(interaction, str(e))
            return
        except requests.exceptions.HTTPError as e:
            await self._safe_followup(interaction, f"Erreur de l'API Valorant : {e}")
            return
        except (ConnectionError, OSError, requests.exceptions.ConnectionError) as e:
            await self._safe_followup(
                interaction, "Problème réseau temporaire pendant la récupération des données. Réessaie dans quelques instants."
            )
            return
        except Exception as e:
            await self._safe_followup(interaction, f"Erreur inattendue : {e}")
            return

        file = discord.File(image_buffer, filename="mmr_progression.png")
        embed = discord.Embed(
            title=f"📈 Progression MMR — {name}#{tag}",
            description=(
                "Modèle statistique (chaîne de Markov d'ordre 2) : la courbe noire est le MMR réel "
                "(proxy), la rouge la moyenne simulée, la zone rose l'écart-type. Riot ne publie pas "
                "la vraie formule, ceci est une approximation.\n\n"
                f"Seuil Radiant utilisé pour ce graphique : **{radiant_threshold_rr} RR** "
                "(RR du 500e joueur du classement live de cette région, `/radiant` pour vérifier)."
            ),
            color=discord.Color.red(),
        )
        embed.set_image(url="attachment://mmr_progression.png")
        try:
            await interaction.followup.send(embed=embed, file=file)
        except (discord.HTTPException, ConnectionError, OSError):
            pass  # coupure réseau transitoire, rien à faire de plus


async def setup(bot: commands.Bot):
    await bot.add_cog(MMRMarkov(bot))