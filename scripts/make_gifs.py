"""Render the animated figures used by the launch post.

Every GIF here is a *diagram*, not a screen recording.  The numbers in the AgentLab
figure are the verified `converge-vs-runaway` run published in docs/agentlab.md; nothing
is invented here.  Live SigNoz UI evidence stays as the real screenshots in docs/.

Usage:
    uv run python scripts/make_gifs.py                       # all figures
    uv run python scripts/make_gifs.py --terminal <log-file> # replay a captured CLI run
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from math import atan2, cos, hypot, sin
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).resolve().parents[1] / "docs"
WIDTH, HEIGHT = 960, 540
FPS = 10

# Shared with docs/onboarding/agent-mesh-radar.tex; keep the two in sync.
INK = "#1F2933"
SLATE = "#52606D"
ACCENT = "#2563EB"
ACCENTDK = "#1E3A8A"
LOOPRED = "#DC2626"
GOOD = "#059669"
AMBER = "#D97706"
PAPER = "#F8FAFC"
PANEL = "#EEF2F7"
LINE = "#CBD5E1"
NODE_FILL = "#DCE7FB"
NODE_HOT = "#F7C9C9"
NODE_OFF = "#E6EAEE"

_SANS = ("segoeui.ttf", "calibri.ttf", "arial.ttf", "DejaVuSans.ttf")
_SANS_BOLD = ("segoeuib.ttf", "calibrib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf")
_MONO = ("consola.ttf", "cour.ttf", "DejaVuSansMono.ttf")

Point = tuple[float, float]
Color = str | tuple[int, int, int]


def font(size: int, *, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    """Load the first available face, falling back to Pillow's bitmap default."""

    for name in _MONO if mono else (_SANS_BOLD if bold else _SANS):
        for directory in ("C:/Windows/Fonts", "/usr/share/fonts/truetype/dejavu", ""):
            try:
                return ImageFont.truetype(str(Path(directory) / name) if directory else name, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def ease(t: float) -> float:
    """Smoothstep, so motion starts and stops instead of snapping."""

    t = min(max(t, 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def blend(start: str, end: str, t: float) -> tuple[int, int, int]:
    a = [int(start[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(end[i : i + 2], 16) for i in (1, 3, 5)]
    t = min(max(t, 0.0), 1.0)
    return (
        round(a[0] + (b[0] - a[0]) * t),
        round(a[1] + (b[1] - a[1]) * t),
        round(a[2] + (b[2] - a[2]) * t),
    )


def new_frame(title: str, subtitle: str = "") -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 6), fill=ACCENT)
    draw.text((40, 32), title, font=font(27, bold=True), fill=ACCENTDK)
    if subtitle:
        draw.text((40, 70), subtitle, font=font(16), fill=SLATE)
    # Watermark lives in the dead space under the caption so it never collides.
    draw.text((WIDTH - 40, HEIGHT - 26), "Taraol", font=font(13, bold=True), fill=LINE, anchor="ra")
    return image, draw


def node(
    draw: ImageDraw.ImageDraw,
    center: Point,
    label: str,
    *,
    radius: int = 44,
    color: Color = ACCENT,
    fill: Color = NODE_FILL,
    dim: bool = False,
    width: int = 3,
    label_size: int = 15,
    label_below: bool = False,
) -> None:
    x, y = center
    draw.ellipse(
        (x - radius, y - radius, x + radius, y + radius),
        fill=PAPER if dim else fill,
        outline=LINE if dim else color,
        width=width,
    )
    # Small nodes can't hold "researcher" inside the rim, so their labels sit underneath.
    anchor = (x, y + radius + 12) if label_below else (x, y)
    draw.text(
        anchor,
        label,
        font=font(label_size, bold=True),
        fill=LINE if dim else (color if label_below else INK),
        anchor="mm",
    )


def _arrow_head(
    draw: ImageDraw.ImageDraw, tip: Point, angle: float, color: Color, width: int
) -> None:
    size = 4 + width * 2.6
    for offset in (2.5, -2.5):
        draw.line(
            (tip, (tip[0] + size * cos(angle + offset), tip[1] + size * sin(angle + offset))),
            fill=color,
            width=width,
        )


def _trim(start: Point, end: Point, pad: float) -> tuple[Point, Point]:
    """Pull an edge back from both node rims so arrowheads sit outside the circles."""

    dx, dy = end[0] - start[0], end[1] - start[1]
    length = hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    return (start[0] + ux * pad, start[1] + uy * pad), (end[0] - ux * pad, end[1] - uy * pad)


def edge(
    draw: ImageDraw.ImageDraw,
    start: Point,
    end: Point,
    *,
    color: Color = SLATE,
    width: int = 3,
    progress: float = 1.0,
    pad: float = 50.0,
    dot: float | None = None,
) -> None:
    """Straight forward edge, optionally drawn in progressively with a travelling dot."""

    a, b = _trim(start, end, pad)
    progress = min(max(progress, 0.0), 1.0)
    if progress <= 0.01:
        return
    tip = (a[0] + (b[0] - a[0]) * progress, a[1] + (b[1] - a[1]) * progress)
    draw.line((a, tip), fill=color, width=width)
    if progress > 0.98:
        _arrow_head(draw, b, _angle(a, b), color, width)
    if dot is not None:
        draw.ellipse(
            (
                a[0] + (b[0] - a[0]) * dot - 6,
                a[1] + (b[1] - a[1]) * dot - 6,
                a[0] + (b[0] - a[0]) * dot + 6,
                a[1] + (b[1] - a[1]) * dot + 6,
            ),
            fill=color,
        )


def back_edge(
    draw: ImageDraw.ImageDraw,
    start: Point,
    end: Point,
    *,
    color: Color = LOOPRED,
    width: int = 4,
    progress: float = 1.0,
    pad: float = 50.0,
    bow: float = 120.0,
    dot: float | None = None,
    label: str = "",
) -> None:
    """A bowed return edge.

    The re-delegation hop runs antiparallel to a forward edge, so drawing it straight
    would hide it underneath that edge.  Bowing it makes the cycle legible.
    """

    mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = hypot(dx, dy) or 1.0
    control = (mid[0] - dy / length * bow, mid[1] + dx / length * bow)

    curve = [
        (
            (1 - t) ** 2 * start[0] + 2 * (1 - t) * t * control[0] + t**2 * end[0],
            (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * control[1] + t**2 * end[1],
        )
        for t in (i / 60 for i in range(61))
    ]
    curve = [
        p
        for p in curve
        if hypot(p[0] - start[0], p[1] - start[1]) > pad
        and hypot(p[0] - end[0], p[1] - end[1]) > pad
    ]
    if len(curve) < 3:
        return
    progress = min(max(progress, 0.0), 1.0)
    shown = curve[: max(2, int(len(curve) * progress))]
    draw.line(shown, fill=color, width=width, joint="curve")
    if progress > 0.98:
        _arrow_head(draw, curve[-1], _angle(curve[-3], curve[-1]), color, width)
    if dot is not None:
        point = curve[min(int(dot * (len(curve) - 1)), len(curve) - 1)]
        draw.ellipse((point[0] - 6, point[1] - 6, point[0] + 6, point[1] + 6), fill=color)
    if label and progress > 0.98:
        apex = curve[len(curve) // 2]
        anchor = (apex[0], apex[1] - 18)
        box = draw.textbbox(anchor, label, font=font(14, mono=True), anchor="mm")
        draw.rectangle((box[0] - 6, box[1] - 3, box[2] + 6, box[3] + 3), fill=PAPER)
        draw.text(anchor, label, font=font(14, mono=True), fill=color, anchor="mm")


def _angle(a: Point, b: Point) -> float:
    return atan2(b[1] - a[1], b[0] - a[0])


def caption(draw: ImageDraw.ImageDraw, text: str, *, color: Color = INK) -> None:
    y = HEIGHT - 82
    draw.rounded_rectangle((40, y, WIDTH - 40, y + 44), radius=8, fill=PANEL)
    draw.text((62, y + 22), text, font=font(18, bold=True), fill=color, anchor="lm")


def encode(frames: Sequence[Image.Image], destination: Path) -> None:
    """Write frames through ffmpeg's palettegen/paletteuse for a clean, small GIF."""

    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is required to encode the GIFs")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as workdir:
        for index, frame in enumerate(frames):
            frame.save(Path(workdir) / f"f{index:04d}.png")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-framerate",
                str(FPS),
                "-i",
                str(Path(workdir) / "f%04d.png"),
                "-filter_complex",
                # stats_mode=full: the loop-red node tints occupy few pixels and
                # `diff` quantised them away to grey.
                (
                    "[0:v] split [a][b];[a] palettegen=stats_mode=full:max_colors=192 [p];"
                    "[b][p] paletteuse=dither=bayer:bayer_scale=4"
                ),
                "-loop",
                "0",
                str(destination),
            ],
            check=True,
        )
    kilobytes = destination.stat().st_size // 1024
    print(f"wrote {destination.name} ({len(frames)} frames, {kilobytes} KB)")


# --------------------------------------------------------------------------------------
# 1. mesh-topology.gif — the mesh assembling itself, then the back-edge closing the cycle
# --------------------------------------------------------------------------------------

MESH: dict[str, Point] = {
    "planner": (135, 322),
    "researcher": (330, 218),
    "writer": (525, 322),
    "critic": (720, 218),
    "router": (840, 400),
}
CHAIN = [
    ("planner", "researcher"),
    ("researcher", "writer"),
    ("writer", "critic"),
    ("critic", "router"),
]
# How far into the build-out each node stops being a placeholder.
ARRIVES = {"planner": 0.0, "researcher": 0.5, "writer": 1.5, "critic": 2.5, "router": 3.5}


def mesh_topology() -> list[Image.Image]:
    frames: list[Image.Image] = []
    per_edge, hold, loop_in, loop_hold = 8, 6, 12, 28
    total = per_edge * len(CHAIN) + hold + loop_in + loop_hold

    for index in range(total):
        image, draw = new_frame(
            "One trace, five services",
            "SigNoz draws this map from trace parent/child + service.name. No custom UI.",
        )
        built = index / per_edge
        loop_t = (index - per_edge * len(CHAIN) - hold) / loop_in
        for order, (src, dst) in enumerate(CHAIN):
            span = built - order
            edge(
                draw,
                MESH[src],
                MESH[dst],
                color=ACCENT,
                progress=ease(min(max(span, 0.0), 1.0)),
                dot=span % 1.0 if 0 < span < 1 else None,
            )
        if loop_t > 0:
            settled = loop_t >= 1
            pulse = 0.5 + 0.5 * sin(index / 2.2)
            back_edge(
                draw,
                MESH["critic"],
                MESH["writer"],
                color=LOOPRED if settled else blend(AMBER, LOOPRED, min(loop_t, 1.0)),
                progress=ease(min(loop_t, 1.0)),
                pad=52,
                bow=118,
                dot=(index / 10.0) % 1.0 if settled else None,
                label="re-delegates" if settled else "",
            )
            if settled:
                for name in ("writer", "critic"):
                    x, y = MESH[name]
                    glow = int(46 + 6 * pulse)
                    draw.ellipse((x - glow, y - glow, x + glow, y + glow), outline=LOOPRED, width=2)
        for name, position in MESH.items():
            looping = loop_t >= 1 and name in ("writer", "critic")
            node(
                draw,
                position,
                name,
                color=LOOPRED if looping else ACCENT,
                fill=NODE_HOT if looping else NODE_FILL,
                dim=built < ARRIVES[name],
            )
        if loop_t <= 0:
            caption(draw, "Each agent is its own OTel service; every hop carries traceparent.")
        else:
            caption(draw, "critic \u2192 writer re-delegates. The mesh has a cycle.", color=LOOPRED)
        frames.append(image)
    return frames


# --------------------------------------------------------------------------------------
# 2. traceparent-hop.gif — one trace id surviving five separate processes
# --------------------------------------------------------------------------------------

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
SPAN_IDS = [
    "00f067aa0ba902b7",
    "b7ad6b7169203331",
    "3c2f1a94ee5d80c1",
    "9d8e7f60a1b2c3d4",
    "5e4d3c2b1a098765",
]
PROCS = ["planner", "researcher", "writer", "critic", "router"]


def traceparent_hop() -> list[Image.Image]:
    frames: list[Image.Image] = []
    per_hop, tail = 13, 24
    box_w, gap, top = 156, 24, 196
    left = (WIDTH - (box_w * 5 + gap * 4)) / 2

    for index in range(per_hop * 4 + tail):
        image, draw = new_frame(
            "How one trace survives five separate processes",
            "inject_into(headers) on send, extract_from(headers) on receive  \u00b7  "
            "src/taraol/propagation.py",
        )
        hop = min(index / per_hop, 4.0)
        centers: list[Point] = []
        for order, name in enumerate(PROCS):
            x = left + order * (box_w + gap)
            reached = hop >= order - 0.05
            draw.rounded_rectangle(
                (x, top, x + box_w, top + 96),
                radius=10,
                fill=NODE_FILL if reached else PAPER,
                outline=ACCENT if reached else LINE,
                width=3 if reached else 2,
            )
            draw.text(
                (x + box_w / 2, top + 34),
                name,
                font=font(17, bold=True),
                fill=INK if reached else LINE,
                anchor="mm",
            )
            draw.text(
                (x + box_w / 2, top + 64),
                "own OTel service",
                font=font(12),
                fill=SLATE if reached else LINE,
                anchor="mm",
            )
            centers.append((x + box_w / 2, top + 48))

        current = min(int(hop), 3)
        fraction = min(max(hop - current, 0.0), 1.0)
        if index < per_hop * 4:
            start_x = centers[current][0] + box_w / 2 + 2
            end_x = centers[current + 1][0] - box_w / 2 - 2
            travel = start_x + (end_x - start_x) * ease(fraction)
            draw.line(((start_x, top + 48), (end_x, top + 48)), fill=LINE, width=2)
            draw.ellipse((travel - 9, top + 39, travel + 9, top + 57), fill=ACCENT)
            draw.text(
                (travel, top - 20),
                "traceparent",
                font=font(13, bold=True),
                fill=ACCENTDK,
                anchor="mm",
            )

        header_span = SPAN_IDS[min(int(hop + 0.5), 4)]
        draw.rounded_rectangle((70, 336, WIDTH - 70, 420), radius=10, fill=PANEL, outline=LINE)
        draw.text((92, 352), "traceparent header on the wire", font=font(13), fill=SLATE)
        x = 92
        for text, color in (
            ("00-", SLATE),
            (TRACE_ID, LOOPRED),
            ("-", SLATE),
            (header_span, ACCENT),
            ("-01", SLATE),
        ):
            draw.text((x, 380), text, font=font(17, mono=True), fill=color)
            x += draw.textlength(text, font=font(17, mono=True))
        draw.text(
            (WIDTH - 92, 352),
            "trace id constant   \u00b7   span id changes each hop",
            font=font(13),
            fill=SLATE,
            anchor="ra",
        )
        caption(
            draw,
            "ParentBased(ALWAYS_ON): a child never re-decides sampling, so the mesh "
            "never shatters.",
        )
        frames.append(image)
    return frames


# --------------------------------------------------------------------------------------
# 3. incident-beat.gif — the five beats of the demo, timed from a real captured run
# --------------------------------------------------------------------------------------

BEATS: list[tuple[str, str, str]] = [
    ("observe", "The mesh renders itself in the Service Map. Spend climbs.", ACCENTDK),
    ("detect", "writer \u2194 critic revise forever. loop_detected fires.", LOOPRED),
    ("contain", "The writer \u2192 critic edge breaker trips OPEN.", AMBER),
    ("enforce", "Alert \u2192 controller pauses the agent. agent_paused audit.", AMBER),
    ("result", "Spend flatlines. Every action is itself telemetry.", GOOD),
]
FINAL_COST = 0.0266

MINI: dict[str, Point] = {
    "planner": (96, 330),
    "researcher": (180, 254),
    "writer": (262, 336),
    "critic": (348, 254),
    "router": (416, 350),
}


def _cost_curve(t: float) -> float:
    """Climbing spend that accelerates during the loop and stops dead at the pause."""

    if t < 0.32:
        return 0.22 * (t / 0.32)
    if t < 0.62:
        return 0.22 + 0.62 * ((t - 0.32) / 0.30) ** 1.7
    return 0.84


def incident_beat() -> list[Image.Image]:
    frames: list[Image.Image] = []
    per_beat = 22
    total = per_beat * len(BEATS)

    for index in range(total):
        beat = min(index // per_beat, len(BEATS) - 1)
        window, text, color = BEATS[beat]
        image, draw = new_frame(
            "A runaway agent loop, detected and contained",
            "Detection reads telemetry, not application code \u00b7 docs/self-defense.md",
        )

        rail_y = 132
        draw.line(((40, rail_y), (WIDTH - 40, rail_y)), fill=LINE, width=4)
        draw.line(
            ((40, rail_y), (40 + (WIDTH - 80) * ((index + 1) / total), rail_y)), fill=color, width=4
        )
        for order in range(len(BEATS)):
            x = 40 + (WIDTH - 80) * (order / (len(BEATS) - 1))
            done = order <= beat
            draw.ellipse(
                (x - 7, rail_y - 7, x + 7, rail_y + 7),
                fill=color if done else PAPER,
                outline=color if done else LINE,
                width=3,
            )
        draw.text((40, rail_y + 14), window, font=font(14, bold=True), fill=color)

        # left panel: the mesh
        draw.rounded_rectangle((40, 176, 470, 424), radius=12, fill="#FFFFFF", outline=LINE)
        draw.text((60, 190), "APM \u2192 Service Map", font=font(14, bold=True), fill=SLATE)
        for src, dst in CHAIN:
            edge(draw, MINI[src], MINI[dst], color=ACCENT, width=2, pad=27)
        if beat >= 1:
            cut = beat >= 2
            back_edge(
                draw,
                MINI["critic"],
                MINI["writer"],
                color=LINE if cut else blend(AMBER, LOOPRED, 0.55 + 0.45 * sin(index / 2.0)),
                width=3,
                pad=28,
                bow=52,
                dot=None if cut else (index / 8.0) % 1.0,
            )
        if beat >= 2:
            # The breaker cuts one edge, not the whole agent: mark the hop itself.
            wx, wy = MINI["writer"]
            cx, cy = MINI["critic"]
            mx, my = (wx + cx) / 2, (wy + cy) / 2
            draw.line(((mx - 9, my - 9), (mx + 9, my + 9)), fill=AMBER, width=4)
            draw.line(((mx - 9, my + 9), (mx + 9, my - 9)), fill=AMBER, width=4)
            # Status chip in the panel's dead space; beside the X it collides with `critic`.
            draw.text(
                (60, 400), "writer → critic  ·  breaker OPEN", font=font(12, bold=True), fill=AMBER
            )
        for name, position in MINI.items():
            hot = beat >= 1 and name in ("writer", "critic")
            stopped = beat >= 3 and name == "writer"
            node(
                draw,
                position,
                name,
                radius=22,
                width=2,
                label_size=13,
                label_below=True,
                color=SLATE if stopped else (LOOPRED if hot else ACCENT),
                fill=NODE_OFF if stopped else (NODE_HOT if hot else NODE_FILL),
            )
        if beat >= 3:
            x, y = MINI["writer"]
            draw.text((x, y + 50), "PAUSED", font=font(11, bold=True), fill=SLATE, anchor="mm")

        # right panel: the conversation-budget chart
        draw.rounded_rectangle((494, 176, WIDTH - 40, 424), radius=12, fill="#FFFFFF", outline=LINE)
        draw.text((514, 190), "Conversation budget", font=font(14, bold=True), fill=SLATE)
        spend = _cost_curve(index / total) * FINAL_COST / 0.84
        draw.text(
            (WIDTH - 62, 188),
            f"${spend:.4f}",
            font=font(23, bold=True),
            fill=GOOD if beat >= 4 else ACCENTDK,
            anchor="ra",
        )
        plot = (526, 236, WIDTH - 62, 396)
        for step in range(1, 4):
            gy = plot[1] + (plot[3] - plot[1]) * step / 4
            draw.line(((plot[0], gy), (plot[2], gy)), fill=PANEL, width=1)
        draw.line(((plot[0], plot[3]), (plot[2], plot[3])), fill=LINE, width=2)
        draw.line(((plot[0], plot[1]), (plot[0], plot[3])), fill=LINE, width=2)
        budget_y = plot[3] - (plot[3] - plot[1]) * 0.9
        draw.line(((plot[0], budget_y), (plot[2], budget_y)), fill=LOOPRED, width=2)
        draw.text(
            (plot[0] + 8, budget_y - 8),
            "budget",
            font=font(12, bold=True),
            fill=LOOPRED,
            anchor="lb",
        )
        points = [
            (
                plot[0] + (plot[2] - plot[0]) * (step / total),
                plot[3] - (plot[3] - plot[1]) * _cost_curve(step / total),
            )
            for step in range(index + 1)
        ]
        if len(points) > 1:
            draw.line(points, fill=ACCENT, width=3, joint="curve")
            head = points[-1]
            draw.ellipse((head[0] - 5, head[1] - 5, head[0] + 5, head[1] + 5), fill=ACCENT)
        if beat >= 4:
            draw.text(
                (points[-1][0] - 4, points[-1][1] + 22),
                "flatlined",
                font=font(13, bold=True),
                fill=GOOD,
                anchor="ra",
            )

        caption(draw, text, color=color)
        frames.append(image)
    return frames


# --------------------------------------------------------------------------------------
# 4. agentlab-compare.gif — the published converge-vs-runaway run, drawn out
# --------------------------------------------------------------------------------------

# Verbatim from the verified run published in docs/agentlab.md.
ARMS: list[tuple[str, float, int, int, int, int, float]] = [
    # name, cost usd, tokens, avg ms, loops, breaker trips, health
    ("baseline", 0.0116, 4127, 42460, 0, 0, 91.5),
    ("runaway", 0.0266, 9457, 130972, 1, 1, 58.8),
]
METRICS: list[tuple[str, int, str]] = [
    ("cost (USD)", 0, "${:.4f}"),
    ("tokens", 1, "{:,}"),
    ("avg latency", 2, "{:,} ms"),
    ("runaway loops", 3, "{}"),
    ("breaker trips", 4, "{}"),
]


def agentlab_compare() -> list[Image.Image]:
    frames: list[Image.Image] = []
    per_metric, tail = 15, 30
    total = per_metric * len(METRICS) + tail
    left, row_h, top = 300, 52, 190
    bar_max = 430

    for index in range(total):
        image, draw = new_frame(
            "Same workload, two designs. Which one ships?",
            "AgentLab compares operational telemetry, not answer quality · docs/agentlab.md",
        )
        draw.text((left, top - 30), "baseline", font=font(15, bold=True), fill=GOOD)
        draw.text((left + 150, top - 30), "runaway", font=font(15, bold=True), fill=LOOPRED)

        for order, (title, slot, fmt) in enumerate(METRICS):
            reveal = ease(min(max(index / per_metric - order, 0.0), 1.0))
            if reveal <= 0.01:
                continue
            y = top + order * row_h
            draw.text((60, y + 12), title, font=font(15, bold=True), fill=SLATE)
            values = [arm[slot + 1] for arm in ARMS]
            peak = max(values) or 1
            for arm_index, arm in enumerate(ARMS):
                value = arm[slot + 1]
                colour = GOOD if arm_index == 0 else LOOPRED
                width = bar_max * (value / peak) * reveal
                bar_y = y + arm_index * 13
                draw.rounded_rectangle(
                    (left, bar_y, left + max(width, 2), bar_y + 10), radius=3, fill=colour
                )
                if reveal > 0.97:
                    text = fmt.format(value)
                    draw.text(
                        (left + bar_max + 14, bar_y + 5), text, font=font(13), fill=INK, anchor="lm"
                    )

        if index >= per_metric * len(METRICS):
            fade = ease((index - per_metric * len(METRICS)) / 8)
            box = (60, 452, WIDTH - 60, 500)
            draw.rounded_rectangle(
                box,
                radius=10,
                fill=blend(PAPER, "#DCFCE7", fade),
                outline=GOOD if fade > 0.6 else LINE,
                width=2,
            )
            if fade > 0.5:
                draw.text(
                    (80, 476),
                    "Operational Health   baseline 91.5   vs   runaway 58.8",
                    font=font(17, bold=True),
                    fill=INK,
                    anchor="lm",
                )
                draw.text(
                    (WIDTH - 80, 476),
                    "ship baseline",
                    font=font(17, bold=True),
                    fill=GOOD,
                    anchor="rm",
                )
        else:
            caption(draw, "2.3× the cost. 3× the latency. One loop, one breaker trip.")
        frames.append(image)
    return frames


# --------------------------------------------------------------------------------------
# terminal replay of a real captured run
# --------------------------------------------------------------------------------------

TERM_BG = "#10161D"
TERM_FG = "#D7DEE7"
_NOISE = (" Container", "#", " => ", "time=", "container ", " Image ", "EXIT=")
_COLS = 104


def terminal_replay(log: Path) -> list[Image.Image]:
    """Replay a captured `make demo` log. Real bytes only - nothing is synthesised."""

    kept = [
        line.rstrip()
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.startswith(_NOISE)
    ]
    lines: list[str] = []
    for line in kept:
        # Soft-wrap rather than truncate: a clipped word looks like a broken capture.
        while len(line) > _COLS:
            cut = line.rfind(" ", 0, _COLS)
            cut = cut if cut > 40 else _COLS
            lines.append(line[:cut])
            line = "  " + line[cut:].lstrip()
        lines.append(line)
    lines = lines[-24:]
    text_font = font(15, mono=True)
    frames: list[Image.Image] = []

    def render(visible: list[str]) -> Image.Image:
        image = Image.new("RGB", (WIDTH, HEIGHT), TERM_BG)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, WIDTH, 34), fill="#1B2530")
        for order, dot_color in enumerate(("#FF5F57", "#FEBC2E", "#28C840")):
            draw.ellipse((22 + order * 22, 12, 34 + order * 22, 24), fill=dot_color)
        draw.text(
            (WIDTH / 2, 17), "make demo", font=font(14, bold=True), fill="#8B98A5", anchor="mm"
        )
        for order, line in enumerate(visible):
            color = TERM_FG
            if line.startswith(">>>"):
                color = "#5FA8FF"
            elif line.startswith(("note:", "[local mode]")):
                color = "#F0B429"
            elif "completed in" in line or "Pause action" in line:
                color = "#3DDC97"
            elif "FAILED" in line:
                color = "#FF6B6B"
            draw.text((26, 50 + order * 19), line, font=text_font, fill=color)
        return image

    for count in range(1, len(lines) + 1):
        frames.append(render(lines[:count]))
        frames.append(render(lines[:count]))
    frames.extend([frames[-1]] * 30)
    return frames


BUILDERS: dict[str, Callable[[], list[Image.Image]]] = {
    "defend-beat.gif": incident_beat,
    "mesh-topology.gif": mesh_topology,
    "traceparent-hop.gif": traceparent_hop,
    "agentlab-compare.gif": agentlab_compare,
}


def main(argv: Sequence[str]) -> None:
    if "--terminal" in argv:
        log = Path(argv[argv.index("--terminal") + 1])
        if not log.exists():
            raise SystemExit(f"no captured run at {log}")
        encode(terminal_replay(log), OUT_DIR / "demo-terminal.gif")
        return
    for name, build in BUILDERS.items():
        encode(build(), OUT_DIR / name)


if __name__ == "__main__":
    main(sys.argv[1:])
