#!/usr/bin/env python3
"""Generate light_mode.svg / dark_mode.svg neofetch-style profile cards.

Pulls public GitHub stats for GITHUB_USERNAME via the REST + GraphQL APIs
and renders them next to the cached ASCII avatar (assets/avatar_ascii.txt,
produced separately by make_ascii_avatar.py) into two themed SVGs.

Only public data is used everywhere (public repos, public contributions),
so the default Actions GITHUB_TOKEN is sufficient — no extra PAT needed.
"""
import os
import sys
import time
from datetime import datetime, timezone

import requests

USERNAME = os.environ.get("GITHUB_USERNAME", "safaraliyevelmir")
TOKEN = os.environ["GITHUB_TOKEN"]
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")

REST_HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
}
GRAPHQL_HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
}


def gh_graphql(query: str, variables: dict) -> dict:
    resp = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables},
        headers=GRAPHQL_HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"GraphQL error: {data['errors']}")
    return data["data"]


def fetch_user_info() -> dict:
    resp = requests.get(f"https://api.github.com/users/{USERNAME}", headers=REST_HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


# No privacy filter: with a PAT that has repo scope this also counts
# private/organization repositories, which is where most of the LOC lives.
# With the default Actions GITHUB_TOKEN it silently degrades to public-only.
OWNED_REPOS_QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    repositories(first: 100, after: $cursor, ownerAffiliations: [OWNER, ORGANIZATION_MEMBER, COLLABORATOR], isFork: false) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes { name stargazerCount isPrivate owner { login } }
    }
  }
}
"""

CONTRIBUTED_REPOS_QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    repositoriesContributedTo(first: 100, after: $cursor, contributionTypes: [COMMIT], includeUserRepositories: false) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes { name owner { login } }
    }
  }
}
"""

COMMITS_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
    }
  }
}
"""


def paginate(query: str, path: list) -> list:
    nodes = []
    cursor = None
    while True:
        data = gh_graphql(query, {"login": USERNAME, "cursor": cursor})
        node = data
        for key in path:
            node = node[key]
        nodes.extend(node["nodes"])
        if not node["pageInfo"]["hasNextPage"]:
            break
        cursor = node["pageInfo"]["endCursor"]
    return nodes


def fetch_owned_repos() -> list:
    return paginate(OWNED_REPOS_QUERY, ["user", "repositories"])


def fetch_contributed_repos() -> list:
    return paginate(CONTRIBUTED_REPOS_QUERY, ["user", "repositoriesContributedTo"])


def fetch_total_commits(created_at: str) -> int:
    start_year = datetime.fromisoformat(created_at.replace("Z", "+00:00")).year
    current_year = datetime.now(timezone.utc).year
    total = 0
    for year in range(start_year, current_year + 1):
        frm = f"{year}-01-01T00:00:00Z"
        to = f"{year}-12-31T23:59:59Z"
        data = gh_graphql(COMMITS_QUERY, {"login": USERNAME, "from": frm, "to": to})
        total += data["user"]["contributionsCollection"]["totalCommitContributions"]
    return total


def fetch_loc(owner: str, repo: str) -> tuple:
    """Returns (additions, deletions) contributed by USERNAME, or (0, 0) if unavailable."""
    url = f"https://api.github.com/repos/{owner}/{repo}/stats/contributors"
    for attempt in range(3):
        resp = requests.get(url, headers=REST_HEADERS, timeout=30)
        if resp.status_code == 202:
            # GitHub is still computing stats for this repo; wait and retry once or twice.
            time.sleep(3)
            continue
        resp.raise_for_status()
        for entry in resp.json():
            if entry.get("author", {}).get("login", "").lower() == USERNAME.lower():
                additions = sum(w["a"] for w in entry["weeks"])
                deletions = sum(w["d"] for w in entry["weeks"])
                return additions, deletions
        return 0, 0
    print(f"warning: stats/contributors not ready for {owner}/{repo}, skipping", file=sys.stderr)
    return 0, 0


def collect_stats() -> dict:
    user = fetch_user_info()
    owned = fetch_owned_repos()
    contributed = fetch_contributed_repos()

    stars = sum(r["stargazerCount"] for r in owned)

    seen = set()
    all_repos = []
    for r in owned + contributed:
        key = (r["owner"]["login"], r["name"])
        if key not in seen:
            seen.add(key)
            all_repos.append(key)

    loc_add = loc_del = 0
    for owner, name in all_repos:
        a, d = fetch_loc(owner, name)
        loc_add += a
        loc_del += d

    commits = fetch_total_commits(user["created_at"])

    return {
        "repos": user["public_repos"],
        "followers": user["followers"],
        "contributed": len(contributed),
        "stars": stars,
        "commits": commits,
        "loc_add": loc_add,
        "loc_del": loc_del,
    }


def load_avatar(theme_name: str) -> list:
    path = os.path.join(REPO_ROOT, "assets", f"avatar_{theme_name}.txt")
    with open(path) as f:
        return f.read().splitlines()


INFO_ROWS = [
    ("Role", "Software Engineer"),
    ("Location", "Baku, Azerbaijan"),
    ("Languages", "Python, JavaScript, HTML, CSS"),
    ("Databases", "PostgreSQL, MongoDB"),
    ("Cloud", "AWS"),
    ("Interests", "Shopify, Trading, Machine Learning, Minecraft"),
    ("LinkedIn", "linkedin.com/in/elmirsafaraliyev"),
]

THEMES = {
    "dark": {"bg": "#161b22", "fg": "#c9d1d9", "key": "#ffa657", "value": "#a5d6ff", "add": "#3fb950", "del": "#f85149", "dim": "#616e7f"},
    "light": {"bg": "#ffffff", "fg": "#24292f", "key": "#953800", "value": "#0a3069", "add": "#1a7f37", "del": "#cf222e", "dim": "#6e7781"},
}


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# Braille glyph metrics vary between fallback fonts, so each art line is
# pinned to an exact pixel width via textLength below.
AVATAR_FONT_SIZE = 12
AVATAR_LINE_H = 12
AVATAR_CHAR_W = 6.5
INFO_FONT_SIZE = 14
INFO_LINE_H = 20
INFO_CHAR_W = 8.4


def render_svg(stats: dict, ascii_lines: list, theme_name: str) -> str:
    t = THEMES[theme_name]
    top = 30
    avatar_x = 15
    avatar_width_px = max(len(line) for line in ascii_lines) * AVATAR_CHAR_W
    info_x = avatar_x + avatar_width_px + 25

    info_line_count = 1 + len(INFO_ROWS) + 6  # header + rows + spacer + stats header + 4 stat rows
    longest_info_line = max(len(k) + len(v) for k, v in INFO_ROWS) + 2
    longest_info_line = max(longest_info_line, len("Lines of Code: ") + 20)

    width = info_x + longest_info_line * INFO_CHAR_W + 20
    height = max(len(ascii_lines) * AVATAR_LINE_H, info_line_count * INFO_LINE_H) + 40

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" font-family="Consolas,monospace" '
        f'width="{width:.0f}px" height="{height:.0f}px" font-size="{INFO_FONT_SIZE}px">',
        f'<rect width="{width:.0f}px" height="{height:.0f}px" fill="{t["bg"]}" rx="10"/>',
        f'<text x="{avatar_x}" y="{top}" fill="{t["fg"]}" font-size="{AVATAR_FONT_SIZE}px" '
        f'font-family="\'Apple Braille\',\'Segoe UI Symbol\',\'Noto Sans Symbols 2\',monospace">',
    ]
    for i, line in enumerate(ascii_lines):
        y = top + i * AVATAR_LINE_H
        parts.append(
            f'<tspan x="{avatar_x}" y="{y:.1f}" textLength="{avatar_width_px:.0f}" '
            f'lengthAdjust="spacingAndGlyphs">{esc(line)}</tspan>'
        )
    parts.append("</text>")

    line_h = INFO_LINE_H
    parts.append(f'<text x="{info_x:.0f}" y="{top}" fill="{t["fg"]}">')
    parts.append(f'<tspan x="{info_x}" y="{top}">{esc(USERNAME)}</tspan> -----------------------------')
    y = top + line_h
    for key, value in INFO_ROWS:
        parts.append(
            f'<tspan x="{info_x}" y="{y}" fill="{t["key"]}">{esc(key)}</tspan>'
            f'<tspan fill="{t["dim"]}">: </tspan>'
            f'<tspan fill="{t["value"]}">{esc(value)}</tspan>'
        )
        y += line_h

    y += line_h // 2
    parts.append(f'<tspan x="{info_x}" y="{y}">GitHub Stats</tspan> -----------------------------')
    y += line_h
    parts.append(
        f'<tspan x="{info_x}" y="{y}" fill="{t["key"]}">Repos</tspan>'
        f'<tspan fill="{t["dim"]}">: </tspan><tspan fill="{t["value"]}">{stats["repos"]}</tspan>'
        f'<tspan fill="{t["dim"]}"> | </tspan>'
        f'<tspan fill="{t["key"]}">Contributed</tspan>'
        f'<tspan fill="{t["dim"]}">: </tspan><tspan fill="{t["value"]}">{stats["contributed"]}</tspan>'
    )
    y += line_h
    parts.append(
        f'<tspan x="{info_x}" y="{y}" fill="{t["key"]}">Stars</tspan>'
        f'<tspan fill="{t["dim"]}">: </tspan><tspan fill="{t["value"]}">{stats["stars"]}</tspan>'
        f'<tspan fill="{t["dim"]}"> | </tspan>'
        f'<tspan fill="{t["key"]}">Followers</tspan>'
        f'<tspan fill="{t["dim"]}">: </tspan><tspan fill="{t["value"]}">{stats["followers"]}</tspan>'
    )
    y += line_h
    parts.append(
        f'<tspan x="{info_x}" y="{y}" fill="{t["key"]}">Commits</tspan>'
        f'<tspan fill="{t["dim"]}">: </tspan><tspan fill="{t["value"]}">{stats["commits"]:,}</tspan>'
    )
    y += line_h
    parts.append(
        f'<tspan x="{info_x}" y="{y}" fill="{t["key"]}">Lines of Code</tspan>'
        f'<tspan fill="{t["dim"]}">: </tspan>'
        f'<tspan fill="{t["add"]}">{stats["loc_add"]:,}++</tspan>'
        f'<tspan fill="{t["dim"]}">, </tspan>'
        f'<tspan fill="{t["del"]}">{stats["loc_del"]:,}--</tspan>'
    )
    parts.append("</text>")
    parts.append("</svg>")
    return "\n".join(parts)


def main() -> int:
    stats = collect_stats()

    for theme in ("dark", "light"):
        svg = render_svg(stats, load_avatar(theme), theme)
        out_path = os.path.join(REPO_ROOT, f"{theme}_mode.svg")
        with open(out_path, "w") as f:
            f.write(svg + "\n")
        print(f"Wrote {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
