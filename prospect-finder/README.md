# Prospect Finder

A command-line sales prospecting tool for Korvellan Studios: find local businesses to pitch on our services.

## Features

### Implemented

- **Search local businesses** using OpenStreetMap's Overpass API
  - Search by city and industry (plumbers, HVAC, electricians, contractors)
  - Shows business name, address, phone number, and website
  - Saves results to a CSV file, skipping duplicates
  - Handles API rate limits, timeouts, and failures
- **Command-line interface** for running searches

### Coming soon

- **Organize contact information** from public business listings, websites, and directories
- **AI-assisted outreach**: personalized outreach scripts and email templates per prospect

## Setup

This project uses [uv](https://docs.astral.sh/uv/) to manage Python.

```powershell
cd prospect-finder
uv venv
uv pip install -r requirements.txt
```

## Usage

```powershell
uv run main.py search --city "STILLWATER" --industry plumber
uv run main.py search --city "MINNEAPOLIS" --industry hvac
```

Options:
- `--city`: city to search in
- `--industry`: industry type (plumber, hvac, electrician, contractor, etc.)
- `-l` or `--limit`: maximum number of results (default: 20)

Results are shown on screen and saved to `data/prospects.csv`.

## Project structure

- `main.py`: entry point and search logic
- `requirements.txt`: Python dependencies
- `.gitignore`: keeps secrets and generated data out of git
- `data/`: prospect CSV exports (not committed)

## Security notes

- Never commit `.env` files containing API keys or credentials
- Generated prospect data is excluded from version control

## Roadmap

- Integration with public business directories
- AI-generated outreach content
- CRM integration for follow-up tracking
- Reporting and analytics dashboard
