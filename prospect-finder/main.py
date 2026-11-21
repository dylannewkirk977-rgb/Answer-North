"""Korvellan Studios Prospect Finder - find local businesses and YouTube creators to pitch.

Commands:
  search    local businesses (OpenStreetMap) -> data/local_prospects.csv
  creators  YouTube creators for the Clipper   -> data/creator_prospects.csv
"""
import argparse
import csv
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

USER_AGENT = "KorvellanStudiosProspectFinder/1.1"
DATA_DIR = Path(__file__).parent / "data"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Free public OpenStreetMap query servers; they're often busy, so we try several.
OVERPASS_SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Industry -> OpenStreetMap tags, plus a name pattern to catch businesses tagged loosely.
INDUSTRIES = {
    "plumber":     {"tags": [("craft", "plumber")], "name": "plumb"},
    "hvac":        {"tags": [("craft", "hvac"), ("shop", "hvac")], "name": "hvac|heating|air condition|furnace"},
    "electrician": {"tags": [("craft", "electrician")], "name": "electric"},
    "contractor":  {"tags": [("craft", "builder"), ("office", "construction_company")],
                    "name": "construction|contracting|builders|remodel"},
    "roofer":      {"tags": [("craft", "roofer")], "name": "roofing"},
    "landscaper":  {"tags": [("craft", "gardener")], "name": "landscap|lawn care"},
    "painter":     {"tags": [("craft", "painter")], "name": "painting"},
    "dentist":     {"tags": [("amenity", "dentist"), ("healthcare", "dentist")], "name": "dental|dentist"},
    "salon":       {"tags": [("shop", "hairdresser"), ("shop", "beauty")], "name": "salon|barber"},
    "auto_repair": {"tags": [("shop", "car_repair")], "name": "auto repair|automotive"},
    "lawyer":      {"tags": [("office", "lawyer")], "name": "law office|law firm|attorney"},
    "real_estate": {"tags": [("office", "estate_agent")], "name": "realty|real estate"},
}
BUSINESS_KEYS = ("shop", "craft", "office", "amenity", "healthcare")  # filters name-only matches


# ----------------------------------------------------------------- shared helpers

def get(url: str, **kwargs) -> requests.Response:
    headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
    return requests.get(url, headers=headers, timeout=kwargs.pop("timeout", 30), **kwargs)


def save_rows(path: Path, rows: list[dict], key: str) -> tuple[int, int]:
    """Append rows to a CSV, skipping ones already saved (by `key`). Returns (new, skipped)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            existing = {r.get(key) for r in csv.DictReader(f)}
    new = [r for r in rows if str(r[key]) not in existing]
    if new:
        write_header = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            if write_header:
                w.writeheader()
            w.writerows(new)
    return len(new), len(rows) - len(new)


# ----------------------------------------------------------------- local businesses

def geocode(place: str) -> dict:
    """Look up a city with Nominatim (any capitalization works)."""
    r = get(NOMINATIM_URL, params={"q": place, "format": "json", "limit": 1})
    r.raise_for_status()
    data = r.json()
    if not data:
        raise ValueError(f"Couldn't find '{place}'. Try adding the state, e.g. \"Stillwater, MN\".")
    return {"name": data[0]["display_name"], "lat": float(data[0]["lat"]), "lon": float(data[0]["lon"])}


def overpass_query(industry: str, lat: float, lon: float, radius_m: int) -> str:
    spec = INDUSTRIES.get(industry, {"tags": [], "name": re.escape(industry)})
    around = f"(around:{radius_m},{lat},{lon})"
    parts = [f'nwr["{k}"="{v}"]{around};' for k, v in spec["tags"]]
    parts.append(f'nwr["name"~"{spec["name"]}",i]{around};')
    return f"[out:json][timeout:90];({''.join(parts)});out center tags;"


def run_overpass(query: str, rounds: int = 2) -> list[dict]:
    """Try each public server in turn; busy/timeouts move on to the next one."""
    for rnd in range(rounds):
        for url in OVERPASS_SERVERS:
            host = url.split("/")[2]
            try:
                r = requests.post(url, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=60)
            except requests.RequestException as e:
                print(f"  {host}: no response ({type(e).__name__}), trying next server...")
                continue
            if r.status_code in (429, 502, 503, 504):
                print(f"  {host}: busy ({r.status_code}), trying next server...")
                continue
            if r.status_code != 200:
                print(f"  {host}: error {r.status_code}, trying next server...")
                continue
            try:
                return r.json().get("elements", [])
            except ValueError:
                print(f"  {host}: bad reply, trying next server...")
        if rnd + 1 < rounds:
            print("  All map servers busy; waiting 30s and trying again...")
            time.sleep(30)
    raise RuntimeError("All free OpenStreetMap servers are busy right now. Try again in a few minutes.")


def to_business(el: dict, industry: str, place: str) -> dict | None:
    tags = el.get("tags", {})
    name = tags.get("name", "").strip()
    if len(name) < 2 or not any(k in tags for k in BUSINESS_KEYS):
        return None
    street = " ".join(p for p in (tags.get("addr:housenumber"), tags.get("addr:street")) if p)
    address = ", ".join(p for p in (street, tags.get("addr:city"), tags.get("addr:state"),
                                    tags.get("addr:postcode")) if p)
    website = tags.get("website") or tags.get("contact:website") or tags.get("url") or ""
    if website and not website.startswith(("http://", "https://")):
        website = "https://" + website
    center = el.get("center", el)
    return {
        "found_at": datetime.now().strftime("%Y-%m-%d"),
        "industry": industry,
        "name": name,
        "phone": tags.get("phone") or tags.get("contact:phone") or "",
        "email": tags.get("email") or tags.get("contact:email") or "",
        "website": website,
        "has_website": "yes" if website else "NO",
        "address": address,
        "searched_near": place,
        "lat": center.get("lat", ""),
        "lon": center.get("lon", ""),
        "osm_id": f"{el['type']}/{el['id']}",
    }


def cmd_search(args) -> int:
    industry = args.industry.lower().strip()
    if industry not in INDUSTRIES:
        print(f"Note: '{industry}' isn't a preset; searching business names for it. "
              f"Presets: {', '.join(INDUSTRIES)}")
    print(f"Looking up {args.city}...")
    place = geocode(args.city)
    print(f"  -> {place['name']}")
    time.sleep(1)  # Nominatim's usage policy: max 1 request per second

    print(f"Searching for {industry} within {args.radius_km} km...")
    elements = run_overpass(overpass_query(industry, place["lat"], place["lon"], args.radius_km * 1000))

    seen, results = set(), []
    for el in elements:
        b = to_business(el, industry, args.city)
        if not b:
            continue
        dupe_key = (b["name"].lower(), b["address"].lower())
        if dupe_key in seen:
            continue
        seen.add(dupe_key)
        results.append(b)
    results = results[: args.limit]

    if not results:
        print("\nNo businesses found. Try a bigger --radius-km, a nearby larger city, or another industry.")
        return 0

    print(f"\nFound {len(results)} businesses:\n")
    for i, b in enumerate(results, 1):
        print(f"[{i}] {b['name']}")
        for label, key in (("Phone", "phone"), ("Email", "email"), ("Website", "website"), ("Address", "address")):
            if b[key]:
                print(f"    {label}: {b[key]}")
        if b["has_website"] == "NO":
            print("    (no website listed: possible website lead)")
    out = DATA_DIR / "local_prospects.csv"
    new, skipped = save_rows(out, results, "osm_id")
    print(f"\nSaved {new} new to {out}" + (f" ({skipped} already in the list)" if skipped else ""))
    return 0


# ----------------------------------------------------------------- YouTube creators

ATOM = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/"}


def recent_uploads(channel_id: str) -> list[dict]:
    """Latest ~15 uploads from the channel's public RSS feed: date, views, short or not."""
    r = get("https://www.youtube.com/feeds/videos.xml", params={"channel_id": channel_id}, timeout=20)
    if r.status_code != 200:
        return []
    uploads = []
    for e in ET.fromstring(r.content).findall("a:entry", ATOM):
        stats = e.find("media:group/media:community/media:statistics", ATOM)
        uploads.append({
            "published": datetime.fromisoformat(e.find("a:published", ATOM).text),
            "views": int(stats.get("views", 0)) if stats is not None else 0,
            "is_short": "/shorts/" in e.find("a:link", ATOM).get("href", ""),
        })
    return uploads


def channel_info(ydl, channel_id: str) -> dict:
    """Subscriber count, handle, description, and lengths of recent long videos."""
    info = ydl.extract_info(f"https://www.youtube.com/channel/{channel_id}/videos", download=False)
    durations = [e.get("duration") for e in info.get("entries") or [] if e.get("duration")]
    return {
        "subscribers": info.get("channel_follower_count") or 0,
        "handle": info.get("uploader_id") or "",
        "description": info.get("description") or "",
        "avg_minutes": round(sum(durations) / len(durations) / 60) if durations else 0,
    }


def rate_opportunity(long_30d: int, shorts_30d: int) -> str:
    """How much a clipping service would add: lots of long videos, few Shorts = high."""
    if long_30d >= 2 and shorts_30d == 0:
        return "HIGH"
    if long_30d >= 1 and shorts_30d <= 4:
        return "MEDIUM"
    return "LOW"


def cmd_creators(args) -> int:
    import yt_dlp

    quiet = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True}
    print(f"Searching YouTube for \"{args.niche}\" (long videos, {args.min_subs:,}-{args.max_subs:,} subs)...")
    with yt_dlp.YoutubeDL(quiet) as ydl:
        found = ydl.extract_info(f"ytsearch{args.search}:{args.niche}", download=False)

    # One entry per channel that posts long videos (podcast/interview-length).
    channels = {}
    for e in found.get("entries") or []:
        if e and e.get("channel_id") and (e.get("duration") or 0) >= args.min_minutes * 60:
            channels.setdefault(e["channel_id"], e.get("channel") or "")
    print(f"  {len(channels)} channels with {args.min_minutes}+ minute videos. Checking each...")

    now = datetime.now(timezone.utc)
    results = []
    with yt_dlp.YoutubeDL({**quiet, "playlistend": 10}) as ydl:
        for i, (cid, name) in enumerate(channels.items(), 1):
            if len(results) >= args.limit:
                break
            try:
                info = channel_info(ydl, cid)
                uploads = recent_uploads(cid)
            except Exception as e:  # one bad channel shouldn't stop the whole search
                print(f"  [{i}] {name}: skipped ({type(e).__name__})")
                continue
            subs = info["subscribers"]
            if not (args.min_subs <= subs <= args.max_subs):
                continue
            recent = [u for u in uploads if (now - u["published"]).days <= 30]
            long_recent = [u for u in recent if not u["is_short"]]
            shorts_recent = [u for u in recent if u["is_short"]]
            if not long_recent:
                continue  # not active with long videos in the last month
            last = max(u["published"] for u in uploads)
            emails = sorted(set(EMAIL_RE.findall(info["description"])))
            row = {
                "found_at": now.strftime("%Y-%m-%d"),
                "niche": args.niche,
                "channel": name,
                "handle": info["handle"],
                "subscribers": subs,
                "long_videos_30d": len(long_recent),
                "shorts_30d": len(shorts_recent),
                "avg_video_minutes": info["avg_minutes"],
                "avg_views_long": round(sum(u["views"] for u in long_recent) / len(long_recent)),
                "days_since_upload": (now - last).days,
                "clip_opportunity": rate_opportunity(len(long_recent), len(shorts_recent)),
                "email": "; ".join(emails),
                "url": f"https://www.youtube.com/channel/{cid}",
                "channel_id": cid,
            }
            results.append(row)
            print(f"  [{i}] {name}: {subs:,} subs, {row['long_videos_30d']} long / "
                  f"{row['shorts_30d']} shorts in 30 days -> {row['clip_opportunity']}")
            time.sleep(0.5)  # be polite to YouTube

    if not results:
        print("\nNo matching creators. Try a different niche, or widen --min-subs/--max-subs.")
        return 0

    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    results.sort(key=lambda r: (order[r["clip_opportunity"]], -r["long_videos_30d"]))
    print(f"\n{len(results)} creators (best clipping prospects first):\n")
    for r in results:
        print(f"  {r['clip_opportunity']:6} {r['channel'][:35]:35} {r['subscribers']:>10,} subs  "
              f"{r['long_videos_30d']} long/{r['shorts_30d']} shorts  ~{r['avg_video_minutes']} min"
              + (f"  {r['email']}" if r["email"] else ""))
    out = DATA_DIR / "creator_prospects.csv"
    new, skipped = save_rows(out, results, "channel_id")
    print(f"\nSaved {new} new to {out}" + (f" ({skipped} already in the list)" if skipped else ""))
    return 0


# ----------------------------------------------------------------- CLI

def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Korvellan Studios Prospect Finder")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("search", help="Find local businesses (OpenStreetMap)")
    p.add_argument("--city", required=True, help='City, ideally with state: "Stillwater, MN"')
    p.add_argument("--industry", required=True, help=f"One of: {', '.join(INDUSTRIES)} (or any word)")
    p.add_argument("--radius-km", type=int, default=15, help="Search radius around the city (default 15)")
    p.add_argument("-l", "--limit", type=int, default=50, help="Max results (default 50)")

    p = sub.add_parser("creators", help="Find YouTube creators who'd benefit from clipping")
    p.add_argument("--niche", required=True, help='What to search, e.g. "business podcast"')
    p.add_argument("--min-subs", type=int, default=5_000)
    p.add_argument("--max-subs", type=int, default=500_000)
    p.add_argument("--min-minutes", type=int, default=20, help="Only channels posting videos this long+")
    p.add_argument("-l", "--limit", type=int, default=25, help="Max creators to return (default 25)")
    p.add_argument("--search", type=int, default=80, help="How many search results to scan (default 80)")

    args = parser.parse_args()
    print("=" * 60 + "\n   Korvellan Studios Prospect Finder\n" + "=" * 60)
    try:
        return cmd_search(args) if args.command == "search" else cmd_creators(args)
    except (ValueError, RuntimeError, requests.RequestException) as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
