"""Scripted demo — walks through a full combat round showing the Havoc Engine in action."""

from __future__ import annotations

import json

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.gia import server as server_module

console = Console()


def print_step(step_num: int, description: str):
    console.print(f"\n{'='*60}")
    console.print(f"[bold yellow]Step {step_num}:[/bold yellow] {description}")
    console.print(f"{'='*60}")


def print_affordances(response: dict):
    affs = response.get("affordances", [])
    if not affs:
        return

    table = Table(title="Affordances", show_lines=True)
    table.add_column("Action", style="cyan bold")
    table.add_column("Description", style="white")

    for a in affs[:8]:  # limit to first 8 for readability
        table.add_row(a["action"], a["description"][:80])

    if len(affs) > 8:
        table.add_row("...", f"[dim]+{len(affs)-8} more[/dim]")

    console.print(table)


def print_events(response: dict):
    events = response.get("events", [])
    for e in events:
        console.print(f"  [bold magenta]EVENT:[/bold magenta] {e['type']} — {json.dumps(e.get('data', {}))}")


def call(fn, **kwargs) -> dict:
    result_str = fn(**kwargs)
    return json.loads(result_str)


def main():
    console.print(Panel(
        "[bold red]EAT THE REICH — Demo Scenario[/bold red]\n"
        "Session setup → Character selection → Coffinfall → Combat round → Scene resolution\n\n"
        "[dim]This demo walks through the complete game flow with the affordance-driven backend.[/dim]",
        style="red",
    ))

    session_id = server_module.DEFAULT_SESSION_ID
    console.print(f"[dim]Session: {session_id}[/dim]")

    # Step 1: Browse available characters
    print_step(1, "Browse available characters")
    result = call(server_module.search, resource_type="characters")
    for c in result.get("data", []):
        console.print(f"  [cyan]{c['id']}[/cyan] — {c['name']}: {c['description'][:60]}...")
    print_affordances(result)

    # Step 2: Select Iryna
    print_step(2, "Select Iryna — the gothic socialite warlock")
    result = call(server_module.act, action="select_character",
                  params='{"template_id": "iryna"}')
    console.print(f"  [green]{result['data']['message']}[/green]")
    iryna_id = result["data"]["character_id"]

    # Step 3: Select Chuck
    print_step(3, "Select Chuck — the rotting cowboy")
    result = call(server_module.act, action="select_character",
                  params='{"template_id": "chuck"}')
    console.print(f"  [green]{result['data']['message']}[/green]")
    chuck_id = result["data"]["character_id"]

    # Step 4: Start the mission
    print_step(4, "COFFINFALL — Start the mission!")
    result = call(server_module.act, action="start_mission", params="{}")
    data = result["data"]
    console.print(f"\n  [bold red]{data['message']}[/bold red]")
    console.print(f"  Location: {data['location']}")
    console.print(f"  {data['location_description']}")
    console.print(f"  Objective: {data['objective']} (rating {data['objective_rating']})")
    for t in data.get("threats", []):
        console.print(f"  Threat: {t['name']} (rating {t['rating']}, attack {t['attack']})")
    console.print(f"  Active character: {data['active_character']}")
    print_affordances(result)

    # Step 5: Iryna engages the first threat
    print_step(5, "Iryna engages the enemy!")
    threat_name = data["threats"][0]["name"]
    result = call(server_module.act, action="engage_threat",
                  params=json.dumps({"threat_name": threat_name}))
    console.print(f"  [red]{result['data']['message']}[/red]")
    if "threat" in result["data"]:
        t = result["data"]["threat"]
        console.print(f"  {t['name']}: rating {t['rating']}, attack {t['attack']}, challenge {t['challenge']}")
    print_affordances(result)

    # Step 6: Build dice pool — SHOOT with hunting rifle
    print_step(6, "Build dice pool — Iryna uses SHOOT + Exquisite hunting rifle")
    result = call(server_module.act, action="build_dice_pool",
                  params=json.dumps({
                      "stat": "shoot",
                      "equipment_names": ["Exquisite hunting rifle"],
                      "bonus_dice": 0,
                  }))
    data = result["data"]
    console.print(f"\n  [bold]{data['message']}[/bold]")
    console.print(f"  Pool: stat({data['pool_breakdown']['stat']}) + equipment({data['pool_breakdown']['equipment']}) + bonus({data['pool_breakdown']['bonus']}) = {data['pool_breakdown']['total']}d6")
    console.print()
    for line in data["roll_summary"].split("\n"):
        console.print(f"  {line}")
    console.print()
    console.print(f"  [green]Player kept: {data['player_kept']}[/green]")
    console.print(f"  [red]GM kept: {data['gm_kept']}[/red]")
    print_affordances(result)

    # Step 7: Allocate dice
    print_step(7, "Allocate dice — split between objective, threat, and defense")
    player_kept = data["player_kept"]

    # Smart allocation: put highest dice on objectives, defend against GM
    allocations = {"objective": [], "threat": [], "defense": [], "feed": [], "special": []}
    sorted_dice = sorted(player_kept, reverse=True)
    for i, die in enumerate(sorted_dice):
        if i == 0:
            allocations["objective"].append(die)
        elif i == 1:
            allocations["threat"].append(die)
        elif i == 2:
            allocations["defense"].append(die)
        else:
            allocations["feed"].append(die)

    console.print(f"  Allocations: {json.dumps(allocations)}")
    result = call(server_module.act, action="allocate_dice",
                  params=json.dumps({"allocations": allocations}))
    data = result["data"]
    console.print(f"\n  [bold]{data['message']}[/bold]")

    if "scene_status" in data:
        console.print("\n  Scene Status:")
        for o in data["scene_status"]["objectives"]:
            status = "[green]COMPLETE[/green]" if o["completed"] else f"rating {o['rating']}"
            console.print(f"    Objective: {o['name']} — {status}")
        for t in data["scene_status"]["threats"]:
            status = "[green]DEFEATED[/green]" if t["defeated"] else f"rating {t['rating']}, attack {t['attack']}"
            console.print(f"    Threat: {t['name']} — {status}")

    if data.get("remaining_gm_dice", 0) > 0:
        console.print(f"\n  [red]GM had {data['remaining_gm_dice']} remaining dice — injury![/red]")

    print_events(result)
    print_affordances(result)

    # Step 8: Switch to Chuck's turn
    print_step(8, "Switch to Chuck's turn")
    result = call(server_module.act, action="next_turn",
                  params=json.dumps({"character_id": chuck_id}))
    console.print(f"  [green]{result['data']['message']}[/green]")

    # Step 9: View Chuck's character sheet
    print_step(9, "View Chuck's character sheet")
    result = call(server_module.act, action="view_character_sheet",
                  params=json.dumps({"character_id": chuck_id}))
    sheet = result["data"]
    console.print(f"  Name: {sheet['state']['name']}")
    console.print(f"  Blood: {sheet['state']['blood']}/10")
    console.print(f"  Stats: {json.dumps(sheet['effective_stats'])}")
    console.print(f"  Equipment:")
    for eq in sheet["state"]["equipment"]:
        console.print(f"    {eq['name']} — {eq['uses_remaining']} uses")

    # Step 10: View scene
    print_step(10, "View current scene status")
    result = call(server_module.act, action="view_scene", params="{}")
    scene = result["data"]
    console.print(f"  Location: {scene['location_id']}")
    for o in scene["active_objectives"]:
        status = "[green]COMPLETE[/green]" if o["is_completed"] else f"rating {o['current_rating']}"
        console.print(f"  Objective: {o['name']} — {status}")
    for t in scene["active_threats"]:
        status = "[green]DEFEATED[/green]" if t["is_defeated"] else f"T{t['current_rating']}/A{t['current_attack']}"
        console.print(f"  Threat: {t['name']} — {status}")

    console.print(Panel(
        "[bold green]Demo complete![/bold green]\n\n"
        "The affordance-driven architecture works:\n"
        "  [cyan]setup[/cyan] → select characters, start mission\n"
        "  [cyan]exploration[/cyan] → move, engage threats, loot, share blood\n"
        "  [cyan]engagement (pre-roll)[/cyan] → build dice pool (stat + equipment)\n"
        "  [cyan]engagement (post-roll)[/cyan] → allocate dice to obj/threat/defense/feed/special\n"
        "  [cyan]between scenes[/cyan] → heal, share blood, choose next location\n\n"
        "Run [bold]python -m agent.cli[/bold] for interactive play with the GM agent.",
        style="green",
    ))


if __name__ == "__main__":
    main()
