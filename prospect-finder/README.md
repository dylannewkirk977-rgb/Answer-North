# Prospect Finder

Sales lead lists for Korvellan Studios:

- **`creators`**: YouTube creators who'd benefit from the Clipper (long videos, few Shorts)
- **`search`**: local businesses (for websites, promo videos, AI receptionists)

Results are saved as CSV in `data/` (not committed) and can be opened in Excel or Google Sheets. Re-running adds only new entries.

## Setup

```powershell
cd prospect-finder
uv venv
uv pip install -r requirements.txt
```

## Find creators to pitch the Clipper

```powershell
uv run main.py creators --niche "business podcast"
uv run main.py creators --niche "true crime podcast" --min-subs 10000 --max-subs 200000
```

Searches YouTube, keeps channels posting long videos (20+ min) in the subscriber range, then checks each channel's last 15 uploads (public RSS feed) for activity and Shorts.

| `clip_opportunity` | Meaning |
|---|---|
| **HIGH** | 2+ long videos in the last 30 days and **no Shorts**: no clipper yet |
| **MEDIUM** | Posting long videos, only a few Shorts |
| **LOW** | Already posts lots of Shorts (probably has a clipper) |

Columns include subscribers, long videos / Shorts in 30 days, average video length, average views, days since last upload, any email found in the channel description, and the channel link. Options: `--min-subs`, `--max-subs`, `--min-minutes`, `-l/--limit`, `--search` (how many results to scan). ~25 s per run.

Review the list by hand: search results include some poor fits (e.g. corporate channels).

## Find local businesses

```powershell
uv run main.py search --industry plumber                     # whole Twin Cities metro (default)
uv run main.py search --industry dentist --city "Minneapolis, MN" --city "St Paul, MN"
```

By default it searches the **Minneapolis–St. Paul metro** (7 counties: Hennepin, Ramsey, Dakota, Anoka, Washington, Scott, Carver). Use `--city` (repeatable, with `--radius-km`, default 10) to narrow it down. Results are sorted by city; the first 40 are printed (`--show-all` for everything) and all are saved to the CSV with a `city` column.

Industries with presets: plumber, hvac, electrician, contractor, roofer, landscaper, painter, dentist, salon, auto_repair, lawyer, real_estate. Any other word searches business names.

Shows name, phone, email, website, and address. Businesses with **no website** are flagged: they're website leads. Data comes from OpenStreetMap (free), which is incomplete for small businesses. The free OpenStreetMap servers are often overloaded; the tool tries three of them and retries once, and if all are busy, try again later.

## Security notes

- Never commit `.env` files containing API keys or credentials
- Generated prospect data (`data/*.csv`) is excluded from version control
