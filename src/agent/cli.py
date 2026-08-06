"""Interactive CLI — chat with the GM agent for Eat the Reich."""

from __future__ import annotations

import json

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.agent.loop import AgentLoop
from src.gia import server as server_module

console = Console()


def print_banner():
    console.print(Panel(
        "[bold red]Gia — EAT THE REICH[/bold red]\n"
        "[dim]Affordance-Driven TTRPG Backend (Havoc Engine)[/dim]\n\n"
        "Commands:\n"
        "  [cyan]quit[/cyan]         — Exit the game\n"
        "  [cyan]state[/cyan]        — View current session state\n"
        "  [cyan]affordances[/cyan]  — View available actions\n"
        "  [cyan]characters[/cyan]   — List available characters\n"
        "  [cyan]scene[/cyan]        — View current scene\n"
        "  [cyan]sheet[/cyan]        — View active character sheet\n\n"
        "Type anything else to talk to the GM.",
        style="red",
    ))


def print_affordances_from_json(result_str: str):
    try:
        data = json.loads(result_str)
        affs = data.get("affordances", [])
    except (json.JSONDecodeError, AttributeError):
        affs = []

    if not affs:
        console.print("[dim]No actions available[/dim]")
        return

    table = Table(title="Available Actions", show_lines=True)
    table.add_column("Action", style="cyan bold")
    table.add_column("Description", style="white")
    table.add_column("Constraints", style="yellow")

    for a in affs:
        constraints = ", ".join(a.get("constraints", [])) or "-"
        table.add_row(a["action"], a["description"], constraints)

    console.print(table)


def print_character_summary(chars: list[dict]):
    table = Table(title="Vampire Commandos", show_lines=True)
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Description", style="white")

    for c in chars:
        table.add_row(c["id"], c["name"], c.get("description", "")[:80])

    console.print(table)


def main():
    print_banner()

    session_id = json.loads(server_module.create_session())["data"]["id"]
    agent = AgentLoop(server_module, session_id)
    console.print(f"[dim]Session: {session_id}[/dim]\n")

    # Show initial state
    result = server_module.search(resource_type="characters", session_id=session_id)
    data = json.loads(result)
    print_character_summary(data.get("data", []))
    console.print()
    print_affordances_from_json(result)
    console.print()

    while True:
        try:
            user_input = console.input("[bold green]You:[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]The vampires retreat into the shadows...[/dim]")
            break

        if not user_input:
            continue

        if user_input.lower() == "quit":
            console.print("[dim]The vampires retreat into the shadows...[/dim]")
            break

        if user_input.lower() == "state":
            state = server_module.get(resource_type="session", session_id=session_id)
            console.print_json(state)
            continue

        if user_input.lower() == "affordances":
            state = server_module.get(resource_type="session", session_id=session_id)
            print_affordances_from_json(state)
            continue

        if user_input.lower() == "characters":
            result = server_module.search(resource_type="characters", session_id=session_id)
            data = json.loads(result)
            print_character_summary(data.get("data", []))
            continue

        if user_input.lower() == "scene":
            result = server_module.get(resource_type="scene", session_id=session_id)
            console.print_json(result)
            continue

        if user_input.lower() == "sheet":
            result = server_module.act(action="view_character_sheet", params="{}", session_id=session_id)
            console.print_json(result)
            continue

        # Send to GM agent
        console.print("[dim]GM is thinking...[/dim]")
        try:
            response = agent.chat(user_input)
            console.print(f"\n[bold red]GM:[/bold red] {response}\n")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]\n")


if __name__ == "__main__":
    main()
