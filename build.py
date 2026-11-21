"""Render dark_mode.svg and light_mode.svg for the Pxjjuzz profile card.

The card is a single ASCII portrait plus a terminal panel. Everything in the
panel is regenerated each run, so there is no patching of pre-made SVGs and no
risk of XML namespace damage.

Usage:
    python build.py            # fetch live stats (needs GITHUB_TOKEN / ACCESS_TOKEN)
    python build.py --offline  # render from cache/stats.json, never hit the API
    python build.py --sample   # render with fake numbers, writes to preview/
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
STATS_CACHE = CACHE / "stats.json"
REPO_CACHE = CACHE / "repos.json"
ASCII_FILE = ROOT / "ascii.txt"

LOGIN = "Pxjjuzz"
BIRTHDAY = date(2008, 1, 16)

ABOUT = {
    "os": "Windows 11, Android 15",
    "host": "SSCE Bangalore",
    "kernel": "BE AIML",
    "ide": "VS Code, Antigravity, OpenCode",
}
STACK = [
    ("Languages.Programming", "Python, C, JavaScript, TypeScript"),
    ("Languages.Computer", "HTML, CSS, JSON, YAML"),
    ("Languages.Real", "English, Hindi, Kannada"),
    ("Hobbies", "AI/ML, full-stack, video editing"),
]
PROJECTS = [
    ("AFTERGLOW", "desktop media player"),
    ("AEROBLEND-AI", "AI + NWP weather models"),
    ("VenueOne", "venue booking platform"),
    ("SNAPBREEDAI", "breed classifier, Streamlit"),
]

# ---------------------------------------------------------------------------
# canvas
# ---------------------------------------------------------------------------
W, H = 1240, 960
ART_X, ART_Y, ART_SIZE, ART_LEADING = 24, 24, 4.3, 5.85
PANEL_X = 620
PANEL_W = 590
DIVIDER_X = 596
PAD_TOP = 34

BODY = 19.5
ADVANCE = BODY * 0.55
ROW = 22.5

THEMES = {
    "dark": {
        "bg": "#0d1117",
        "frame": "#30363d",
        "text": "#c9d1d9",
        "key": "#ffa657",
        "value": "#a5d6ff",
        "muted": "#6e7681",
        "green": "#3fb950",
        "red": "#f85149",
        "accent": "#58a6ff",
        "track": "#21262d",
        "badge": "#161b22",
        "art": "#8b949e",
        "cursor": "#3fb950",
    },
    "light": {
        "bg": "#f6f8fa",
        "frame": "#d0d7de",
        "text": "#1f2328",
        "key": "#953800",
        "value": "#0a3069",
        "muted": "#6e7781",
        "green": "#1a7f37",
        "red": "#cf222e",
        "accent": "#0969da",
        "track": "#eaeef2",
        "badge": "#ffffff",
        "art": "#57606a",
        "cursor": "#1a7f37",
    },
}

STYLE = """@font-face {{
  src: local('Consolas'), local('Consolas Bold'), local('DejaVu Sans Mono');
  font-family: 'MonoFallback';
  font-display: swap;
  size-adjust: 109%;
}}
text, tspan {{ white-space: pre; }}
.section {{ letter-spacing: 2.6px; }}
@keyframes blink {{ 0%, 49% {{ opacity: 1; }} 50%, 100% {{ opacity: 0; }} }}
.cursor {{ animation: blink 1.1s steps(1, end) infinite; }}
@keyframes pulse {{ 0%, 100% {{ opacity: .35; }} 50% {{ opacity: 1; }} }}
.dot {{ animation: pulse 2.4s ease-in-out infinite; }}
"""


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def age(days_from_birth: date = BIRTHDAY, today: date | None = None) -> str:
    today = today or date.today()
    years = today.year - days_from_birth.year
    months = today.month - days_from_birth.month
    days = today.day - days_from_birth.day
    if days < 0:
        months -= 1
        prev = today.replace(day=1) - __import__("datetime").timedelta(days=1)
        days += prev.day
    if months < 0:
        years -= 1
        months += 12
    return f"{years}y {months}m {days}d"


def fmt(n: int) -> str:
    return f"{n:,}"


# ---------------------------------------------------------------------------
# artwork
# ---------------------------------------------------------------------------
# Light mode needs the ink density flipped, otherwise the portrait turns into a
# black blob on a white card.
RAMP = " .:-=+*#%@"
FLIP = {c: RAMP[len(RAMP) - 1 - i] for i, c in enumerate(RAMP)}


def load_art(invert: bool) -> list[str]:
    rows = [line.rstrip() for line in ASCII_FILE.read_text(encoding="utf-8").splitlines()]
    if invert:
        rows = ["".join(FLIP.get(c, c) for c in row) for row in rows]
    return rows


def art_block(rows: list[str], colour: str) -> str:
    spans = []
    y = ART_Y
    for row in rows:
        if row:
            spans.append(f'<tspan x="{ART_X}" y="{round(y, 2)}">{esc(row)}</tspan>')
        y += ART_LEADING
    return (
        f'<text font-size="{ART_SIZE}" fill="{colour}" xml:space="preserve">'
        + "".join(spans)
        + "</text>"
    )


# ---------------------------------------------------------------------------
# panel primitives
# ---------------------------------------------------------------------------
def x_of(col: float) -> float:
    return round(PANEL_X + col * ADVANCE, 2)


def row_of(*segments: tuple[float, str, str]) -> str:
    """segments: (column, text, colour)"""
    return "".join(
        f'<tspan x="{x_of(col)}" fill="{colour}">{esc(text)}</tspan>'
        for col, text, colour in segments
        if text
    )


def kv(key: str, value: str, value_col: int, t: dict, key_col: int = 0) -> str:
    dots = max(2, value_col - key_col - len(key) - 2)
    return (
        row_of((key_col, key, t["key"]))
        + leaders(key_col + len(key), dots, t)
        + row_of((value_col, value, t["value"]))
    )


def leaders(col: float, count: int, t: dict) -> str:
    """Dot run pinned to the exact column width, so it lands before the value in any font."""
    return (
        f'<tspan x="{x_of(col + 1)}" fill="{t["muted"]}" '
        f'textLength="{round(count * ADVANCE, 1)}" lengthAdjust="spacingAndGlyphs">'
        f'{"." * count}</tspan>'
    )


def section(label: str, t: dict) -> str:
    # Rule is pinned to the panel width so the dashes cannot spill past the card.
    cols = (PANEL_W / ADVANCE) - len(label) - 4
    return (
        row_of((0, label.upper(), t["muted"]))
        + f'<tspan x="{x_of(len(label) + 2)}" fill="{t["frame"]}" '
        f'textLength="{round(cols * ADVANCE, 1)}" lengthAdjust="spacingAndGlyphs">'
        f'{"─" * int(cols)}</tspan>'
    )


def indent(text: str, t: dict) -> str:
    return row_of((1, text, t["value"]))


def bar(label: str, pct: float, colour: str, t: dict, baseline: float) -> tuple[str, str]:
    """Returns (label text row, bar graphics) for one language row."""
    label_row = row_of((1, label, t["text"]), (21, f"{pct:.0f}%", t["text"]))
    track_x = x_of(25)
    track_w = 250
    fill_w = max(4.0, track_w * pct / 100.0)
    top = round(baseline - 8, 1)
    gfx = (
        f'<rect x="{track_x}" y="{top}" width="{track_w}" height="7" rx="3.5" fill="{t["track"]}"/>'
        f'<rect x="{track_x}" y="{top}" width="{round(fill_w, 1)}" height="7" rx="3.5" fill="{colour}"/>'
    )
    return label_row, gfx


def badge(prefix: str, text: str, x: float, y: float, t: dict) -> tuple[str, float]:
    width = (len(prefix) + len(text)) * 7.55 + 26
    markup = (
        f'<g transform="translate(0, {round(y, 1)})">'
        f'<rect x="{round(x, 1)}" y="0" width="{round(width, 1)}" height="27" rx="7" '
        f'fill="{t["badge"]}" stroke="{t["frame"]}"/>'
        f'<text x="{round(x + 13, 1)}" y="18.5" font-size="12" font-family="inherit">'
        f'<tspan fill="{t["accent"]}">{esc(prefix)}</tspan>'
        f'<tspan fill="{t["text"]}">{esc(text)}</tspan></text></g>'
    )
    return markup, width


# ---------------------------------------------------------------------------
# card
# ---------------------------------------------------------------------------
def render(theme_name: str, stats: dict, light_art: str = "tile") -> str:
    t = THEMES[theme_name]
    tile = ""
    art_colour = t["art"]
    invert = False
    if theme_name == "light":
        if light_art == "flip":
            invert = True
            art_colour = "#57606a"
        elif light_art == "ink":
            art_colour = "#3d444d"
        else:  # tile: keep the portrait as a real photo panel on the light card
            tile = (
                f'<rect x="22" y="22" width="{DIVIDER_X - 40}" height="{H - 44}" rx="12" '
                f'fill="#0d1117" stroke="{t["frame"]}" stroke-opacity=".9"/>'
            )
            art_colour = "#8b949e"
    art = load_art(invert=invert)

    panel: list[str] = []
    graphics: list[str] = []
    y = PAD_TOP

    def text_row(markup: str, height: float = ROW, dy: float = 0) -> None:
        nonlocal y
        y += dy
        panel.append(f'<text x="{PANEL_X}" y="{round(y, 2)}" font-size="{BODY}">{markup}</text>')
        y += height

    # header ---------------------------------------------------------------
    y += 24
    panel.append(
        f'<text x="{PANEL_X}" y="{round(y, 2)}" font-size="14" fill="{t["muted"]}">'
        f'BE AIML · Bengaluru, India</text>'
    )
    y += 20
    panel.append(
        f'<circle cx="{round(PANEL_X + 4, 1)}" cy="{round(y - 4.6, 1)}" r="4" '
        f'fill="{t["cursor"]}" class="dot"/>'
    )
    panel.append(
        f'<text x="{round(PANEL_X + 15, 1)}" y="{round(y, 2)}" font-size="13" fill="{t["value"]}">'
        f'shipping AFTERGLOW &amp; whatever else looks fun</text>'
    )
    y += 14

    # system ---------------------------------------------------------------
    text_row(section("system", t), height=20, dy=4)
    text_row(kv("OS", ABOUT["os"], 26, t))
    text_row(kv("Uptime", stats["age"], 26, t))
    text_row(kv("Host", ABOUT["host"], 26, t))
    text_row(kv("Kernel", ABOUT["kernel"], 26, t))
    ide_main, _, ide_last = ABOUT["ide"].rpartition(", ")
    text_row(kv("IDE", f"{ide_main}," if ide_last else ABOUT["ide"], 26, t))
    if ide_last:
        text_row(indent(ide_last, t))

    # stack ----------------------------------------------------------------
    text_row(section("stack", t), height=20, dy=12)
    for key, value in STACK:
        text_row(row_of((0, key, t["key"])))
        text_row(indent(value, t))

    # github ---------------------------------------------------------------
    text_row(section("github", t), height=20, dy=12)
    text_row(
        kv("Repositories", fmt(stats["repos"]), 19, t)
        + kv("Contributions", fmt(stats["contributions"]), 43, t, key_col=26)
    )
    text_row(
        kv("Commits", fmt(stats["commits"]), 19, t)
        + kv("Streak", f'{stats["streak"]}d', 43, t, key_col=26)
    )
    text_row(kv("Lines of code", fmt(stats["loc"]), 19, t))
    added = f'+{fmt(stats["loc_add"])}'
    removed = f'-{fmt(stats["loc_del"])}'
    text_row(
        f'<tspan x="{x_of(1)}" fill="{t["green"]}">{added}</tspan>'
        f'<tspan dx="12" fill="{t["red"]}">{removed}</tspan>'
        + kv("best streak", f'{stats["best"]}d', 43, t, key_col=26),
        height=18,
    )

    # languages ------------------------------------------------------------
    text_row(section("top languages", t), height=20, dy=12)
    for name, pct, colour in stats["langs"]:
        label_row, gfx = bar(name, pct, colour, t, baseline=y)
        text_row(label_row, height=21)
        graphics.append(gfx)

    # projects -------------------------------------------------------------
    text_row(section("building", t), height=20, dy=12)
    for name, blurb in PROJECTS:
        dots = max(2, 21 - len(name) - 2)
        text_row(
            row_of((0, name, t["text"]))
            + leaders(len(name), dots, t)
            + f'<tspan x="{x_of(22)}" fill="{t["muted"]}" font-size="13">{esc(blurb)}</tspan>',
            height=22,
        )

    # contact --------------------------------------------------------------
    text_row(section("contact", t), height=20, dy=12)
    y += 4
    bx = PANEL_X
    for prefix, text in (("gh:", "Pxjjuzz"), ("in:", "prajwal-poojary-b4a53a386"), ("@", "prajwalpoojary834@gmail.com")):
        markup, width = badge(prefix, text, bx, y, t)
        graphics.append(markup)
        bx += width + 8
    y += 40

    # footer ---------------------------------------------------------------
    foot_y = H - 28
    foot_text = "built with code, caffeine & curiosity"
    panel.append(
        f'<text x="{PANEL_X}" y="{foot_y}" font-size="13" fill="{t["muted"]}">'
        f'<tspan>{esc(foot_text)}</tspan>'
        f'<tspan dx="7" fill="{t["cursor"]}" class="cursor">█</tspan></text>'
    )

    svg = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="MonoFallback, Consolas, \'DejaVu Sans Mono\', monospace">',
        f"<style>\n{STYLE.format()}</style>",
        f'<rect width="{W}" height="{H}" rx="18" fill="{t["bg"]}"/>',
        f'<rect x="12" y="12" width="{W - 24}" height="{H - 24}" rx="14" fill="none" '
        f'stroke="{t["frame"]}" stroke-opacity=".6"/>',
        tile,
        art_block(art, art_colour),
        f'<path d="M{DIVIDER_X} 40V{H - 40}" stroke="{t["frame"]}" stroke-opacity=".55"/>',
        *panel,
        *graphics,
        "</svg>",
    ]
    return "\n".join(svg) + "\n"


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
API = "https://api.github.com"


def token() -> str | None:
    return os.getenv("ACCESS_TOKEN") or os.getenv("GITHUB_TOKEN")


def headers(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}


def gh(query: str, variables: dict, tok: str) -> dict:
    r = requests.post(
        f"{API}/graphql",
        json={"query": query, "variables": variables},
        headers=headers(tok),
        timeout=40,
    )
    r.raise_for_status()
    payload = r.json()
    if payload.get("errors"):
        raise RuntimeError(str(payload["errors"])[:300])
    return payload["data"]


PROFILE_QUERY = """
query ($login: String!) {
  user(login: $login) {
    followers { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER) {
      totalCount
      nodes {
        nameWithOwner
        stargazers { totalCount }
        defaultBranchRef { target { ... on Commit { history { totalCount } } } }
        languages(first: 8, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""

CONTRIB_QUERY = """
query ($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""

HISTORY_QUERY = """
query ($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { target { ... on Commit {
      history(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        edges { node { additions deletions author { user { login } } } }
      }
    } } }
  }
}
"""


LANG_COLOURS = {
    "TypeScript": "#3178c6",
    "Python": "#3572A5",
    "JavaScript": "#f1e05a",
    "CSS": "#663399",
    "HTML": "#e34c26",
    "SCSS": "#c6538c",
    "PLpgSQL": "#336790",
    "Java": "#b07219",
    "Kotlin": "#A97BFF",
    "C": "#555555",
    "C++": "#f34b7d",
    "C#": "#178600",
    "Rust": "#dea584",
    "Go": "#00ADD8",
    "Swift": "#F05138",
    "Dart": "#00B4AB",
    "Shell": "#89e051",
    "Vue": "#41b883",
    "Svelte": "#ff3e00",
    "Jupyter Notebook": "#DA5B0B",
}


def streak_stats(days: list[tuple[str, int]]) -> tuple[int, int]:
    ordered = sorted(days)
    best = run = 0
    for _, count in ordered:
        run = run + 1 if count else 0
        best = max(best, run)
    current = 0
    for _, count in reversed(ordered):
        if not count:
            break
        current += 1
    return current, best


def top_languages(
    sizes: dict[str, int], colours: dict[str, str], take: int = 5
) -> list:
    total = sum(sizes.values()) or 1
    return [
        (name, size * 100 / total, colours.get(name) or LANG_COLOURS.get(name, "#8b949e"))
        for name, size in sorted(sizes.items(), key=lambda kv: -kv[1])[:take]
    ]


def profile_graphql(tok: str) -> dict:
    """Owner repos, stars, followers and language mix. Works with a repo-scoped token."""
    user = gh(PROFILE_QUERY, {"login": LOGIN}, tok)["user"]
    nodes = user["repositories"]["nodes"]
    sizes: dict[str, int] = {}
    colours: dict[str, str] = {}
    targets = []
    for node in nodes:
        for edge in node["languages"]["edges"]:
            name = edge["node"]["name"]
            sizes[name] = sizes.get(name, 0) + edge["size"]
            colours[name] = edge["node"]["color"] or "#8b949e"
        branch = node["defaultBranchRef"]
        owner, name = node["nameWithOwner"].split("/")
        targets.append((owner, name, branch["target"]["history"]["totalCount"] if branch else 0))
    return {
        "repos": user["repositories"]["totalCount"],
        "stars": sum(n["stargazers"]["totalCount"] for n in nodes),
        "followers": user["followers"]["totalCount"],
        "langs": top_languages(sizes, colours),
        "targets": targets,
    }


def profile_rest(tok: str) -> dict:
    """Fallback when GraphQL is unavailable."""
    h = headers(tok)
    r = requests.get(
        f"{API}/users/{LOGIN}/repos",
        params={"per_page": 100, "type": "owner", "sort": "pushed"},
        headers=h,
        timeout=40,
    )
    r.raise_for_status()
    repos = [repo for repo in r.json() if not repo["fork"]]
    sizes: dict[str, int] = {}
    for repo in repos:
        lr = requests.get(repo["languages_url"], headers=h, timeout=40)
        if lr.status_code == 200:
            for name, size in lr.json().items():
                sizes[name] = sizes.get(name, 0) + size
    me = requests.get(f"{API}/users/{LOGIN}", headers=h, timeout=40)
    followers = me.json().get("followers", 0) if me.status_code == 200 else 0
    return {
        "repos": len(repos),
        "stars": sum(repo["stargazers_count"] for repo in repos),
        "followers": followers,
        "langs": top_languages(sizes, {}),
        "targets": [(LOGIN, repo["name"], 0) for repo in repos],
    }


def contributions_graphql(tok: str) -> tuple[int, int, int]:
    calendar = gh(CONTRIB_QUERY, {"login": LOGIN}, tok)["user"]["contributionsCollection"][
        "contributionCalendar"
    ]
    days = [
        (day["date"], day["contributionCount"])
        for week in calendar["weeks"]
        for day in week["contributionDays"]
    ]
    current, best = streak_stats(days)
    return calendar["totalContributions"], current, best


def contributions_html() -> tuple[int, int, int]:
    """GITHUB_TOKEN cannot read contributionsCollection, so read the public calendar page."""
    page = requests.get(f"https://github.com/users/{LOGIN}/contributions", timeout=40)
    page.raise_for_status()
    html = page.text
    ids = dict(
        re.findall(
            r'data-date="(\d{4}-\d{2}-\d{2})"[^>]*id="(contribution-day-component-[\d-]+)"', html
        )
    )
    counts: dict[str, int] = {}
    for cid, text in re.findall(
        r'for="(contribution-day-component-[\d-]+)"[^>]*>([^<]*)</tool-tip>', html
    ):
        match = re.match(r"^(\d+|No) contributions?", text.strip())
        counts[cid] = int(match.group(1)) if match and match.group(1).isdigit() else 0
    days = [(when, counts.get(cid, 0)) for when, cid in ids.items()]
    current, best = streak_stats(days)
    return sum(count for _, count in days), current, best


def repo_lines(owner: str, name: str, login: str, tok: str, head: int, cache: dict) -> dict:
    """Count my commits and their diff size in one repo, reusing cache when HEAD is unchanged."""
    key = f"{owner}/{name}"
    old = cache.get(key)
    if old and head and old.get("head") == head:
        return old
    commits = add = dele = 0
    cursor = None
    while True:
        data = gh(HISTORY_QUERY, {"owner": owner, "name": name, "cursor": cursor}, tok)
        branch = data["repository"]["defaultBranchRef"]
        if branch is None:
            break
        hist = branch["target"]["history"]
        for edge in hist["edges"]:
            node = edge["node"]
            user = (node.get("author") or {}).get("user") or {}
            if user.get("login", "").lower() == login.lower():
                commits += 1
                add += node["additions"]
                dele += node["deletions"]
        if not hist["pageInfo"]["hasNextPage"]:
            break
        cursor = hist["pageInfo"]["endCursor"]
    result = {"head": head, "commits": commits, "add": add, "del": dele}
    cache[key] = result
    return result


def repo_lines_rest(owner: str, name: str, tok: str, cache: dict) -> dict:
    """Fallback for one repo. GitHub answers 202 while it computes the stats."""
    key = f"{owner}/{name}"
    payload = None
    for attempt in range(4):
        r = requests.get(f"{API}/repos/{owner}/{name}/stats/contributors", headers=headers(tok), timeout=40)
        if r.status_code == 200:
            payload = r.json()
            break
        if r.status_code != 202:
            raise RuntimeError(f"HTTP {r.status_code}")
        time.sleep(2**attempt)
    if payload is None:
        raise RuntimeError("stats still computing")
    mine = [
        c for c in payload if ((c.get("author") or {}).get("login") or "").lower() == LOGIN.lower()
    ]
    result = {
        "head": cache.get(key, {}).get("head", 0),
        "commits": sum(c["total"] for c in mine),
        "add": sum(week["a"] for c in mine for week in c["weeks"]),
        "del": sum(week["d"] for c in mine for week in c["weeks"]),
    }
    cache[key] = result
    return result


def collect(tok: str) -> dict:
    CACHE.mkdir(exist_ok=True)
    repo_cache = json.loads(REPO_CACHE.read_text()) if REPO_CACHE.exists() else {}

    try:
        profile = profile_graphql(tok)
        source = "graphql"
    except Exception as exc:
        print(f"profile via graphql failed ({exc}); using REST", file=sys.stderr)
        profile = profile_rest(tok)
        source = "rest"

    commits = loc_add = loc_del = 0
    for owner, name, head in profile["targets"]:
        key = f"{owner}/{name}"
        try:
            stats = (
                repo_lines(owner, name, LOGIN, tok, head, repo_cache)
                if source == "graphql"
                else repo_lines_rest(owner, name, tok, repo_cache)
            )
        except Exception as exc:
            stats = repo_cache.get(key)
            if stats is None:
                print(f"  {key}: skipped ({exc})", file=sys.stderr)
                stats = {"commits": 0, "add": 0, "del": 0}
            else:
                print(f"  {key}: reusing cached numbers ({exc})", file=sys.stderr)
        commits += stats.get("commits", 0)
        loc_add += stats.get("add", 0)
        loc_del += stats.get("del", 0)

    REPO_CACHE.write_text(json.dumps(repo_cache, indent=2, sort_keys=True))

    try:
        contributions, streak, best = contributions_graphql(tok)
    except Exception as exc:
        print(f"contributions via graphql failed ({exc}); scraping calendar", file=sys.stderr)
        contributions, streak, best = contributions_html()

    return {
        "updated": date.today().isoformat(),
        "age": age(),
        "repos": profile["repos"],
        "stars": profile["stars"],
        "contributions": contributions,
        "followers": profile["followers"],
        "commits": commits,
        "streak": streak,
        "best": best,
        "loc_add": loc_add,
        "loc_del": loc_del,
        "loc": loc_add - loc_del,
        "langs": profile["langs"],
    }


SAMPLE = {
    "updated": "2026-11-20",
    "age": age(),
    "repos": 7,
    "stars": 5,
    "contributions": 184,
    "followers": 1,
    "commits": 236,
    "streak": 4,
    "best": 11,
    "loc_add": 18422,
    "loc_del": 3121,
    "loc": 15301,
    "langs": [
        ("TypeScript", 46.2, "#3178c6"),
        ("Python", 27.9, "#3572A5"),
        ("JavaScript", 12.4, "#f1e05a"),
        ("CSS", 8.1, "#563d7c"),
        ("HTML", 5.4, "#e34c26"),
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="use cache/stats.json only")
    parser.add_argument("--sample", action="store_true", help="fake numbers, write to preview/")
    parser.add_argument("--light-art", default="tile", choices=["tile", "flip", "ink"],
                        help="how the portrait is drawn on the light card")
    args = parser.parse_args()

    if args.sample:
        stats = SAMPLE
    elif args.offline:
        stats = json.loads(STATS_CACHE.read_text())
        stats["age"] = age()
        stats["updated"] = date.today().isoformat()
    else:
        tok = token()
        if not tok:
            print("no ACCESS_TOKEN / GITHUB_TOKEN set", file=sys.stderr)
            return 1
        stats = collect(tok)
        CACHE.mkdir(exist_ok=True)
        STATS_CACHE.write_text(json.dumps(stats, indent=2))

    out = ROOT / "preview" if args.sample else ROOT
    out.mkdir(exist_ok=True)
    for theme in ("dark", "light"):
        (out / f"{theme}_mode.svg").write_text(
            render(theme, stats, args.light_art), encoding="utf-8"
        )
    print(f"rendered {out} ({stats['repos']} repos, {stats['commits']} commits)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
