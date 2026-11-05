#!/usr/bin/env python3
"""Generate an animated "profile scan" terminal card (SVG) for a GitHub profile README.

The left panel turns a photo into teal ASCII art revealed by a scanline;
the right panel types out live GitHub stats line by line. Everything is
pure SVG + SMIL so it animates inside a README <img>.

Usage:
  python scripts/profile_scan.py --user LKtheekshana --out dist/profile-scan.svg
  python scripts/profile_scan.py --user LKtheekshana --photo assets/photo.jpg --out ...

Stats come from the GitHub API when GITHUB_TOKEN is set (as in Actions).
"""
import argparse
import io
import json
import os
import urllib.request
from html import escape

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

# ---------------------------------------------------------------- profile text
PROFILE = {
    "subject": "Theekshana Premarathne",
    "role": "Software Engineering Undergrad",
    "status": "Building | Learning | Shipping",
    "focus": "LLMs · Computer Vision · APIs",
}

# ---------------------------------------------------------------- look & feel
W, H = 960, 520
BG = "#070b0f"
PANEL = "#0b1217"
ACCENT = "#2ee6c5"
ACCENT_DIM = "#1b8f7c"
TEXT = "#cfe9e4"
MUTED = "#5d7c77"
FONT = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"
RAMP = " .,:;-=+*#%@"           # dark -> bright
COLS, ROWS = 104, 57             # ASCII resolution
CYCLE = 16.0                    # seconds per animation loop


# ---------------------------------------------------------------- data
def gh(url, token, data=None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "profile-scan"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_stats(user, token):
    stats = {"repos": "—", "contributions": "—", "stars": "—", "followers": "—",
             "languages": "Python, Swift, JavaScript", "since": "—"}
    if not token:
        return stats
    try:
        u = gh(f"https://api.github.com/users/{user}", token)
        stats["repos"] = u.get("public_repos", "—")
        stats["followers"] = u.get("followers", "—")
        stats["since"] = (u.get("created_at") or "—")[:4]
        repos, page = [], 1
        while True:
            batch = gh(f"https://api.github.com/users/{user}/repos?per_page=100&page={page}", token)
            repos += batch
            if len(batch) < 100:
                break
            page += 1
        own = [r for r in repos if not r.get("fork")]
        stats["stars"] = sum(r.get("stargazers_count", 0) for r in own)
        counts = {}
        for r in own:
            if r.get("language"):
                counts[r["language"]] = counts.get(r["language"], 0) + 1
        if counts:
            top = sorted(counts, key=counts.get, reverse=True)[:3]
            stats["languages"] = ", ".join(top)
    except Exception as e:  # keep going with whatever we have
        print("REST stats failed:", e)
    try:
        q = {"query": "query($u:String!){user(login:$u){contributionsCollection{"
                      "contributionCalendar{totalContributions}}}}", "variables": {"u": user}}
        d = gh("https://api.github.com/graphql", token, json.dumps(q).encode())
        stats["contributions"] = (d["data"]["user"]["contributionsCollection"]
                                  ["contributionCalendar"]["totalContributions"])
    except Exception as e:
        print("GraphQL contributions failed:", e)
    return stats


def load_photo(path, user):
    if path and os.path.exists(path):
        return Image.open(path)
    url = f"https://avatars.githubusercontent.com/{user}?s=460"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "profile-scan"}), timeout=30) as r:
        return Image.open(io.BytesIO(r.read()))


# ---------------------------------------------------------------- ascii art
def to_ascii(img):
    img = ImageOps.exif_transpose(img).convert("L")
    side = min(img.size)
    img = ImageOps.fit(img, (side, side), centering=(0.5, 0.35))
    small = img.filter(ImageFilter.UnsharpMask(radius=3, percent=120)).resize((COLS, ROWS), Image.LANCZOS)
    a = np.asarray(small, dtype=float) / 255.0
    subject = a > 0.04                       # pure-black background (after cut-out) stays empty
    if subject.mean() > 0.05:
        # histogram-equalise only the person so facial features separate clearly
        vals = a[subject]
        ranks = np.searchsorted(np.sort(vals), a, side="right") / vals.size
        a = np.where(subject, 0.15 + 0.85 * ranks, 0)
    # circular vignette so the portrait sits in a round "scan" area
    yy, xx = np.mgrid[0:ROWS, 0:COLS]
    cx, cy = (COLS - 1) / 2, (ROWS - 1) / 2
    r = np.sqrt(((xx - cx) / (COLS / 2)) ** 2 + ((yy - cy) / (ROWS / 2)) ** 2)
    a = a * np.clip((1.02 - r) / 0.12, 0, 1)
    idx = np.clip((a * (len(RAMP) - 1)).round().astype(int), 0, len(RAMP) - 1)
    lvl = np.clip((a * 5).round().astype(int), 0, 5)   # 6 shading levels
    return [("".join(RAMP[i] for i in row), list(lv)) for row, lv in zip(idx, lvl)]


SHADES = [0.0, 0.45, 0.6, 0.75, 0.9, 1.0]


def shaded(line, levels):
    """Group runs of equal brightness into tspans with fill-opacity."""
    parts, i = [], 0
    while i < len(line):
        j = i
        while j < len(line) and levels[j] == levels[i]:
            j += 1
        chunk = escape(line[i:j]).replace(" ", " ")  # NBSP: spaces must not collapse
        lv = levels[i]
        parts.append(chunk if lv == 5 else f'<tspan fill-opacity="{SHADES[lv]}">{chunk}</tspan>')
        i = j
    return "".join(parts)


# ---------------------------------------------------------------- svg helpers
def appear(t, dur=0.25, attr="opacity", hold_end=0.93):
    """SMIL: invisible until t seconds into the loop, then visible until loop end."""
    a = min(t / CYCLE, hold_end - 0.02)
    b = min((t + dur) / CYCLE, hold_end - 0.01)
    return (f'<animate attributeName="{attr}" dur="{CYCLE}s" repeatCount="indefinite" '
            f'values="0;0;1;1;0" keyTimes="0;{a:.4f};{b:.4f};{hold_end};1"/>')


def typed(x, y, text, t, cps=40, size=15, fill=TEXT, weight="400", cid=None):
    """Text revealed left to right like typing, via an animated clip rect."""
    width = max(1, len(text)) * size * 0.62 + 4
    dur = max(0.15, len(text) / cps)
    a, b = t / CYCLE, min((t + dur) / CYCLE, 0.92)
    return (f'<clipPath id="{cid}"><rect x="{x - 2}" y="{y - size}" height="{size + 6}" width="0">'
            f'<animate attributeName="width" dur="{CYCLE}s" repeatCount="indefinite" '
            f'values="0;0;{width:.0f};{width:.0f};0" keyTimes="0;{a:.4f};{b:.4f};0.93;1"/></rect></clipPath>'
            f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}" '
            f'clip-path="url(#{cid})">{escape(text)}</text>')


def build_svg(lines, stats, user, static=False):
    out = []
    add = out.append
    add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'font-family="{FONT}" role="img" aria-label="Profile scan of {escape(user)}">')
    add(f'''<defs>
  <linearGradient id="scan" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{ACCENT}" stop-opacity="0"/>
    <stop offset="0.85" stop-color="{ACCENT}" stop-opacity="0.18"/>
    <stop offset="1" stop-color="{ACCENT}" stop-opacity="0.7"/>
  </linearGradient>
  <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
    <feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <pattern id="crt" width="4" height="4" patternUnits="userSpaceOnUse">
    <rect width="4" height="1" fill="#ffffff" opacity="0.025"/>
  </pattern>
</defs>''')
    # window
    add(f'<rect x="1" y="1" width="{W-2}" height="{H-2}" rx="16" fill="{BG}" stroke="{ACCENT}" stroke-opacity="0.55" stroke-width="2"/>')
    add(f'<rect x="1" y="1" width="{W-2}" height="{H-2}" rx="16" fill="none" stroke="{ACCENT}" stroke-opacity="0.12" stroke-width="8"/>')
    for i, c in enumerate(["#ff5f57", "#febc2e", "#28c840"]):
        add(f'<circle cx="{28 + i*20}" cy="26" r="6" fill="{c}"/>')
    prompt = f"{user.lower()}@github: ~ $ ./profile-scan --live"
    if static:
        add(f'<text x="{W/2}" y="31" text-anchor="middle" font-size="14" fill="{MUTED}">{escape(prompt)}</text>')
    else:
        px = W / 2 - len(prompt) * 14 * 0.62 / 2
        add(typed(px, 31, prompt, 0.2, cps=45, size=14, fill=MUTED, cid="tp"))
    add(f'<line x1="16" y1="48" x2="{W-16}" y2="48" stroke="{ACCENT}" stroke-opacity="0.18"/>')

    # panels
    LX, LY, LW, LH = 24, 64, 430, 432
    RX, RY, RW, RH = 474, 64, 462, 432
    for (x, y, w, h, label) in [(LX, LY, LW, LH, "VISUAL.MAP"), (RX, RY, RW, RH, "SYSTEM.INFO")]:
        add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{PANEL}" stroke="{ACCENT}" stroke-opacity="0.35"/>')
        add(f'<text x="{x+14}" y="{y+22}" font-size="11" letter-spacing="2" fill="{ACCENT}" opacity="0.8">{label}</text>')
    add(f'<text x="{RX+RW-16}" y="{RY+22}" font-size="11" text-anchor="end" fill="{ACCENT}">'
        f'<tspan>● LIVE</tspan>'
        + ('' if static else f'<animate attributeName="opacity" values="1;0.25;1" dur="1.4s" repeatCount="indefinite"/>')
        + '</text>')

    # ascii portrait
    art_top, art_h = LY + 40, LH - 56
    lh = art_h / len(lines)
    art_w = LW - 40
    add(f'<g font-size="{lh*0.98:.2f}" fill="{ACCENT}" filter="url(#glow)" xml:space="preserve">')
    scan_start, scan_len = 1.4, 3.2
    for i, (line, levels) in enumerate(lines):
        y = art_top + (i + 0.8) * lh
        t = scan_start + scan_len * i / len(lines)
        anim = "" if static else appear(t, 0.15)
        op = "1" if static else "0"
        add(f'<text x="{LX+20}" y="{y:.1f}" textLength="{art_w}" lengthAdjust="spacingAndGlyphs" opacity="{op}">'
            f'{shaded(line, levels)}{anim}</text>')
    add('</g>')
    if not static:
        # scanline that sweeps once while drawing, then idles slowly
        add(f'<rect x="{LX+8}" width="{LW-16}" height="40" fill="url(#scan)" opacity="0.9">'
            f'<animate attributeName="y" dur="{CYCLE}s" repeatCount="indefinite" '
            f'values="{art_top-40};{art_top-40};{art_top+art_h-40};{art_top+art_h-40}" '
            f'keyTimes="0;{scan_start/CYCLE:.4f};{(scan_start+scan_len)/CYCLE:.4f};1"/>'
            f'<animate attributeName="opacity" dur="{CYCLE}s" repeatCount="indefinite" '
            f'values="0;0;0.9;0.9;0;0" keyTimes="0;{scan_start/CYCLE:.4f};{(scan_start+0.1)/CYCLE:.4f};'
            f'{(scan_start+scan_len)/CYCLE:.4f};{(scan_start+scan_len+0.3)/CYCLE:.4f};1"/></rect>')
    add(f'<rect x="{LX}" y="{LY}" width="{LW}" height="{LH}" rx="10" fill="url(#crt)"/>')

    # info rows
    rows = [
        ("Subject", PROFILE["subject"]),
        ("Handle", f"@{user}"),
        ("Role", PROFILE["role"]),
        ("Status", PROFILE["status"]),
        ("Focus", PROFILE["focus"]),
        ("Languages", stats["languages"]),
        ("Repositories", str(stats["repos"])),
        ("Contributions", f'{stats["contributions"]:,}' if isinstance(stats["contributions"], int) else str(stats["contributions"])),
        ("Stars", str(stats["stars"])),
        ("Followers", str(stats["followers"])),
        ("Contact", f"github.com/{user}"),
    ]
    row_y0, row_gap = RY + 58, 33
    t = 4.8
    for i, (k, v) in enumerate(rows):
        y = row_y0 + i * row_gap
        if i:
            add(f'<line x1="{RX+16}" y1="{y-21}" x2="{RX+RW-16}" y2="{y-21}" stroke="{ACCENT}" stroke-opacity="0.08"/>')
        if static:
            add(f'<text x="{RX+18}" y="{y}" font-size="14" fill="{ACCENT}">{escape(k)}</text>')
            add(f'<text x="{RX+170}" y="{y}" font-size="14" fill="{TEXT}">{escape(v)}</text>')
        else:
            add(f'<text x="{RX+18}" y="{y}" font-size="14" fill="{ACCENT}" opacity="0">{escape(k)}{appear(t, 0.2)}</text>')
            add(typed(RX + 170, y, v, t + 0.15, cps=55, size=14, cid=f"r{i}"))
            t += 0.15 + len(v) / 55 + 0.12

    # footer status
    fy = RY + RH - 16
    done = f"[✓] scan complete — {len(rows)} fields resolved"
    if static:
        add(f'<text x="{RX+18}" y="{fy}" font-size="12" fill="{ACCENT}">{escape(done)}</text>')
    else:
        add(f'<text x="{RX+18}" y="{fy}" font-size="12" fill="{MUTED}">[…] scanning'
            f'<animate attributeName="opacity" dur="{CYCLE}s" repeatCount="indefinite" values="1;1;0;0;1" '
            f'keyTimes="0;{t/CYCLE:.4f};{(t+0.05)/CYCLE:.4f};0.93;1"/></text>')
        add(f'<text x="{RX+18}" y="{fy}" font-size="12" fill="{ACCENT}" opacity="0">{escape(done)}{appear(t, 0.1)}</text>')
        cx = RX + 18 + len(done) * 12 * 0.62 + 6
        add(f'<rect x="{cx:.0f}" y="{fy-11}" width="8" height="13" fill="{ACCENT}" opacity="0">'
            f'<animate attributeName="opacity" dur="{CYCLE}s" repeatCount="indefinite" calcMode="discrete" '
            f'values="0;1;0;1;0;1;0;1;0" keyTimes="0;{t/CYCLE:.4f};{(t+0.5)/CYCLE:.4f};{(t+1)/CYCLE:.4f};'
            f'{(t+1.5)/CYCLE:.4f};{(t+2)/CYCLE:.4f};{(t+2.5)/CYCLE:.4f};{(t+3)/CYCLE:.4f};0.93"/></rect>')
    add('</svg>')
    return "\n".join(out)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--user", required=True)
    p.add_argument("--photo", default="assets/photo.jpg")
    p.add_argument("--out", default="dist/profile-scan.svg")
    p.add_argument("--static", action="store_true", help="no animation (for previews)")
    p.add_argument("--stats-json", help="use stats from a JSON file instead of the API")
    args = p.parse_args()

    stats = json.load(open(args.stats_json)) if args.stats_json else fetch_stats(args.user, os.getenv("GITHUB_TOKEN"))
    lines = to_ascii(load_photo(args.photo, args.user))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(build_svg(lines, stats, args.user, static=args.static))
    print("wrote", args.out, stats)


if __name__ == "__main__":
    main()
