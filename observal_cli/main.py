import typer
import httpx
from rich import print as rprint
from rich.table import Table
from rich.console import Console
from typing import Optional
from observal_cli import config, client

app = typer.Typer(name="observal", help="Observal MCP Server Registry CLI")
review_app = typer.Typer(help="Admin review commands")
app.add_typer(review_app, name="review")
console = Console()

# ── Phase 1 ──────────────────────────────────────────────


@app.command()
def init():
    """First-run setup: configure server and create admin account."""
    server_url = typer.prompt("Server URL", default="http://localhost:8000")
    admin_email = typer.prompt("Admin email")
    admin_name = typer.prompt("Admin name")
    try:
        r = httpx.post(
            f"{server_url.rstrip('/')}/api/v1/auth/init",
            json={"email": admin_email, "name": admin_name},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        config.save({"server_url": server_url, "api_key": data["api_key"]})
        rprint(f"[green]Initialized! API key saved to {config.CONFIG_FILE}[/green]")
    except httpx.ConnectError:
        rprint("[red]Connection failed. Is the server running?[/red]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as e:
        rprint(f"[red]Error {e.response.status_code}: {e.response.text}[/red]")
        raise typer.Exit(1)


@app.command()
def login():
    """Login with an existing API key."""
    server_url = typer.prompt("Server URL", default="http://localhost:8000")
    api_key = typer.prompt("API Key", hide_input=True)
    try:
        r = httpx.get(
            f"{server_url.rstrip('/')}/api/v1/auth/whoami",
            headers={"X-API-Key": api_key},
            timeout=30,
        )
        r.raise_for_status()
        user = r.json()
        config.save({"server_url": server_url, "api_key": api_key})
        rprint(f"[green]Logged in as {user['name']} ({user['email']})[/green]")
    except httpx.ConnectError:
        rprint("[red]Connection failed. Is the server running?[/red]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError:
        rprint("[red]Invalid API key or server error.[/red]")
        raise typer.Exit(1)


@app.command()
def whoami():
    """Show current authenticated user."""
    user = client.get("/api/v1/auth/whoami")
    rprint(f"[bold]{user['name']}[/bold] ({user['email']})")
    rprint(f"Role: {user.get('role', 'N/A')}")


# ── Phase 2 ──────────────────────────────────────────────


@app.command()
def submit(git_url: str = typer.Argument(..., help="Git repository URL")):
    """Submit an MCP server for review."""
    rprint(f"[dim]Analyzing {git_url}...[/dim]")
    try:
        prefill = client.post("/api/v1/mcps/analyze", {"git_url": git_url})
    except (Exception,SystemExit):
        rprint("[yellow]Could not analyze repo, please fill in details manually[/yellow]")
        prefill = {}

    name = typer.prompt("Name", default=prefill.get("name", ""))
    version = typer.prompt("Version (semver)", default=prefill.get("version", "0.1.0"))
    category = typer.prompt("Category")
    description = typer.prompt("Description", default=prefill.get("description", ""))
    owner = typer.prompt("Owner / Team")

    ide_choices = ["vscode", "cursor", "windsurf", "kiro", "claude_code", "gemini_cli"]
    rprint(f"Available IDEs: {', '.join(ide_choices)}")
    ides_input = typer.prompt("Supported IDEs (comma-separated)")
    supported_ides = [i.strip() for i in ides_input.split(",") if i.strip()]

    setup_instructions = typer.prompt("Setup instructions", default="")
    changelog = typer.prompt("Changelog", default="Initial release")

    result = client.post("/api/v1/mcps/submit", {
        "git_url": git_url,
        "name": name,
        "version": version,
        "category": category,
        "description": description,
        "owner": owner,
        "supported_ides": supported_ides,
        "setup_instructions": setup_instructions,
        "changelog": changelog,
    })
    rprint(f"[green]Submitted! ID: {result['id']} — Status: {result.get('status', 'pending')}[/green]")


@app.command(name="list")
def list_mcps(
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Filter by category"),
    search: Optional[str] = typer.Option(None, "--search", "-s", help="Search term"),
):
    """List available MCP servers."""
    params = {}
    if category:
        params["category"] = category
    if search:
        params["search"] = search
    data = client.get("/api/v1/mcps", params=params)

    table = Table(title="MCP Servers")
    table.add_column("ID", style="dim")
    table.add_column("Name", style="bold")
    table.add_column("Version")
    table.add_column("Category")
    table.add_column("Owner")
    for item in data:
        table.add_row(str(item["id"]), item["name"], item.get("version", ""), item.get("category", ""), item.get("owner", ""))
    console.print(table)


@app.command()
def show(mcp_id: str = typer.Argument(..., help="MCP server ID")):
    """Show full details of an MCP server."""
    item = client.get(f"/api/v1/mcps/{mcp_id}")
    rprint(f"[bold]{item['name']}[/bold] v{item.get('version', '?')}")
    rprint(f"Category: {item.get('category', 'N/A')}")
    rprint(f"Owner: {item.get('owner', 'N/A')}")
    rprint(f"Description: {item.get('description', '')}")
    rprint(f"IDEs: {', '.join(item.get('supported_ides', []))}")
    rprint(f"Setup: {item.get('setup_instructions', 'N/A')}")
    rprint(f"Git: {item.get('git_url', 'N/A')}")


@app.command()
def install(
    mcp_id: str = typer.Argument(..., help="MCP server ID"),
    ide: str = typer.Option(..., "--ide", help="Target IDE"),
):
    """Get install config for an MCP server."""
    result = client.post(f"/api/v1/mcps/{mcp_id}/install", {"ide": ide})
    rprint(f"[green]Config snippet for {ide}:[/green]")
    rprint(result.get("config_snippet", ""))


# ── Review subcommands ───────────────────────────────────


@review_app.command(name="list")
def review_list():
    """List pending submissions (admin only)."""
    data = client.get("/api/v1/review")
    table = Table(title="Pending Reviews")
    table.add_column("ID", style="dim")
    table.add_column("Name", style="bold")
    table.add_column("Submitted By")
    table.add_column("Status")
    for item in data:
        table.add_row(str(item["id"]), item.get("name", ""), item.get("submitted_by", ""), item.get("status", ""))
    console.print(table)


@review_app.command(name="show")
def review_show(review_id: str = typer.Argument(..., help="Review ID")):
    """Show review details (admin only)."""
    item = client.get(f"/api/v1/review/{review_id}")
    rprint(f"[bold]{item.get('name', '')}[/bold] — Status: {item.get('status', '')}")
    rprint(f"Submitted By: {item.get('submitted_by', 'N/A')}")
    rprint(f"Git URL: {item.get('git_url', 'N/A')}")
    rprint(f"Description: {item.get('description', '')}")


@review_app.command(name="approve")
def review_approve(review_id: str = typer.Argument(..., help="Review ID")):
    """Approve a submission (admin only)."""
    result = client.post(f"/api/v1/review/{review_id}/approve")
    rprint(f"[green]Approved: {result.get('name', review_id)}[/green]")


@review_app.command(name="reject")
def review_reject(
    review_id: str = typer.Argument(..., help="Review ID"),
    reason: str = typer.Option(..., "--reason", "-r", help="Rejection reason"),
):
    """Reject a submission (admin only)."""
    result = client.post(f"/api/v1/review/{review_id}/reject", {"reason": reason})
    rprint(f"[yellow]Rejected: {result.get('name', review_id)}[/yellow]")


if __name__ == "__main__":
    app()
