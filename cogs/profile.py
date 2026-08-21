import asyncio
import io
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
import aiohttp

import scoreboard_image
from valorant_api import (
    REGIONS,
    fetch_mmr,
    fetch_matchlist,
    fetch_image_bytes,
    format_peak_season,
    get_tier_icons,
    compute_player_match_stats,
)


def _format_started_at(raw: str) -> str:
    if not raw:
        return "Date inconnue"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return raw


def _format_duration(ms: int) -> str:
    total_seconds = (ms or 0) // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}m {seconds}s"


def _find_viewer_and_team(match: dict, name: str, tag: str):
    """Retrouve le joueur recherché dans un match et son équipe. Renvoie None si
    introuvable ou si le match n'a pas de structure d'équipes/manches exploitable
    (ex: certains modes hors compétitif/non classé)."""
    players = match.get("players", [])
    viewer = next(
        (
            p for p in players
            if (p.get("name") or "").lower() == name.lower() and (p.get("tag") or "").lower() == tag.lower()
        ),
        None,
    )
    if viewer is None:
        return None

    teams = match.get("teams", [])
    team = next((t for t in teams if t.get("team_id") == viewer.get("team_id")), None)
    if team is None or "rounds" not in team:
        return None
    return viewer, team


class MatchButton(discord.ui.Button):
    def __init__(self, match: dict, viewer_name: str, viewer_tag: str, region_value: str, *, label: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style)
        self.match = match
        self.viewer_name = viewer_name
        self.viewer_tag = viewer_tag
        self.region_value = region_value

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
        except (discord.HTTPException, ConnectionError, OSError):
            return

        async with aiohttp.ClientSession() as session:
            file, view = await build_match_scoreboard(session, self.match, self.viewer_name, self.viewer_tag, self.region_value)

        view.message = interaction.message
        try:
            await interaction.edit_original_response(embed=None, attachments=[file], view=view)
        except (discord.HTTPException, ConnectionError, OSError):
            pass


class ProfileView(discord.ui.View):
    def __init__(self, matches: list, viewer_name: str, viewer_tag: str, region_value: str):
        super().__init__(timeout=300)
        self.message = None

        added = 0
        for match in matches:
            if added >= 5:
                break
            result = _find_viewer_and_team(match, viewer_name, viewer_tag)
            if result is None:
                continue

            _, team = result
            rounds = team.get("rounds", {})
            my_score = rounds.get("won", 0)
            opp_score = rounds.get("lost", 0)
            won = team.get("won", my_score > opp_score)
            map_name = match.get("metadata", {}).get("map", {}).get("name", "?")

            icon = "✅" if won else "❌"
            label = f"{icon} {my_score}-{opp_score} · {map_name}"[:80]
            style = discord.ButtonStyle.success if won else discord.ButtonStyle.danger

            self.add_item(MatchButton(match, viewer_name, viewer_tag, region_value, label=label, style=style))
            added += 1

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.HTTPException, discord.NotFound):
                pass


class PlayerSelect(discord.ui.Select):
    def __init__(self, players: list, region_value: str):
        self.players_by_value = {}
        options = []
        for i, p in enumerate(players):
            name = p.get("name")
            tag = p.get("tag")
            if not name or not tag:
                continue  # compte anonymisé/masqué : pas de profil consultable

            stats = p.get("stats", {})
            options.append(
                discord.SelectOption(
                    label=f"{name}#{tag}"[:100],
                    description=(
                        f"{p.get('agent', {}).get('name', '?')} · "
                        f"{stats.get('kills', 0)}/{stats.get('deaths', 0)}/{stats.get('assists', 0)}"
                    )[:100],
                    value=str(i),
                )
            )
            self.players_by_value[str(i)] = (name, tag)

        disabled = not options
        if disabled:
            options = [discord.SelectOption(label="Aucun profil consultable pour ce match", value="none")]

        super().__init__(placeholder="Voir le profil d'un joueur...", options=options, disabled=disabled)
        self.region_value = region_value

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        if value not in self.players_by_value:
            await interaction.response.defer()
            return

        name, tag = self.players_by_value[value]
        region_name = next((r.name for r in REGIONS if r.value == self.region_value), self.region_value)

        try:
            await interaction.response.defer()
        except (discord.HTTPException, ConnectionError, OSError):
            return

        async with aiohttp.ClientSession() as session:
            embed, view, error = await build_profile(session, name, tag, self.region_value, region_name)

        if error:
            try:
                await interaction.followup.send(error, ephemeral=True)
            except (discord.HTTPException, ConnectionError, OSError):
                pass
            return

        view.message = interaction.message
        try:
            await interaction.edit_original_response(embed=embed, view=view)
        except (discord.HTTPException, ConnectionError, OSError):
            pass


class MatchView(discord.ui.View):
    def __init__(self, players: list, region_value: str):
        super().__init__(timeout=300)
        self.message = None
        self.add_item(PlayerSelect(players, region_value))

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.HTTPException, discord.NotFound):
                pass


async def build_profile(session: aiohttp.ClientSession, name: str, tag: str, region_value: str, region_name: str):
    """Récupère rank + peak + 5 dernières parties classées, et construit l'embed/la vue du profil.
    Renvoie (embed, view, None) en cas de succès, ou (None, None, message_erreur) sinon."""
    try:
        mmr_payload = await fetch_mmr(session, name, tag, region_value)
    except aiohttp.ClientResponseError as e:
        if e.status == 404:
            return None, None, "Joueur introuvable. Vérifie le pseudo, le tag et la région."
        return None, None, f"Erreur de l'API Valorant (code {e.status})."
    except Exception as e:
        return None, None, f"Erreur lors de la récupération du profil : {e}"

    data = mmr_payload.get("data", {})
    current = data.get("current", {})
    if not current:
        return None, None, "Aucune donnée de rank disponible pour ce joueur."

    tier = current.get("tier", {})
    rank_name = tier.get("name", "Non classé")
    rr = current.get("rr", 0)
    elo = current.get("elo", "N/A")

    peak = data.get("peak", {})
    peak_tier_name = peak.get("tier", {}).get("name")
    peak_season = format_peak_season(peak.get("season", {}).get("short"))

    icons = await get_tier_icons(session)
    rank_icon = icons.get(tier.get("id"))

    matches = await fetch_matchlist(session, name, tag, region_value, size=5)

    embed = discord.Embed(
        title=f"🎯 Profil Valorant de {name}#{tag}",
        description=f"**{rank_name}** — {rr} RR",
        color=discord.Color.red(),
    )
    embed.add_field(name="Elo", value=str(elo), inline=True)
    embed.add_field(name="Région", value=region_name, inline=True)
    if peak_tier_name:
        embed.add_field(name="🏔️ Peak rank", value=f"{peak_tier_name} ({peak_season})", inline=True)
    if rank_icon:
        embed.set_thumbnail(url=rank_icon)

    view = ProfileView(matches, name, tag, region_value)
    embed.set_footer(
        text="Clique sur une partie pour voir le scoreboard." if view.children else "Aucune partie classée récente trouvée."
    )

    return embed, view, None


async def _fetch_player_rank_icons(session: aiohttp.ClientSession, players: list, region_value: str) -> dict:
    """Récupère le rang live actuel + peak (et leurs icônes) pour chaque joueur nommé
    d'un match. Renvoie {(name.lower(), tag.lower()): (current_icon_bytes, peak_icon_bytes)}.
    Un joueur dont la récupération échoue (compte introuvable, API en erreur...) obtient
    simplement (None, None) : ça n'empêche pas d'afficher le reste du scoreboard."""
    icons = await get_tier_icons(session)
    named_players = [p for p in players if p.get("name") and p.get("tag")]

    async def fetch_one(p: dict):
        payload = await fetch_mmr(session, p["name"], p["tag"], region_value)
        data = payload.get("data", {})
        current_tier_id = data.get("current", {}).get("tier", {}).get("id")
        peak_tier_id = data.get("peak", {}).get("tier", {}).get("id")
        current_bytes = await fetch_image_bytes(session, icons.get(current_tier_id))
        peak_bytes = await fetch_image_bytes(session, icons.get(peak_tier_id))
        return current_bytes, peak_bytes

    results = await asyncio.gather(*(fetch_one(p) for p in named_players), return_exceptions=True)

    icon_map = {}
    for p, result in zip(named_players, results):
        key = (p["name"].lower(), p["tag"].lower())
        icon_map[key] = (None, None) if isinstance(result, Exception) else result
    return icon_map


async def build_match_scoreboard(session: aiohttp.ClientSession, match: dict, viewer_name: str, viewer_tag: str, region_value: str):
    """Construit l'image du scoreboard d'un match (avec icônes de rang live + peak par
    joueur) et sa vue de navigation. Renvoie (discord.File, MatchView)."""
    metadata = match.get("metadata", {})
    map_name = metadata.get("map", {}).get("name", "Carte inconnue")
    queue = metadata.get("queue") or {}
    mode_name = queue.get("name") or queue.get("mode_type") or "Mode inconnu"
    started_at = _format_started_at(metadata.get("started_at"))
    duration = _format_duration(metadata.get("game_length_in_ms", 0))

    players = match.get("players", [])
    teams = match.get("teams", [])

    result = _find_viewer_and_team(match, viewer_name, viewer_tag)
    if result is not None:
        _, viewer_team = result
        rounds = viewer_team.get("rounds", {})
        rounds_played = rounds.get("won", 0) + rounds.get("lost", 0)
    elif teams:
        rounds = teams[0].get("rounds", {})
        rounds_played = rounds.get("won", 0) + rounds.get("lost", 0)
    else:
        rounds_played = 0

    score_line = ""
    if len(teams) == 2:
        score_line = f"{teams[0].get('rounds', {}).get('won', '?')} : {teams[1].get('rounds', {}).get('won', '?')}"

    icon_map = await _fetch_player_rank_icons(session, players, region_value)

    team_labels = {"Red": "Équipe Red", "Blue": "Équipe Blue"}
    team_data_list = []
    for team in teams:
        team_players = [p for p in players if p.get("team_id") == team.get("team_id")]
        if not team_players:
            continue

        rows = []
        for p in team_players:
            s = compute_player_match_stats(p, rounds_played)
            key = ((p.get("name") or "").lower(), (p.get("tag") or "").lower())
            current_bytes, peak_bytes = icon_map.get(key, (None, None))
            rows.append(
                scoreboard_image.PlayerRow(
                    name=p.get("name") or "Inconnu",
                    tag=p.get("tag") or "????",
                    agent=p.get("agent", {}).get("name") or "?",
                    kills=s["kills"],
                    deaths=s["deaths"],
                    assists=s["assists"],
                    acs=s["acs"],
                    adr=s["adr"],
                    hs_percent=s["hs_percent"],
                    current_icon_bytes=current_bytes,
                    peak_icon_bytes=peak_bytes,
                )
            )

        team_data_list.append(
            scoreboard_image.TeamData(
                label=team_labels.get(team.get("team_id"), f"Équipe {team.get('team_id', '?')}"),
                won=bool(team.get("won")),
                rounds_won=team.get("rounds", {}).get("won", 0),
                team_id=team.get("team_id", ""),
                players=rows,
            )
        )

    title = f"{map_name} — {mode_name}" + (f"   {score_line}" if score_line else "")
    subtitle = f"{started_at} · {duration}"

    png_bytes = await asyncio.to_thread(scoreboard_image.render_scoreboard, title, subtitle, team_data_list)

    file = discord.File(io.BytesIO(png_bytes), filename="scoreboard.png")
    view = MatchView(players, region_value)
    return file, view


class Profile(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="profil", description="Affiche le profil Valorant complet d'un joueur (rank, peak, dernières parties classées)")
    @app_commands.describe(
        pseudo="Riot ID complet, format Pseudo#Tag (ex: Dodo#1234)",
        region="Région du compte",
    )
    @app_commands.choices(region=REGIONS)
    async def profil(self, interaction: discord.Interaction, pseudo: str, region: app_commands.Choice[str]):
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
            return

        async with aiohttp.ClientSession() as session:
            embed, view, error = await build_profile(session, name, tag, region.value, region.name)

        if error:
            await interaction.followup.send(error)
            return

        try:
            message = await interaction.followup.send(embed=embed, view=view)
            view.message = message
        except (discord.HTTPException, ConnectionError, OSError):
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Profile(bot))
