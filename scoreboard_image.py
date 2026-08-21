"""Rendu du scoreboard d'un match Valorant en image (façon tracker.gg).

Module purement synchrone (aucun appel réseau ici) : les icônes de rang sont
déjà téléchargées en amont (bytes bruts) et décodées ici. Pensé pour tourner
dans un thread (asyncio.to_thread) vu que la composition d'image est
bloquante, comme /mmr le fait déjà pour ses graphiques matplotlib.
"""

import io
from dataclasses import dataclass, field
from typing import Optional

import matplotlib
from PIL import Image, ImageDraw, ImageFont

WIDTH = 700
PADDING = 20
ICON_SIZE = 30
ROW_HEIGHT = 46
TEAM_HEADER_HEIGHT = 34
TEAM_GAP = 16

BG_COLOR = (18, 20, 28, 255)
ROW_COLOR = (26, 29, 40, 255)
HEADER_BG = (32, 35, 48, 255)
TEXT_COLOR = (235, 236, 240, 255)
MUTED_COLOR = (150, 156, 172, 255)
WIN_COLOR = (100, 210, 130, 255)
LOSE_COLOR = (225, 95, 95, 255)
TEAM_ACCENT_COLORS = {"Red": (225, 95, 95, 255), "Blue": (95, 150, 225, 255)}
DEFAULT_ACCENT_COLOR = (150, 156, 172, 255)

# Colonnes (x de départ), calculées une fois pour tout aligner comme un vrai tableau
COL_ICON_1 = PADDING + 12
COL_ICON_2 = COL_ICON_1 + ICON_SIZE + 4
COL_NAME = COL_ICON_2 + ICON_SIZE + 16
COL_NAME_WIDTH = 195
COL_AGENT = COL_NAME + COL_NAME_WIDTH
COL_AGENT_WIDTH = 85
COL_ACS = COL_AGENT + COL_AGENT_WIDTH
COL_ACS_WIDTH = 55
COL_KDA = COL_ACS + COL_ACS_WIDTH
COL_KDA_WIDTH = 85
COL_ADR = COL_KDA + COL_KDA_WIDTH
COL_ADR_WIDTH = 65
COL_HS = COL_ADR + COL_ADR_WIDTH
COL_HS_WIDTH = 60

_FONT_CACHE: dict = {}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    if key not in _FONT_CACHE:
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        path = f"{matplotlib.get_data_path()}/fonts/ttf/{name}"
        _FONT_CACHE[key] = ImageFont.truetype(path, size)
    return _FONT_CACHE[key]


def _load_icon(data: Optional[bytes]) -> Optional[Image.Image]:
    if not data:
        return None
    try:
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        return img.resize((ICON_SIZE, ICON_SIZE))
    except Exception:
        return None


@dataclass
class PlayerRow:
    name: str
    tag: str
    agent: str
    kills: int
    deaths: int
    assists: int
    acs: float
    adr: float
    hs_percent: float
    current_icon_bytes: Optional[bytes] = None
    peak_icon_bytes: Optional[bytes] = None


@dataclass
class TeamData:
    label: str
    won: bool
    rounds_won: int
    team_id: str = ""
    players: list = field(default_factory=list)


def _draw_right_aligned(draw: ImageDraw.ImageDraw, text: str, right_x: int, y: int, font, fill):
    w = draw.textlength(text, font=font)
    draw.text((right_x - w, y), text, font=font, fill=fill)


def _fit_name_tag(draw: ImageDraw.ImageDraw, name: str, tag: str, font, max_width: int) -> str:
    """Raccourcit le pseudo si besoin, mais garde toujours le tag entier lisible."""
    full = f"{name}#{tag}"
    if draw.textlength(full, font=font) <= max_width:
        return full
    while name and draw.textlength(f"{name}#{tag}", font=font) > max_width:
        name = name[:-1]
    return f"{name}#{tag}"


def _draw_team(draw: ImageDraw.ImageDraw, canvas: Image.Image, team: TeamData, y: int) -> int:
    font_bold = _font(15, bold=True)
    font_regular = _font(13)

    header_color = WIN_COLOR if team.won else LOSE_COLOR
    accent = TEAM_ACCENT_COLORS.get(team.team_id, DEFAULT_ACCENT_COLOR)
    draw.rectangle([PADDING, y, WIDTH - PADDING, y + TEAM_HEADER_HEIGHT], fill=HEADER_BG)
    draw.rectangle([PADDING, y, PADDING + 4, y + TEAM_HEADER_HEIGHT], fill=accent)
    result_text = "Victoire" if team.won else "Défaite"
    draw.text(
        (PADDING + 16, y + 8),
        f"{team.label} — {team.rounds_won} manches",
        font=font_bold,
        fill=TEXT_COLOR,
    )
    result_w = draw.textlength(result_text, font=font_bold)
    draw.text((WIDTH - PADDING - 10 - result_w, y + 8), result_text, font=font_bold, fill=header_color)
    y += TEAM_HEADER_HEIGHT + 6

    ranked = sorted(team.players, key=lambda p: p.acs, reverse=True)
    for p in ranked:
        row_top = y
        draw.rectangle([PADDING, row_top, WIDTH - PADDING, row_top + ROW_HEIGHT - 6], fill=ROW_COLOR)

        icon_y = row_top + (ROW_HEIGHT - 6 - ICON_SIZE) // 2
        current_icon = _load_icon(p.current_icon_bytes)
        if current_icon:
            canvas.paste(current_icon, (COL_ICON_1, icon_y), current_icon)
        peak_icon = _load_icon(p.peak_icon_bytes)
        if peak_icon:
            canvas.paste(peak_icon, (COL_ICON_2, icon_y), peak_icon)

        name_text = _fit_name_tag(draw, p.name, p.tag, font_bold, COL_NAME_WIDTH - 6)
        draw.text((COL_NAME, row_top + 13), name_text, font=font_bold, fill=TEXT_COLOR)

        draw.text((COL_AGENT, row_top + 13), p.agent, font=font_regular, fill=MUTED_COLOR)
        _draw_right_aligned(draw, f"{p.acs:.0f}", COL_ACS + COL_ACS_WIDTH, row_top + 13, font_bold, TEXT_COLOR)
        _draw_right_aligned(
            draw, f"{p.kills}/{p.deaths}/{p.assists}", COL_KDA + COL_KDA_WIDTH, row_top + 13, font_regular, TEXT_COLOR
        )
        _draw_right_aligned(draw, f"{p.adr:.0f}", COL_ADR + COL_ADR_WIDTH, row_top + 13, font_regular, MUTED_COLOR)
        _draw_right_aligned(draw, f"{p.hs_percent:.0f}%", COL_HS + COL_HS_WIDTH, row_top + 13, font_regular, MUTED_COLOR)

        y += ROW_HEIGHT

    return y + TEAM_GAP


def render_scoreboard(title: str, subtitle: str, teams: list) -> bytes:
    header_height = 96
    body_height = sum(TEAM_HEADER_HEIGHT + 6 + len(t.players) * ROW_HEIGHT + TEAM_GAP for t in teams)
    height = header_height + body_height + PADDING

    canvas = Image.new("RGBA", (WIDTH, height), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    font_title = _font(20, bold=True)
    font_subtitle = _font(13)
    font_legend = _font(11)
    draw.text((PADDING, 14), title, font=font_title, fill=TEXT_COLOR)
    draw.text((PADDING, 42), subtitle, font=font_subtitle, fill=MUTED_COLOR)
    draw.text((COL_ICON_1, 64), "Actuel/Peak", font=font_legend, fill=MUTED_COLOR)

    y = header_height
    for team in teams:
        y = _draw_team(draw, canvas, team, y)

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()
