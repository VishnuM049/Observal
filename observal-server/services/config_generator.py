from models.mcp import McpListing


def generate_config(listing: McpListing, ide: str) -> dict:
    name = listing.name
    if ide in ("cursor", "vscode"):
        return {"mcpServers": {name: {"command": "python", "args": ["-m", name], "env": {}}}}
    if ide == "kiro":
        return {"mcpServers": {name: {"command": "python", "args": ["-m", name], "env": {}}}}
    if ide == "claude-code":
        return {"command": f"claude mcp add {name} -- python -m {name}", "type": "shell_command"}
    if ide == "gemini-cli":
        return {"mcpServers": {name: {"command": "python", "args": ["-m", name]}}}
    # Default fallback
    return {"mcpServers": {name: {"command": "python", "args": ["-m", name], "env": {}}}}
