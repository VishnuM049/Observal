import httpx
import typer
from observal_cli import config


def _client() -> tuple[str, dict]:
    cfg = config.get_or_exit()
    return cfg["server_url"].rstrip("/"), {"X-API-Key": cfg["api_key"]}


def get(path: str, params: dict | None = None) -> dict:
    base, headers = _client()
    try:
        r = httpx.get(f"{base}{path}", headers=headers, params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        detail = e.response.json().get("detail", e.response.text) if e.response.headers.get("content-type", "").startswith("application/json") else e.response.text
        raise typer.Exit(f"Error {e.response.status_code}: {detail}")
    except httpx.ConnectError:
        raise typer.Exit("Connection failed. Is the server running?")


def post(path: str, json_data: dict | None = None) -> dict:
    base, headers = _client()
    try:
        r = httpx.post(f"{base}{path}", headers=headers, json=json_data, timeout=30)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        detail = e.response.json().get("detail", e.response.text) if e.response.headers.get("content-type", "").startswith("application/json") else e.response.text
        raise typer.Exit(f"Error {e.response.status_code}: {detail}")
    except httpx.ConnectError:
        raise typer.Exit("Connection failed. Is the server running?")
