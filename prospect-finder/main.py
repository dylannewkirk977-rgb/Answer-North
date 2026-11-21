"""Korvellan Studios Prospect Finder - find local businesses and YouTube creators to pitch.

Commands:
  search      local businesses (local OpenStreetMap data) -> data/local_prospects.csv
  update-map  download/refresh the Minnesota map data (monthly)
  creators    YouTube creators for the Clipper            -> data/creator_prospects.csv
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

import osm_local

USER_AGENT = "KorvellanStudiosProspectFinder/1.2"
DATA_DIR = Path(__file__).parent / "data"
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

# Search regions as bounding boxes (south, west, north, east).
REGIONS = {
    "twin-cities": {
        "label": "Minneapolis-St. Paul metro (7 counties)",
        # Hennepin, Ramsey, Dakota, Anoka, Washington, Scott, Carver
        "bbox": (44.47, -94.01, 45.42, -92.73),
    },
}


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

def to_business(el: dict, industry: str, area: str) -> dict | None:
    tags = el["tags"]
    name = tags.get("name", "").strip()
    if len(name) < 2 or not any(k in tags for k in BUSINESS_KEYS):
        return None
    street = " ".join(p for p in (tags.get("addr:housenumber"), tags.get("addr:street")) if p)
    address = ", ".join(p for p in (street, tags.get("addr:city"), tags.get("addr:state"),
                                    tags.get("addr:postcode")) if p)
    website = tags.get("website") or tags.get("contact:website") or tags.get("url") or ""
    if website and not website.startswith(("http://", "https://")):
        website = "https://" + website
    return {
        "found_at": datetime.now().strftime("%Y-%m-%d"),
        "industry": industry,
        "name": name,
        "phone": tags.get("phone") or tags.get("contact:phone") or "",
        "email": tags.get("email") or tags.get("contact:email") or "",
        "website": website,
        "has_website": "yes" if website else "NO",
        # City from the address; if missing, the nearest town (marked with ~).
        "city": tags.get("addr:city") or f"~{osm_local.nearest_town(el['lat'], el['lon'])}",
        "address": address,
        "searched_area": area,
        "lat": round(el["lat"], 6),
        "lon": round(el["lon"], 6),
        "osm_id": el["osm_id"],
    }


def cmd_search(args) -> int:
    industry = args.industry.lower().strip()
    if industry not in INDUSTRIES:
        print(f"Note: '{industry}' isn't a preset; searching business names for it. "
              f"Presets: {', '.join(INDUSTRIES)}")

    spec = INDUSTRIES.get(industry, {"tags": [], "name": re.escape(industry)})
    info = osm_local.map_info()
    print(f"Using local map data from {info.get('map_file_date')} "
          f"({int(info.get('businesses', 0)):,} Minnesota businesses)")

    if args.city:  # specific cities, each with a radius
        circles, labels = [], []
        for city in args.city:
            place = osm_local.find_place(city)
            circles.append((place["lat"], place["lon"], args.radius_km))
            labels.append(place["name"])
        area_label = " + ".join(labels)
        print(f"Searching for {industry} within {args.radius_km} km of {area_label}...")
        elements = osm_local.search(spec, circles=circles)
    else:  # a whole region
        region = REGIONS[args.region]
        area_label = region["label"]
        print(f"Searching for {industry} across {area_label}...")
        elements = osm_local.search(spec, bbox=region["bbox"])

    seen, results = set(), []
    for el in elements:
        b = to_business(el, industry, area_label)
        if not b:
            continue
        dupe_key = (b["name"].lower(), b["address"].lower())
        if dupe_key in seen:
            continue
        seen.add(dupe_key)
        results.append(b)
    results.sort(key=lambda b: (b["city"].lstrip("~").lower(), b["name"].lower()))
    results = results[: args.limit]

    if not results:
        print("\nNo businesses found. Try another industry, or a bigger --radius-km.")
        return 0

    no_site = sum(b["has_website"] == "NO" for b in results)
    with_phone = sum(bool(b["phone"]) for b in results)
    print(f"\nFound {len(results)} businesses ({with_phone} with a phone number, "
          f"{no_site} with no website listed):\n")
    show = results if args.show_all else results[:40]
    for b in show:
        print(f"  {b['name'][:38]:38} {b['city'][:16]:16} {b['phone'][:16]:16} "
              f"{'' if b['website'] else 'NO WEBSITE'}")
    if len(show) < len(results):
        print(f"  ... and {len(results) - len(show)} more in the CSV (use --show-all to list them here)")
    out = DATA_DIR / "local_prospects.csv"
    new, skipped = save_rows(out, results, "osm_id")
    print(f"\nSaved {new} new to {out}" + (f" ({skipped} already in the list)" if skipped else ""))
    return 0


def cmd_update_map(args) -> int:
    pbf = osm_local.OSM_DIR / "minnesota-latest.osm.pbf"
    if not args.skip_download:
        pbf = osm_local.download_map(USER_AGENT)
    elif not pbf.exists():
        raise RuntimeError(f"No map file at {pbf}; run without --skip-download.")
    osm_local.build_index(pbf)
    print("Map data ready. Refresh about once a month with: uv run main.py update-map")
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
    p.add_argument("--industry", required=True, help=f"One of: {', '.join(INDUSTRIES)} (or any word)")
    p.add_argument("--region", choices=list(REGIONS), default="twin-cities",
                   help="Region to search (default: twin-cities = Minneapolis-St. Paul metro)")
    p.add_argument("--city", action="append",
                   help='Search specific cities instead of the region (repeatable): --city "St Paul, MN"')
    p.add_argument("--radius-km", type=int, default=10, help="Radius around each --city (default 10)")
    p.add_argument("-l", "--limit", type=int, default=1000, help="Max results (default 1000)")
    p.add_argument("--show-all", action="store_true", help="Print every result, not just the first 40")

    p = sub.add_parser("update-map", help="Download the latest Minnesota map data and rebuild the index")
    p.add_argument("--skip-download", action="store_true", help="Only rebuild the index from the existing file")

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
        if args.command == "search":
            return cmd_search(args)
        if args.command == "update-map":
            return cmd_update_map(args)
        return cmd_creators(args)
    except (ValueError, RuntimeError, requests.RequestException) as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
