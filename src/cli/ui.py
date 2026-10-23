from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from typing import List, Dict, Any

console = Console()


def print_banner(is_author_mode: bool):
    mode_label = "Developer / Author Mode" if is_author_mode else "Client Mode"
    console.print(
        Panel(
            f"[bold cyan]BONELAB MOD SYNC[/bold cyan]\n[dim]Profile: {mode_label}[/dim]",
            border_style="cyan",
            expand=False,
        )
    )


def render_mods_table(mods: List[Dict[str, Any]], title: str = "Список модов") -> Table:
    table = Table(title=title)
    table.add_column("#", width=4, style="dim")
    table.add_column("Название", style="cyan")
    table.add_column("Файл архива", style="magenta")
    table.add_column("File ID", style="dim", width=12)

    for idx, mod in enumerate(mods, 1):
        table.add_row(
            str(idx),
            mod.get("name", "Unknown"),
            mod.get("filename", "Unknown"),
            str(mod.get("file_id", "N/A")),
        )
    return table