from datetime import datetime, timezone
from typing import List, Dict, Any
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

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
    table.add_column("Mod ID", style="dim", width=10)
    table.add_column("File ID", style="dim", width=10)

    for idx, mod in enumerate(mods, 1):
        table.add_row(
            str(idx),
            mod.get("name", "Unknown"),
            mod.get("filename", "Unknown"),
            str(mod.get("id", "N/A")),
            str(mod.get("file_id", "N/A")),
        )
    return table


def render_collections_table(collections: List[Dict[str, Any]]) -> Table:
    table = Table(title="Ваши коллекции в облаке")
    table.add_column("#", width=4, style="dim")
    table.add_column("Название", style="bold cyan")
    table.add_column("Идентификатор (slug)", style="dim")
    table.add_column("Модов", justify="right", style="green", width=8)
    table.add_column("Описание", style="italic")

    for idx, col in enumerate(collections, 1):
        mod_count = len(col.get("mods", []))
        table.add_row(
            str(idx),
            col.get("name", "Без имени"),
            col.get("slug", "-"),
            str(mod_count),
            col.get("description", "") or "[dim]—[/dim]",
        )
    return table


def render_shares_table(shares: Dict[str, Any]) -> Table:
    table = Table(title="Активные раздачи (Share Codes)")
    table.add_column("Код раздачи", style="bold bright_cyan")
    table.add_column("Включенные коллекции", style="magenta")
    table.add_column("Модов", justify="right", style="green", width=8)
    table.add_column("Осталось времени", style="yellow")

    now = datetime.now(timezone.utc)
    for code, data in shares.items():
        exp_str = data.get("expires_at")
        time_left = "Бессрочно"
        if exp_str:
            try:
                exp_dt = datetime.fromisoformat(exp_str)
                delta = exp_dt - now
                if delta.total_seconds() <= 0:
                    time_left = "[red]Истек[/red]"
                else:
                    hours, rem = divmod(int(delta.total_seconds()), 3600)
                    minutes, _ = divmod(rem, 60)
                    time_left = f"{hours}ч {minutes}м"
            except Exception:
                time_left = "N/A"

        cols_str = ", ".join(data.get("collections", [])) or "Custom"
        mod_count = len(data.get("mods", []))
        table.add_row(code, cols_str, str(mod_count), time_left)

    return table