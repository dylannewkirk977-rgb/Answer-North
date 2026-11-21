"""Local OpenStreetMap data: download a state's map file once, index its businesses,
and search them offline (no busy public servers).

Files (in prospect-finder/osm/, not committed):
  minnesota-latest.osm.pbf  raw map data from Geofabrik (~290 MB, refresh monthly)
  businesses.sqlite         index built from it: businesses + city/town names
"""
import hashlib
import json
import math
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import requests

OSM_DIR = Path(__file__).parent / "osm"
DB_PATH = OSM_DIR / "businesses.sqlite"
GEOFABRIK_INDEX = "https://download.geofabrik.de/index-v1-nogeom.json"
STATE = "us/minnesota"  # Geofabrik region id

BUSINESS_KEYS = ("shop", "craft", "office", "amenity", "healthcare")
KEEP_TAGS = re.compile(r"^(name|shop|craft|office|amenity|healthcare|phone|contact:.*|email|website|url|addr:.*)$")
PLACE_KINDS = {"city": 0, "town": 1, "village": 2, "suburb": 3, "hamlet": 4}  # lower = preferred


# ----------------------------------------------------------------- download

def download_map(user_agent: str) -> Path:
    """Download the latest state map file (and check it against Geofabrik's checksum)."""
    OSM_DIR.mkdir(parents=True, exist_ok=True)
    index = requests.get(GEOFABRIK_INDEX, headers={"User-Agent": user_agent}, timeout=60).json()
    url = next(f["properties"]["urls"]["pbf"] for f in index["features"] if f["properties"]["id"] == STATE)
    dest = OSM_DIR / Path(url).name
    tmp = dest.with_suffix(".download")

    print(f"Downloading {url}")
    with requests.get(url, headers={"User-Agent": user_agent}, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        done, md5, last = 0, hashlib.md5(), 0.0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                md5.update(chunk)
                done += len(chunk)
                if total and time.time() - last > 2:
                    print(f"  {done / 1e6:,.0f} / {total / 1e6:,.0f} MB", end="\r")
                    last = time.time()
    expected = requests.get(url + ".md5", headers={"User-Agent": user_agent}, timeout=60).text.split()[0]
    if md5.hexdigest() != expected:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("Downloaded map file is corrupted (checksum mismatch). Please try again.")
    tmp.replace(dest)
    print(f"\n  Saved {dest.name} ({done / 1e6:,.0f} MB, checksum OK)")
    return dest


# ----------------------------------------------------------------- build index

def build_index(pbf: Path) -> dict:
    """Read the map file and store every named business and place in SQLite."""
    import osmium

    class Handler(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.biz, self.places = [], []

        def _keep(self, tags) -> dict | None:
            if "name" not in tags or not any(k in tags for k in BUSINESS_KEYS):
                return None
            return {t.k: t.v for t in tags if KEEP_TAGS.match(t.k)}

        def node(self, n):
            if not n.location.valid():
                return
            kind = n.tags.get("place")
            if kind in PLACE_KINDS and "name" in n.tags:
                pop = n.tags.get("population", "0")
                self.places.append((n.tags["name"], n.location.lat, n.location.lon, kind,
                                    int(pop) if pop.isdigit() else 0))
            tags = self._keep(n.tags)
            if tags:
                self.biz.append((f"node/{n.id}", n.location.lat, n.location.lon, tags["name"], json.dumps(tags)))

        def way(self, w):
            tags = self._keep(w.tags)
            if not tags:
                return
            pts = [(nd.lat, nd.lon) for nd in w.nodes if nd.location.valid()]
            if pts:  # use the middle of the building/area
                lat = sum(p[0] for p in pts) / len(pts)
                lon = sum(p[1] for p in pts) / len(pts)
                self.biz.append((f"way/{w.id}", lat, lon, tags["name"], json.dumps(tags)))

    print(f"Indexing {pbf.name} (takes a minute or two)...")
    t0 = time.time()
    h = Handler()
    h.apply_file(str(pbf), locations=True)  # locations=True gives ways their coordinates

    tmp = DB_PATH.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript("""
        CREATE TABLE biz (osm_id TEXT PRIMARY KEY, lat REAL, lon REAL, name TEXT, tags TEXT);
        CREATE TABLE places (name TEXT, lat REAL, lon REAL, kind TEXT, population INTEGER);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    con.executemany("INSERT OR IGNORE INTO biz VALUES (?,?,?,?,?)", h.biz)
    con.executemany("INSERT INTO places VALUES (?,?,?,?,?)", h.places)
    con.execute("CREATE INDEX biz_loc ON biz (lat, lon)")
    stats = {"businesses": len(h.biz), "places": len(h.places),
             "map_file_date": datetime.fromtimestamp(pbf.stat().st_mtime).strftime("%Y-%m-%d"),
             "built": datetime.now().strftime("%Y-%m-%d %H:%M")}
    con.executemany("INSERT INTO meta VALUES (?,?)", [(k, str(v)) for k, v in stats.items()])
    con.commit()
    con.close()
    tmp.replace(DB_PATH)
    print(f"  Indexed {stats['businesses']:,} businesses and {stats['places']:,} places "
          f"in {time.time() - t0:.0f}s -> {DB_PATH.name}")
    return stats


# ----------------------------------------------------------------- search

def _db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise RuntimeError("No local map data yet. Run once:  uv run main.py update-map")
    return sqlite3.connect(DB_PATH)


def map_info() -> dict:
    with _db() as con:
        return dict(con.execute("SELECT key, value FROM meta"))


def _normalize_place(name: str) -> str:
    n = name.lower().strip()
    n = re.sub(r",\s*(mn|minnesota)\.?$", "", n)
    n = re.sub(r"^(st\.?|saint)\s+", "saint ", n)  # "St Paul" / "St. Paul" -> "saint paul"
    return n.replace(".", "").strip()


def find_place(name: str) -> dict:
    """Look up a city/town by name in the local data (any capitalization, 'St'/'Saint' both work)."""
    target = _normalize_place(name)
    with _db() as con:
        rows = con.execute("SELECT name, lat, lon, kind, population FROM places").fetchall()
    matches = [r for r in rows if _normalize_place(r[0]) == target]
    if not matches:
        close = sorted({r[0] for r in rows if target in _normalize_place(r[0])})[:5]
        hint = f" Did you mean: {', '.join(close)}?" if close else ""
        raise ValueError(f"Couldn't find '{name}' in the Minnesota map data.{hint}")
    best = min(matches, key=lambda r: (PLACE_KINDS.get(r[3], 9), -r[4]))
    return {"name": best[0], "lat": best[1], "lon": best[2], "kind": best[3]}


_towns: list[tuple] | None = None


def nearest_town(lat: float, lon: float) -> str:
    """Name of the closest city/town/village (for businesses with no city in their address)."""
    global _towns
    if _towns is None:
        with _db() as con:
            _towns = con.execute(
                "SELECT name, lat, lon FROM places WHERE kind IN ('city', 'town', 'village')").fetchall()
    if not _towns:
        return ""
    return min(_towns, key=lambda t: (t[1] - lat) ** 2 + ((t[2] - lon) * 0.7) ** 2)[0]


def _km(lat1, lon1, lat2, lon2) -> float:
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def search(industry_spec: dict, bbox: tuple | None = None,
           circles: list[tuple] | None = None) -> list[dict]:
    """Businesses matching an industry inside a bbox (s, w, n, e) or circles [(lat, lon, km)]."""
    boxes = []
    if bbox:
        boxes.append(bbox)
    for lat, lon, km in circles or []:
        dlat = km / 111.0
        dlon = km / (111.0 * math.cos(math.radians(lat)))
        boxes.append((lat - dlat, lon - dlon, lat + dlat, lon + dlon))

    name_re = re.compile(industry_spec["name"], re.I)
    tag_pairs = set(industry_spec["tags"])
    out, seen = [], set()
    with _db() as con:
        for s, w, n, e in boxes:
            for osm_id, lat, lon, name, tags_json in con.execute(
                    "SELECT osm_id, lat, lon, name, tags FROM biz "
                    "WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?", (s, n, w, e)):
                if osm_id in seen:
                    continue
                if circles and not bbox and not any(_km(lat, lon, c[0], c[1]) <= c[2] for c in circles):
                    continue
                tags = json.loads(tags_json)
                if any(tags.get(k) == v for k, v in tag_pairs) or name_re.search(name):
                    seen.add(osm_id)
                    out.append({"osm_id": osm_id, "lat": lat, "lon": lon, "tags": tags})
    return out
