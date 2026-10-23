import sys
from pathlib import Path
from rich.progress import Progress, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn

from src.config import IS_AUTHOR_MODE, get_bonelab_mods_path
from src.cli.ui import console, print_banner, render_mods_table
from src.core.backup import count_installed_mods, backup_existing_mods
from src.core.installer import download_and_extract
from src.core.builder import PackBuilder
from src.services.gist import GistService
from src.services.discord import DiscordTracker


def action_install_pack():
    console.rule("[bold cyan]Установка пака[/bold cyan]")

    mods_dir = get_bonelab_mods_path()
    console.print(f"[dim]Путь установки:[/dim] [cyan]{mods_dir}[/cyan]")

    installed_count = count_installed_mods(mods_dir)
    if installed_count > 0:
        console.print(f"[dim]Обнаружено установленных модов:[/dim] [yellow]{installed_count}[/yellow]")
        make_backup = console.input("Сделать резервную копию (.zip) перед установкой? [y/N]: ").strip().lower()
        if make_backup == "y":
            b_path = backup_existing_mods(
                mods_dir,
                on_progress=lambda msg: console.print(f"[cyan]{msg}[/cyan]")
            )
            if b_path:
                console.print(f"[green][+] Резервная копия готова:[/green] [dim]{b_path}[/dim]\n")
    else:
        console.print("[dim]Директория модов чистая.[/dim]")

    console.print()
    passphrase = console.input("[bold]Введите код пака:[/bold] ").strip()
    if not passphrase:
        return

    gist_service = GistService()
    with console.status("[cyan]Подключение к облачному реестру...[/cyan]"):
        try:
            pack_data = gist_service.fetch_pack(passphrase)
        except Exception as e:
            console.print(f"[red][!] Ошибка получения пака: {e}[/red]\n")
            return

    mods = pack_data.get("mods", [])
    if not mods:
        console.print("[yellow][!] Пак не содержит модов для установки.[/yellow]\n")
        return

    console.print(f"\n[green][+] Найдено модов в паке:[/green] [bold]{len(mods)}[/bold]\n")
    console.print(render_mods_table(mods, title=f"Содержимое пака: {passphrase}"))
    console.print()

    dry_run = console.input("Тестовый режим (Dry-run в ./test_mods/)? [y/N]: ").strip().lower() == "y"
    target_dir = (Path.cwd() / "test_mods") if dry_run else mods_dir

    if dry_run:
        console.print(f"[yellow][*] Режим Dry-run:[/yellow] {target_dir}\n")
    else:
        console.print(f"[green][*] Моды будут добавлены в:[/green] {target_dir}\n")

    if console.input("Продолжить установку? [Enter / 'n']: ").strip().lower() == "n":
        console.print("[yellow]Отменено.[/yellow]\n")
        return

    discord = DiscordTracker()
    discord.start(pack_name=passphrase, mods=mods)

    console.print()
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        console=console,
    ) as progress:
        done_count = 0
        for idx, mod in enumerate(mods):
            t = progress.add_task(f"[bold]{mod['name'][:28]}[/bold]", total=None)

            def _on_start(total_bytes):
                progress.update(t, total=total_bytes)

            def _on_chunk(chunk_len, downloaded, speed_mb):
                progress.update(t, advance=chunk_len)
                discord.update_live(
                    passphrase, mods, idx, downloaded, progress.tasks[t].total or 0, f"{speed_mb:.1f} MB/s"
                )

            def _on_extract():
                discord.update_live(
                    passphrase, mods, idx, progress.tasks[t].total or 0, progress.tasks[t].total or 0, "Распаковка...", force=True
                )
                progress.update(t, description=f"[cyan]Распаковка: {mod['filename']}[/cyan]")

            try:
                download_and_extract(
                    url=mod["download_url"],
                    filename=mod["filename"],
                    target_dir=target_dir,
                    on_start=_on_start,
                    on_chunk=_on_chunk,
                    on_extract=_on_extract,
                )
                progress.update(t, description=f"[green][+] {mod['name'][:28]}[/green]")
                done_count += 1
            except Exception as e:
                progress.update(t, description=f"[red][!] {mod['name'][:28]} ({e})[/red]")

    discord.finish(passphrase, mods, success=(done_count == len(mods)))
    console.print(f"\n[bold green][+] Установка завершена.[/bold green] Путь: [cyan]{target_dir}[/cyan]\n")


def action_create_pack():
    builder = PackBuilder()
    pack = builder.create_empty_pack()
    passphrase = pack["passphrase"]

    console.rule("[bold cyan]Сборка пака[/bold cyan]")
    console.print(f"\nКод пака: [bold bright_cyan]{passphrase}[/bold bright_cyan]\n")
    console.print("[dim]Вставляйте ссылки по одной. Нажмите Enter на пустой строке для завершения сборки.[/dim]\n")

    count = 1
    while True:
        url = console.input(f"Ссылка #{count} (Enter - завершить): ").strip()
        if not url:
            break

        with console.status("[cyan]Получение метаданных PCVR с mod.io...[/cyan]"):
            ok, result = builder.resolve_mod_from_url(url)
            if not ok:
                console.print(f"[red][!] {result}[/red]")
                continue

            mod_item = result
            pack["mods"].append(mod_item)

            console.print(f"[green][+] Добавлен:[/green] [bold]{mod_item['name']}[/bold]")
            console.print(
                f"    [dim]Файл: {mod_item['filename']} | File ID: {mod_item['file_id']} | Mod ID: {mod_item['id']}[/dim]"
            )
            count += 1

    if not pack["mods"]:
        console.print("[yellow]Пак пуст. Сборка отменена.[/yellow]\n")
        return

    console.print()
    console.print(render_mods_table(pack["mods"], title=f"Итоговый состав: '{passphrase}'"))
    console.print()

    gist_service = GistService()
    with console.status("[cyan]Публикация пака в облачный реестр...[/cyan]"):
        try:
            gist_service.publish_pack(passphrase, pack)
            console.print(f"[bold green][+] Пак успешно опубликован в облаке![/bold green]")
            console.print(f"Код для загрузки другом: [bold bright_cyan]{passphrase}[/bold bright_cyan]\n")
        except Exception as e:
            console.print(f"[red][!] Ошибка выгрузки: {e}[/red]\n")


def run_app():
    while True:
        console.clear()
        print_banner(IS_AUTHOR_MODE)

        if IS_AUTHOR_MODE:
            console.print("[1] Собрать новый пак")
            console.print("[2] Установить пак")
            console.print("[0] Выход\n")
            choice = console.input("Выбор [0-2]: ").strip()
        else:
            console.print("[1] Установить пак модов")
            console.print("[0] Выход\n")
            choice = console.input("Выбор [0-1]: ").strip()
            if choice == "1":
                choice = "2"

        if choice == "1" and IS_AUTHOR_MODE:
            action_create_pack()
            console.input("[dim]Нажмите Enter для возврата в меню...[/dim]")
        elif choice == "2":
            action_install_pack()
            console.input("[dim]Нажмите Enter для возврата в меню...[/dim]")
        elif choice == "0":
            console.print("[dim]Завершение работы.[/dim]")
            break