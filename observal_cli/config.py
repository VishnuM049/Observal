import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".observal"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}


def save(data: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


def get_or_exit() -> dict:
    cfg = load()
    if not cfg.get("server_url") or not cfg.get("api_key"):
        import typer
        raise typer.Exit("Not configured. Run 'observal init' or 'observal login' first.")
    return cfg
