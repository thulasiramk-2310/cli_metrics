#!/usr/bin/env python3
"""Generate the animated demo SVG used in the README.

    python3 scripts/make_demo_svg.py

Renders a run of dashboard frames against synthetic metrics and writes them into
one SVG, where CSS cycles the frames. Animated SVG is used rather than a GIF
because it stays sharp at any zoom, weighs a fraction as much, and diffs as text.

No JavaScript: GitHub renders README images in a context where scripts never
run, but CSS animation does.
"""

import math
import os
import sys

from rich.cells import cell_len
from rich.console import Console

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from sysdash.cli import CLIDashboard  # noqa: E402


def _load_make_metrics():
    """Pull make_metrics out of the test fixtures, by file path.

    "import tests.conftest" is not reliable: tests/ has no __init__.py, so it is
    only a namespace portion, and any regular "tests" package installed in
    site-packages wins over it.
    """
    import importlib.util

    path = os.path.join(ROOT, "tests", "conftest.py")
    spec = importlib.util.spec_from_file_location("_sysdash_test_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.make_metrics


make_metrics = _load_make_metrics()

COLUMNS, ROWS = 112, 30
FRAMES = 12
SECONDS_PER_FRAME = 0.7

# Terminal metrics for 14px DejaVu Sans Mono.
FONT_SIZE = 14
CHAR_WIDTH = 8.4
LINE_HEIGHT = 17.5
PADDING = 16
TITLE_BAR = 28

BACKGROUND = "#12141a"
FOREGROUND = "#c9d1d9"


def freeze_clock():
    """Pin the header clock so the image is not stamped with build time."""
    import datetime as datetime_module

    import sysdash.cli

    fixed = datetime_module.datetime(2026, 1, 1, 9, 41, 0)

    class FrozenDateTime(datetime_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    sysdash.cli.datetime = FrozenDateTime


def build_frames():
    """Render FRAMES dashboards, each a list of lines of (text, style) runs."""
    # A real hostname and a live clock would both be baked into the image.
    dashboard = CLIDashboard(hostname="archbox")
    dashboard._sampler = "disabled"
    freeze_clock()

    state = {"tick": 0}

    def metrics():
        """Synthetic readings that visibly move, so the graph has a shape."""
        tick = state["tick"]
        data = make_metrics()
        cpu = 35 + 30 * math.sin(tick / 2.4)
        data["cpu"]["total"] = cpu
        data["cpu"]["per_core"] = [
            max(0.0, min(100.0, cpu + 35 * math.sin(tick / 1.7 + core)))
            for core in range(16)
        ]
        data["memory"]["percent"] = 62 + 8 * math.sin(tick / 3.1)
        data["network"]["bytes_recv_rate"] = (120 + 90 * math.sin(tick / 1.3)) * 1024
        data["network"]["bytes_sent_rate"] = (40 + 25 * math.sin(tick / 2.0)) * 1024
        for index, process in enumerate(data["processes"]):
            process["cpu"] = max(
                0.0, 48 - index * 4 + 9 * math.sin(tick / 1.5 + index)
            )
        return data

    dashboard.collector.collect_all = lambda **kwargs: metrics()
    dashboard._cached_processes = make_metrics()["processes"]

    # legacy_windows would substitute ASCII "+---+" for the box-drawing
    # characters, so the demo would not look like the real dashboard.
    console = Console(
        width=COLUMNS, height=ROWS, force_terminal=True,
        legacy_windows=False, color_system="truecolor",
    )
    options = console.options.update(width=COLUMNS, height=ROWS)
    # rich derives ascii_only from the console encoding, and on a cp1252 Windows
    # shell that swaps every box-drawing character for "+---+". The SVG carries
    # its own encoding, so state it outright.
    options.encoding = "utf-8"

    layout = dashboard.make_layout()
    # Warm the history so the first visible frame already has a trend line.
    for warmup in range(26):
        state["tick"] = warmup
        dashboard.update_dashboard(layout)

    frames = []
    for step in range(FRAMES):
        state["tick"] = 26 + step

        # Script a little interaction: select a process, then open help.
        if step == 5:
            dashboard.handle_key("down")
        elif step == 6:
            dashboard.handle_key("down")
        elif step == 8:
            dashboard._cached_processes = metrics()["processes"]
            dashboard.handle_key("k")
        elif step == 11:
            dashboard.handle_key("n")

        # The sampler is disabled here, so feed the process list by hand or it
        # would sit frozen while everything else moves.
        dashboard._cached_processes = metrics()["processes"]

        dashboard.update_dashboard(layout)
        frames.append(console.render_lines(layout, options, pad=True))

    return frames


def colour_of(style, attribute):
    """Hex colour for a segment style, or None to inherit the default."""
    colour = getattr(style, attribute, None) if style else None
    if colour is None:
        return None
    try:
        triplet = colour.get_truecolor()
    except Exception:
        return None
    return f"#{triplet.red:02x}{triplet.green:02x}{triplet.blue:02x}"


def escape(text):
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def merge_runs(segments):
    """Collapse neighbouring segments that share a style.

    Each run becomes one <tspan>; without this the graph's dotted field emits
    one element per character and the file triples in size.
    """
    runs = []
    for segment in segments:
        key = (
            colour_of(segment.style, "color"),
            colour_of(segment.style, "bgcolor"),
            bool(segment.style and segment.style.bold),
            bool(segment.style and segment.style.dim),
        )
        if runs and runs[-1][2] == key:
            runs[-1][0] += segment.text
        else:
            runs.append([segment.text, segment.style, key])
    return [(text, style) for text, style, _ in runs]


def render_frame(lines, index):
    """One frame as an SVG group."""
    parts = [f'<g class="f f{index}">']

    for row, segments in enumerate(lines):
        y = TITLE_BAR + PADDING + (row + 1) * LINE_HEIGHT - 4
        column = 0
        spans = []

        for text, style in merge_runs(segments):
            width = cell_len(text)
            if text.strip():
                x = PADDING + column * CHAR_WIDTH
                background = colour_of(style, "bgcolor")
                if background:
                    parts.append(
                        f'<rect x="{x:.1f}" y="{y - FONT_SIZE + 1:.1f}" '
                        f'width="{width * CHAR_WIDTH:.1f}" height="{LINE_HEIGHT:.1f}" '
                        f'fill="{background}"/>'
                    )
                attributes = [f'x="{x:.1f}"']
                foreground = colour_of(style, "color")
                if foreground:
                    attributes.append(f'fill="{foreground}"')
                if style and style.bold:
                    attributes.append('font-weight="bold"')
                if style and style.dim:
                    attributes.append('opacity="0.55"')
                spans.append(
                    f'<tspan {" ".join(attributes)}>{escape(text)}</tspan>'
                )
            column += width

        if spans:
            parts.append(f'<text y="{y:.1f}">{"".join(spans)}</text>')

    parts.append("</g>")
    return "".join(parts)


def main():
    frames = build_frames()
    duration = FRAMES * SECONDS_PER_FRAME
    visible = 100.0 / FRAMES

    width = COLUMNS * CHAR_WIDTH + PADDING * 2
    height = ROWS * LINE_HEIGHT + PADDING * 2 + TITLE_BAR

    # Each frame shares one keyframe cycle, offset by its own delay.
    delays = "".join(
        f".f{index}{{animation-delay:{index * SECONDS_PER_FRAME:.2f}s}}"
        for index in range(FRAMES)
    )
    style = (
        f"text{{font-family:'DejaVu Sans Mono','SFMono-Regular',Consolas,"
        f"'Liberation Mono',monospace;font-size:{FONT_SIZE}px;"
        f"white-space:pre;fill:{FOREGROUND}}}"
        f".f{{opacity:0;animation:frame {duration:.1f}s steps(1,end) infinite}}"
        f"@keyframes frame{{0%,{visible - 0.01:.2f}%{{opacity:1}}"
        f"{visible:.2f}%,100%{{opacity:0}}}}"
        f"{delays}"
        "@media (prefers-reduced-motion:reduce){"
        ".f{animation:none}.f0{opacity:1}}"
    )

    body = "".join(render_frame(lines, index) for index, lines in enumerate(frames))

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" '
        f'height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'font-size="{FONT_SIZE}">'
        f"<style>{style}</style>"
        f'<rect width="{width:.0f}" height="{height:.0f}" rx="10" fill="{BACKGROUND}"/>'
        f'<circle cx="22" cy="14" r="5" fill="#ff5f56"/>'
        f'<circle cx="40" cy="14" r="5" fill="#ffbd2e"/>'
        f'<circle cx="58" cy="14" r="5" fill="#27c93f"/>'
        f'<text x="{width / 2:.0f}" y="19" text-anchor="middle" '
        f'fill="#6e7681" font-size="12">sysdash</text>'
        f"{body}</svg>"
    )

    destination = os.path.join(
        os.path.dirname(__file__), "..", "docs", "demo.svg"
    )
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(destination, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(svg)

    size = os.path.getsize(destination)
    print(f"wrote {destination} ({size / 1024:.0f} KB, {len(frames)} frames)")


if __name__ == "__main__":
    main()
