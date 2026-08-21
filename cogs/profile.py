from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
import aiohttp

from valorant_api import (
    REGIONS,
    fetch_mmr,
    fetch_matchlist,
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


def _format_name_tag(name: str, tag: str, width: int = 20) -> str:
    """Tronque le pseudo si besoin, mais garde toujours le tag entier lisible."""
    name = name or "Inconnu"
    tag_part = f"#{tag or '????'}"
    max_name_len = max(1, width - len(tag_part))
    return f"{name[:max_name_len]}{tag_part}"[:width]


def _build_team_table(players: list, rounds_played: int) -> str:
    header = f"{'Joueur':<20}{'Agent':<10}{'ACS':>5}{'K':>4}{'D':>4}{'A':>4}{'ADR':>6}{'HS%':>6}"
    lines = [header]
    for p in players:
        name = _format_name_tag(p.get("name"), p.get("tag"))
        agent = (p.get("agent", {}).get("name") or "?")[:9]
        s = compute_player_match_stats(p, rounds_played)
        lines.append(
            f"{name:<20}{agent:<10}{s['acs']:>5.0f}{s['kills']:>4}{s['deaths']:>4}{s['assists']:>4}"
            f"{s['adr']:>6.0f}{s['hs_percent']:>5.0f}%"
        )
    return "\n".join(lines)


class MatchButton(discord.ui.Button):
    def __init__(self, match: dict, viewer_name: str, viewer_tag: str, region_value: str, *, label: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style)
        self.match = match
        self.viewer_name = viewer_name
        self.viewer_tag = viewer_tag
        self.region_value = region_value

    async def callback(self, interaction: discord.Interaction):
        embed, view = build_match_embed(self.match, self.viewer_name, self.viewer_tag, self.region_value)
        view.message = interaction.message
        try:
            await interaction.response.edit_message(embed=embed, view=view)
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
    """Récupère rank + peak + 5 derniers matchs, et construit l'embed/la vue du profil.
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
        text="Clique sur une partie pour voir le scoreboard." if view.children else "Aucun match récent trouvé."
    )

    return embed, view, None


def build_match_embed(match: dict, viewer_name: str, viewer_tag: str, region_value: str):
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
        score_line = f"**{teams[0].get('rounds', {}).get('won', '?')} : {teams[1].get('rounds', {}).get('won', '?')}**"

    embed = discord.Embed(
        title=f"🗺️ {map_name} — {mode_name}",
        description=f"{score_line}\n🕒 {started_at} · ⏱️ {duration}".strip(),
        color=discord.Color.blurple(),
    )

    for team in teams:
        team_players = [p for p in players if p.get("team_id") == team.get("team_id")]
        if not team_players:
            continue
        rounds = team.get("rounds", {})
        trophy = "🏆 " if team.get("won") else ""
        header = f"{trophy}Équipe {team.get('team_id', '?')} — {rounds.get('won', '?')} manches"
        table = _build_team_table(team_players, rounds_played)
        embed.add_field(name=header, value=f"```{table}```", inline=False)

    view = MatchView(players, region_value)
    return embed, view


class Profile(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="profil", description="Affiche le profil Valorant complet d'un joueur (rank, peak, derniers matchs)")
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
