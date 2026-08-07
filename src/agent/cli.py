"""Interactive CLI — chat with the GM agent for Eat the Reich."""

from __future__ import annotations

import json

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.agent.loop import AgentLoop
from gia.server import GameRuntime

console = Console()


def _dump(result) -> dict:
    return result.model_dump(mode="json", by_alias=True)


def _act(runtime: GameRuntime, action: str, params: dict, session_id: str) -> dict:
    """Execute an action, resolving the current revision first.

    ``GameRuntime.act`` requires an explicit ``expected_revision`` for
    action-name dispatch — the deleted JSON compat path used to resolve
    this automatically.
    """
    revision = runtime.get("session", session_id=session_id).state_revision
    return _dump(runtime.act(action, params, session_id, revision))


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


def print_affordances(result: dict):
    affs = result.get("affordances", [])

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

    runtime = GameRuntime()
    session_id = runtime.create_session().data["id"]
    agent = AgentLoop(runtime, session_id)
    console.print(f"[dim]Session: {session_id}[/dim]\n")

    # Show initial state
    result = _dump(runtime.search(resource_type="characters", session_id=session_id))
    print_character_summary(result.get("data", []))
    console.print()
    print_affordances(result)
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
            state = _dump(runtime.get(resource_type="session", session_id=session_id))
            console.print_json(json.dumps(state))
            continue

        if user_input.lower() == "affordances":
            state = _dump(runtime.get(resource_type="session", session_id=session_id))
            print_affordances(state)
            continue

        if user_input.lower() == "characters":
            result = _dump(runtime.search(resource_type="characters", session_id=session_id))
            print_character_summary(result.get("data", []))
            continue

        if user_input.lower() == "scene":
            result = _dump(runtime.get(resource_type="scene", session_id=session_id))
            console.print_json(json.dumps(result))
            continue

        if user_input.lower() == "sheet":
            result = _act(runtime, "view_character_sheet", {}, session_id)
            console.print_json(json.dumps(result))
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
