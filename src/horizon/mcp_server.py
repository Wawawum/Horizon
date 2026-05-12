"""MCP server for Horizon — exposes search and notes access via the local API."""
import asyncio
import json
import os
from pathlib import Path

import httpx
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server


def _base_url() -> str:
    port = os.environ.get("HORIZON_API_PORT")
    if not port:
        port_file = Path.home() / ".horizon" / "api.port"
        port = port_file.read_text().strip()
    return f"http://127.0.0.1:{port}"


server = Server("horizon")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search",
            description="Search notes and tasks in Horizon using full-text search.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The text to search for"},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="list_notes",
            description="List all active (non-archived) notes in Horizon.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="get_note",
            description="Get the full content of a Horizon note by its ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer", "description": "The note ID"},
                },
                "required": ["note_id"],
            },
        ),
    ]


async def _tool_search(client: httpx.AsyncClient, arguments: dict) -> list[types.TextContent]:
    query = arguments.get("query", "").strip()
    if not query:
        return [types.TextContent(type="text", text="Error: query is required")]
    resp = await client.get("/search", params={"q": query})
    data = resp.json()
    if resp.status_code != 200:
        return [types.TextContent(type="text", text=f"Error: {data.get('error', 'unknown')}")]
    results = data.get("results", [])
    if not results:
        return [types.TextContent(type="text", text="No results found.")]
    lines = [f"[{r['type']}] #{r['id']} — {r['title']}\n{r['body']}" for r in results]
    return [types.TextContent(type="text", text="\n\n".join(lines))]


async def _tool_list_notes(client: httpx.AsyncClient, arguments: dict) -> list[types.TextContent]:
    resp = await client.get("/notes")
    data = resp.json()
    if resp.status_code != 200:
        return [types.TextContent(type="text", text=f"Error: {data.get('error', 'unknown')}")]
    notes = data.get("notes", [])
    if not notes:
        return [types.TextContent(type="text", text="No notes found.")]
    return [types.TextContent(type="text", text=json.dumps(notes, ensure_ascii=False, indent=2))]


async def _tool_get_note(client: httpx.AsyncClient, arguments: dict) -> list[types.TextContent]:
    note_id = arguments.get("note_id")
    if note_id is None:
        return [types.TextContent(type="text", text="Error: note_id is required")]
    resp = await client.get(f"/notes/{note_id}")
    data = resp.json()
    if resp.status_code == 404:
        return [types.TextContent(type="text", text="Note not found.")]
    if resp.status_code != 200:
        return [types.TextContent(type="text", text=f"Error: {data.get('error', 'unknown')}")]
    note = data
    text = f"# {note['title']}\n\n{note['body']}\n\n---\nid: {note['id']} | dt: {note['dt']} | project_id: {note['project_id']}"
    return [types.TextContent(type="text", text=text)]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    async with httpx.AsyncClient(base_url=_base_url(), timeout=10.0) as client:
        if name == "search":
            return await _tool_search(client, arguments)
        elif name == "list_notes":
            return await _tool_list_notes(client, arguments)
        elif name == "get_note":
            return await _tool_get_note(client, arguments)
        else:
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


async def _async_main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
