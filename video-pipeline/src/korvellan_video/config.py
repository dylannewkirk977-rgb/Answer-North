"""Load config.yaml."""
from pathlib import Path

import yaml

PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_DIR / "config.yaml"


def load_config(path: Path | None = None) -> dict:
    path = Path(path) if path else DEFAULT_CONFIG
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    out = Path(cfg.get("output_dir", "output"))
    cfg["output_dir"] = out if out.is_absolute() else PROJECT_DIR / out
    return cfg
