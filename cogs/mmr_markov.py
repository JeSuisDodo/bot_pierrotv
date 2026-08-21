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


# Couleur par groupe de rang (ignore le sous-palier, ex: "Fer 1"/"Fer 2" -> "Fer")
RANK_COLORS: dict[str, str] = {
    "Fer": "#8d8d93",
    "Bronze": "#a9704f",
    "Argent": "#a6b1bb",
    "Or": "#e0b93d",
    "Platine": "#2fb8b0",
    "Diamant": "#c77dff",
    "Ascendant": "#2ecc71",
    "Immortel": "#8e2a56",
    "Radiant": "#ffd700",
}


def rank_group(rank_name: str) -> str:
    """'Fer 1' -> 'Fer', 'Immortel 3' -> 'Immortel', 'Radiant' -> 'Radiant'."""
    return rank_name.split(" ")[0]


def elo_to_color(elo: float, radiant_threshold_rr: int = DEFAULT_RADIANT_THRESHOLD_RR) -> str:
    rank_name, _ = elo_to_rank_and_rr(elo, radiant_threshold_rr)
    return RANK_COLORS.get(rank_group(rank_name), "#1d3557")


def fetch_radiant_threshold_rr(region: str, platform: str = "pc") -> int:
    """Récupère le seuil Radiant officiel pour cette région.

    L'API renvoie directement le vrai seuil calculé par Riot dans
    "data.thresholds" (entrée avec tier.name == "Radiant"). Se baser sur le
    RR du 500e joueur du classement (ancienne approche) est peu fiable : le
    nombre de joueurs Radiant n'est pas toujours exactement 500, ça dépend
    de la région/saison."""
    if not HENRIKDEV_API_KEY:
        return DEFAULT_RADIANT_THRESHOLD_RR

    url = f"https://api.henrikdev.xyz/valorant/v3/leaderboard/{region}/{platform}?start_index=1&size=500"
    try:
        resp = requests.get(url, headers={"Authorization": HENRIKDEV_API_KEY}, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data", {})
        radiant_threshold = next(
            (t for t in data.get("thresholds", []) if t.get("tier", {}).get("name") == "Radiant"),
            None,
        )
        if radiant_threshold is not None:
            return int(radiant_threshold.get("threshold", DEFAULT_RADIANT_THRESHOLD_RR))
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
    match_id: Optional[str] = None


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
        match_id = entry.get("match_id")
        points.append(MatchPoint(date=date, elo=elo, rr_delta=delta, result=result, match_id=match_id))
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


# --------------------------------------------------------------------------- #
# 1bis. Ajustement à la force du lobby (échantillonné)
# --------------------------------------------------------------------------- #
#
# L'historique elo (mmr-history) ne contient que le MMR du joueur, pas la
# composition des parties. Pour savoir si un match a été joué contre un lobby
# plus fort ou plus faible que le joueur, il faut récupérer le détail complet
# de CE match (v4/match/{region}/{match_id}) — un appel API par match. Comme
# l'historique peut contenir jusqu'à 300 matchs, on n'échantillonne qu'une
# vingtaine de points répartis sur toute la période plutôt que de tout
# récupérer.

def tier_id_to_approx_elo(tier_id: int) -> float:
    """Convertit un tier.id (échelle Riot/HenrikDev : 3=Fer 1 ... 26=Immortel 3,
    27=Radiant) en valeur elo approximative sur notre échelle interne (milieu du
    palier de 100, faute de connaître le RR exact de l'adversaire à cet instant)."""
    bucket_index = tier_id - 3
    if bucket_index < 0:
        return 50.0
    return bucket_index * 100 + 50


def average_lobby_elo(players: list[dict], exclude_name: str, exclude_tag: str) -> Optional[float]:
    """Elo moyen approximatif des 9 autres joueurs d'un match (équipe + adversaires),
    en excluant le joueur recherché. None si aucun rang exploitable n'est trouvé."""
    tiers = [
        p.get("tier", {}).get("id")
        for p in players
        if not (
            (p.get("name") or "").lower() == exclude_name.lower()
            and (p.get("tag") or "").lower() == exclude_tag.lower()
        )
    ]
    tiers = [t for t in tiers if t is not None]
    if not tiers:
        return None
    return sum(tier_id_to_approx_elo(t) for t in tiers) / len(tiers)


def fetch_match_detail(cfg: Config, match_id: str) -> dict:
    url = f"https://api.henrikdev.xyz/valorant/v4/match/{cfg.region}/{match_id}"
    return _get(url, cfg.api_key)


def compute_lobby_adjustment(
    history: list[MatchPoint], cfg: Config, n_samples: int = 20, damping: float = 0.3
) -> np.ndarray:
    """Échantillonne ~n_samples matchs répartis sur l'historique, récupère leur
    composition complète, et calcule un ajustement d'elo (positif si le lobby
    était plus fort que le joueur à ce moment-là, négatif sinon) interpolé sur
    tout l'historique. Renvoie un tableau de deltas, un par point de `history`
    (tout à 0.0 si aucun échantillon n'a pu être récupéré).

    Heuristique, pas un calcul validé statistiquement : `damping` limite l'ampleur
    de l'ajustement (30% de l'écart de force du lobby par défaut) pour qu'un seul
    match échantillonné ne fasse pas dévier la courbe simulée de façon disproportionnée."""
    candidate_indices = [i for i, m in enumerate(history) if m.match_id]
    if not candidate_indices:
        return np.zeros(len(history))

    step = max(1, len(candidate_indices) // n_samples)
    sample_indices = candidate_indices[::step][:n_samples]

    sample_points: list[tuple[int, float]] = []
    for i in sample_indices:
        point = history[i]
        try:
            match_data = fetch_match_detail(cfg, point.match_id)
        except Exception:
            continue

        players = match_data.get("data", {}).get("players", [])
        lobby_elo = average_lobby_elo(players, cfg.name, cfg.tag)
        if lobby_elo is None:
            continue

        diff = lobby_elo - point.elo
        sample_points.append((i, diff * damping))
        time.sleep(0.2)  # anti-rate-limit, même esprit que fetch_stored_history_paginated

    if not sample_points:
        return np.zeros(len(history))

    xs = [p[0] for p in sample_points]
    ys = [p[1] for p in sample_points]
    return np.interp(np.arange(len(history)), xs, ys)


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


def adaptive_state_width(n_matches: int) -> int:
    """Largeur de tranche d'elo adaptée à la richesse de l'historique. Avec peu de
    matchs, des tranches fines (25) laissent trop peu d'exemples par état pour être
    fiables (le modèle finit par tomber sur les replis génériques ci-dessous plus
    souvent que sur de vraies données) ; des tranches plus larges regroupent plus
    d'observations par état pour un historique court."""
    if n_matches < 30:
        return 50
    if n_matches < 100:
        return 35
    return 25


class ControlledMarkovChainOrder2:
    order = 2
    START = "start"

    def __init__(self, width: int):
        self.width = width
        self.counts: dict[str, dict[tuple, dict[int, int]]] = {
            "win": defaultdict(lambda: defaultdict(int)),
            "loss": defaultdict(lambda: defaultdict(int)),
        }
        # Repli de dernier recours : distribution globale des déplacements
        # (bucket_suivant - bucket_actuel) observés pour ce résultat, tous
        # états confondus. Utilisée quand une tranche d'elo n'a jamais été
        # visitée dans l'historique du joueur (voir transition_row).
        self.global_deltas: dict[str, dict[int, int]] = {
            "win": defaultdict(int),
            "loss": defaultdict(int),
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
            self.global_deltas[next_result][bucket_next - bucket_i] += 1

    def transition_row(self, result: str, aug_state: tuple) -> dict[int, float]:
        row = self.counts[result].get(aug_state)
        if row:
            total = sum(row.values())
            return {j: c / total for j, c in row.items()}

        bucket, _ = aug_state
        merged: dict[int, int] = defaultdict(int)
        for (b, _prev), sub_row in self.counts[result].items():
            if b == bucket:
                for j, c in sub_row.items():
                    merged[j] += c
        if merged:
            total = sum(merged.values())
            return {j: c / total for j, c in merged.items()}

        # Cette tranche n'a jamais été vue en historique pour ce résultat (ex: la
        # simulation dérive au-delà de tout ce que le joueur a réellement atteint).
        # Sans ce repli, on renverrait {bucket: 1.0} et la trajectoire simulée
        # resterait figée indéfiniment dès qu'elle atteint une tranche inédite.
        # On applique plutôt le profil de déplacement global du joueur pour ce
        # résultat, recentré sur la tranche actuelle, pour que la simulation
        # continue à bouger de façon plausible.
        deltas = self.global_deltas[result]
        if deltas:
            total = sum(deltas.values())
            return {bucket + delta: c / total for delta, c in deltas.items()}

        return {bucket: 1.0}  # dernier recours : vraiment aucune donnée disponible

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
    n_runs: int = 1000,
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

    # --- Palette et typographie ---
    COLOR_REAL = "#1d3557"       # bleu marine profond
    COLOR_SIM = "#e63946"        # rouge corail vif
    COLOR_FILL = "#e63946"
    COLOR_GRID = "#d0d0d0"
    COLOR_TEXT = "#2b2b2b"
    COLOR_BG = "#fbfbfd"

    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Verdana", "DejaVu Sans", "Arial"],
        "font.size": 11,
        "text.color": COLOR_TEXT,
        "axes.edgecolor": "#999999",
        "axes.labelcolor": COLOR_TEXT,
        "xtick.color": COLOR_TEXT,
        "ytick.color": COLOR_TEXT,
    })

    fig, ax = plt.subplots(figsize=(11, 6.5), facecolor=COLOR_BG)
    ax.set_facecolor(COLOR_BG)

    ax.plot([], [], color=COLOR_REAL, linewidth=2.6, label="Rang réel (couleur = rang)")  # entrée légende neutre
    for i in range(n - 1):
        seg_color = elo_to_color(real_elo[i], radiant_threshold_rr)
        ax.plot(
            [i, i + 1], [real_elo[i], real_elo[i + 1]],
            color=seg_color, linewidth=2.6, solid_capstyle="round", zorder=3,
        )
    x_sim = range(len(mean_sim))
    ax.plot(
        x_sim, mean_sim, label="Chaîne de Markov ordre 2, ajustée à la force du lobby (moyenne simulée)",
        color=COLOR_SIM, linewidth=1.6, solid_capstyle="round",
    )
    ax.fill_between(
        x_sim, mean_sim - std_sim, mean_sim + std_sim,
        color=COLOR_FILL, alpha=0.15, label="Écart-type simulé", linewidth=0,
    )

    # --- Axe des ordonnées en rangs plutôt qu'en elo brut ---
    y_min, y_max = ax.get_ylim()

    # Rangs classiques en dessous d'Immortel (paliers fixes de 100, RR reset)
    ticks = [t for t, _ in RANK_TIERS if y_min - 100 <= t <= min(y_max + 100, IMMORTAL_START)]
    labels = [name_ for t, name_ in RANK_TIERS if y_min - 100 <= t <= min(y_max + 100, IMMORTAL_START)]

    # À partir d'Immortel, on affiche un repère par palier significatif
    # (Immortel 1/2/3 puis Radiant au seuil live actuel), sans graduation
    # intermédiaire tous les 100 RR.
    immortel1_elo = IMMORTAL_START
    immortel2_elo = IMMORTAL_START + 100
    immortel3_elo = IMMORTAL_START + 200
    radiant_elo = IMMORTAL_START + radiant_threshold_rr

    for elo_mark, label in [
        (immortel1_elo, "Immortel 1"),
        (immortel2_elo, "Immortel 2"),
        (immortel3_elo, "Immortel 3"),
        (radiant_elo, "Radiant"),
    ]:
        if y_min - 100 <= elo_mark <= y_max + 100:
            ticks.append(elo_mark)
            labels.append(label)

    ax.set_yticks(ticks)
    ax.set_yticklabels(labels)
    ax.grid(axis="y", color=COLOR_GRID, linewidth=0.8, linestyle="-", alpha=0.6)
    ax.set_axisbelow(True)

    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#999999")
    ax.tick_params(axis="both", length=0)

    # --- Extremums (dont le max/min global garanti), annotés avec rang + RR ---
    extrema = find_local_extrema(real_elo)
    for idx, val, kind in extrema:
        offset = (0, 13) if kind == "max" else (0, -17)
        va = "bottom" if kind == "max" else "top"
        ax.annotate(
            format_rank_rr(val, radiant_threshold_rr),
            xy=(idx, val),
            xytext=offset,
            textcoords="offset points",
            ha="center",
            va=va,
            fontsize=8,
            color=COLOR_TEXT,
            fontweight="medium",
            arrowprops=dict(arrowstyle="-", color="#aaaaaa", lw=0.8),
        )
        ax.scatter([idx], [val], s=18, color=COLOR_REAL, zorder=5, edgecolors=COLOR_BG, linewidths=0.8)

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
        fontsize=11,
        fontweight="bold",
        color=COLOR_SIM,
    )

    ax.set_xlabel("Numéro de match", fontsize=10.5, labelpad=8)
    ax.set_ylabel("Rang", fontsize=10.5, labelpad=8)
    ax.set_title(f"Progression MMR de {name}#{tag}", fontsize=15, fontweight="bold", color=COLOR_TEXT, pad=16)
    legend = ax.legend(loc="upper left", frameon=True, fontsize=9.5)
    legend.get_frame().set_facecolor(COLOR_BG)
    legend.get_frame().set_edgecolor("#dddddd")
    legend.get_frame().set_linewidth(0.8)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor=COLOR_BG)
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

    cfg.state_width = adaptive_state_width(len(history))

    # Échantillonne ~20 matchs pour ajuster le modèle à la force réelle du lobby
    # (voir compute_lobby_adjustment). La courbe "réelle" tracée plus bas reste
    # basée sur l'historique brut, non ajusté : seule la chaîne apprend sur les
    # valeurs recalibrées, pour que la simulation reflète la difficulté rencontrée.
    lobby_adjustment = compute_lobby_adjustment(history, cfg, n_samples=20)
    adjusted_history = [
        MatchPoint(
            date=m.date,
            elo=max(0, int(round(m.elo + lobby_adjustment[i]))),
            rr_delta=m.rr_delta,
            result=m.result,
            match_id=m.match_id,
        )
        for i, m in enumerate(history)
    ]

    start_state = to_state(history[0].elo, cfg.state_width)
    chain = ControlledMarkovChainOrder2(width=cfg.state_width)
    chain.fit(adjusted_history)
    cond_rates = conditional_win_rates(history)
    sims = simulate_order2(chain, start_state, len(history) - 1, cond_rates, n_runs=1000)

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
    @app_commands.checks.cooldown(1, 604800.0, key=lambda i: i.user.id)  # 1 utilisation / semaine / utilisateur
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
                "la vraie formule, ceci est une approximation."
            ),
            color=discord.Color.red(),
        )
        embed.set_image(url="attachment://mmr_progression.png")
        try:
            await interaction.followup.send(embed=embed, file=file)
        except (discord.HTTPException, ConnectionError, OSError):
            pass  # coupure réseau transitoire, rien à faire de plus

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            retry_after = int(error.retry_after)
            days, rest = divmod(retry_after, 86400)
            hours, rest = divmod(rest, 3600)
            minutes = rest // 60

            parts = []
            if days:
                parts.append(f"{days}j")
            if hours:
                parts.append(f"{hours}h")
            if minutes and not days:  # évite d'afficher les minutes si on est déjà à plusieurs jours
                parts.append(f"{minutes}m")
            delay_str = " ".join(parts) if parts else "quelques secondes"

            message = f"⏳ Tu pourras réutiliser cette commande dans {delay_str}."
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(message, ephemeral=True)
                else:
                    await interaction.response.send_message(message, ephemeral=True)
            except (discord.HTTPException, ConnectionError, OSError):
                pass
        else:
            raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(MMRMarkov(bot))