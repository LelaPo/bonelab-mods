import sys
import json
import requests
from pathlib import Path

# Добавляем корень проекта в sys.path для корректных импортов
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.cli.ui import console, render_mods_table
from src.services.gist import GistService
from src.core.collections import CollectionManager


def load_legacy_registry(gist_service: GistService) -> dict:
    """Вычитывает старый registry.json из мастер-гиста."""
    files = gist_service._fetch_master_gist()
    if "registry.json" not in files:
        return {}
    try:
        content = json.loads(files["registry.json"]["content"])
        return content if isinstance(content, dict) else {}
    except Exception:
        return {}


def fetch_legacy_pack(url: str) -> list:
    """Загружает список модов по raw URL старого гиста."""
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data.get("mods", [])


def run_migration():
    console.rule("[bold magenta]Миграция старых коллекций (v1 -> v2)[/bold magenta]")

    gist_service = GistService()
    cm = CollectionManager(gist_service)

    with console.status("[cyan]Чтение старого registry.json...[/cyan]"):
        legacy_registry = load_legacy_registry(gist_service)

    if not legacy_registry:
        console.print("[red][!] В мастер-гисте не найден старый registry.json или он пуст.[/red]")
        return

    console.print(f"[green][+] Найдено старых паков:[/green] {len(legacy_registry)}\n")

    legacy_packs_data = {}
    with console.status("[cyan]Загрузка содержимого старых паков...[/cyan]"):
        for code, url in legacy_registry.items():
            try:
                mods = fetch_legacy_pack(url)
                legacy_packs_data[code] = mods
            except Exception as e:
                console.print(f"[yellow][!] Не удалось загрузить '{code}': {e}[/yellow]")

    # Отображаем список старых паков
    console.print("[bold]Доступные старые паки:[/bold]")
    pack_keys = list(legacy_packs_data.keys())
    for idx, code in enumerate(pack_keys, 1):
        m_count = len(legacy_packs_data[code])
        console.print(f"  [{idx}] [bold cyan]{code}[/bold cyan] ({m_count} модов)")

    console.print("\n[dim]Введите номера паков для объединения (например: 2, 3) или 'all':[/dim]")
    selection = console.input("Выбор паков: ").strip()
    if not selection:
        console.print("[yellow]Отменено.[/yellow]")
        return

    chosen_mods = []
    chosen_names = []
    if selection.lower() == "all":
        for k in pack_keys:
            chosen_names.append(k)
            chosen_mods.extend(legacy_packs_data[k])
    else:
        parts = [p.strip() for p in selection.replace(",", " ").split() if p.strip().isdigit()]
        for p in parts:
            idx = int(p) - 1
            if 0 <= idx < len(pack_keys):
                name = pack_keys[idx]
                chosen_names.append(name)
                chosen_mods.extend(legacy_packs_data[name])

    if not chosen_mods:
        console.print("[red][!] Не выбрано ни одного мода.[/red]")
        return

    # Дедупликация модов по mod['id']
    unique_mods = []
    seen_ids = set()
    for mod in chosen_mods:
        mid = mod.get("id")
        if mid not in seen_ids:
            seen_ids.add(mid)
            unique_mods.append(mod)

    console.print(f"\n[green][+] Отобрано модов после дедупликации:[/green] [bold]{len(unique_mods)}[/bold]")
    console.print(f"[dim]Источники:[/dim] {', '.join(chosen_names)}\n")

    # Спрашиваем, куда мигрировать: в новую или существующую
    existing_cols = cm.list_collections()
    console.print("[bold]Куда импортировать моды?[/bold]")
    console.print("  [0] Создать НОВУЮ коллекцию")
    for idx, c in enumerate(existing_cols, 1):
        console.print(f"  [{idx}] В существующую: [bold cyan]{c['name']}[/bold cyan] ({len(c.get('mods', []))} модов)")

    dest_choice = console.input(f"\nВыбор [0-{len(existing_cols)}]: ").strip()
    target_slug = None

    if dest_choice == "0":
        target_name = console.input("Название новой коллекции: ").strip()
        target_desc = console.input("Описание (опционально): ").strip()
        with console.status("[cyan]Создание коллекции в Gist...[/cyan]"):
            col_data = cm.create_collection(target_name, target_desc)
            target_slug = col_data["slug"]
    elif dest_choice.isdigit() and 1 <= int(dest_choice) <= len(existing_cols):
        target_slug = existing_cols[int(dest_choice) - 1]["slug"]
    else:
        console.print("[yellow]Отменено.[/yellow]")
        return

    # Добавляем моды в выбранную коллекцию
    with console.status(f"[cyan]Импорт {len(unique_mods)} модов в коллекцию '{target_slug}'...[/cyan]"):
        cols = gist_service.get_collections()
        target_col = cols.get(target_slug)

        existing_in_col = {m.get("id") for m in target_col.get("mods", [])}
        added_count = 0

        for mod in unique_mods:
            if mod.get("id") not in existing_in_col:
                target_col["mods"].append(mod)
                existing_in_col.add(mod.get("id"))
                added_count += 1

        cols[target_slug] = target_col
        gist_service.save_collections(cols)

    console.print(f"\n[bold green][+] Успешно импортировано {added_count} новых модов в коллекцию '{target_slug}'![/bold green]")
    console.print(f"[dim]Всего модов в коллекции сейчас:[/dim] {len(target_col['mods'])}\n")


if __name__ == "__main__":
    try:
        run_migration()
    except KeyboardInterrupt:
        sys.exit(0)