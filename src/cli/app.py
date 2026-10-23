import sys
from pathlib import Path
from rich.progress import Progress, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn

from src.config import IS_AUTHOR_MODE, get_bonelab_mods_path
from src.cli.ui import (
    console,
    print_banner,
    render_mods_table,
    render_collections_table,
    render_shares_table,
)
from src.passphrases import generate_passphrase
from src.core.backup import count_installed_mods, backup_existing_mods
from src.core.detector import is_mod_already_installed, update_sync_state
from src.core.installer import download_and_extract
from src.core.builder import PackBuilder
from src.core.importer import scan_and_resolve_mods
from src.core.collections import CollectionManager
from src.services.gist import GistService
from src.services.discord import DiscordTracker


# ==================== УСТАНОВКА ДЛЯ КЛИЕНТА ====================
# ==================== ИМПОРТ ИЗ УСТАНОВЛЕННЫХ МОДОВ ИГРЫ ====================

def action_import_from_game():
    console.clear()
    console.rule("[bold cyan]Импорт модов из игры в облачную коллекцию[/bold cyan]")

    mods_dir = get_bonelab_mods_path()
    console.print(f"[dim]Сканирование директории:[/dim] [cyan]{mods_dir}[/cyan]\n")

    if not mods_dir.exists():
        console.print("[red][!] Папка Mods не найдена.[/red]\n")
        return

    cm = CollectionManager()

    resolved_mods = []
    unresolved_mods = []

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Поиск модов на mod.io...[/cyan]", total=100)

        def _on_progress(title: str, current: int, total: int):
            progress.update(
                task,
                total=total,
                completed=current,
                description=f"[cyan]Поиск:[/cyan] [bold]{title[:30]}[/bold]"
            )

        resolved_mods, unresolved_mods = scan_and_resolve_mods(
            mods_dir=mods_dir,
            gist_service=GistService(),
            on_progress=_on_progress
        )

    console.print()
    console.print(f"[green][+] Успешно распознано автоматически:[/green] [bold]{len(resolved_mods)}[/bold]")
    
    # Интерактивный резолв ненайденных модов
    if unresolved_mods:
        console.print(f"[yellow][!] Не удалось сопоставить автоматически: {len(unresolved_mods)} модов[/yellow]")
        resolve_manual = console.input("Хотите вручную указать ссылки mod.io для оставшихся? [Y/n]: ").strip().lower() != "n"
        
        if resolve_manual:
            modio_client = PackBuilder().modio
            resolved_manual_count = 0
            for un in list(unresolved_mods):
                console.print(f"\n[cyan]Мод:[/cyan] [bold]{un['title']}[/bold] [dim](папка: {un['folder_name']})[/dim]")
                url = console.input("  Вставьте ссылку mod.io (Enter - пропустить): ").strip()
                if not url:
                    continue

                ok, res = PackBuilder().resolve_mod_from_url(url)
                if ok:
                    resolved_mods.append(res)
                    unresolved_mods.remove(un)
                    resolved_manual_count += 1
                    # Запоминаем в локальный sync_state, чтобы больше никогда не спрашивать
                    update_sync_state(
                        target_dir=mods_dir,
                        mod_id=res["id"],
                        file_id=res["file_id"],
                        mod_name=res["name"],
                        folder_name=un["folder_name"]
                    )
                    console.print(f"  [green][+] Добавлен:[/green] [bold]{res['name']}[/bold]")
                else:
                    console.print(f"  [red][!] {res}[/red]")
            
            if resolved_manual_count > 0:
                console.print(f"\n[green][+] Дополнительно привязано модов:[/green] [bold]{resolved_manual_count}[/bold]")

    console.print()

    if not resolved_mods:
        console.print("[red][!] Ни одного мода не выбрано для сохранения.[/red]\n")
        return

    # Дедупликация и подробный отчет по повторам
    unique_resolved = []
    seen_ids = {}
    duplicates_detected = []

    for m in resolved_mods:
        mid = m["id"]
        if mid not in seen_ids:
            seen_ids[mid] = m["name"]
            unique_resolved.append(m)
        else:
            duplicates_detected.append((m["name"], mid, seen_ids[mid]))

    if duplicates_detected:
        console.print(f"[yellow][!] Предупреждение: обнаружены повторы Mod ID ({len(duplicates_detected)} шт.):[/yellow]")
        for mod_name, mod_id, first_name in duplicates_detected:
            console.print(f"   [dim]• Мод '{mod_name}' (ID: {mod_id}) уже был добавлен как '{first_name}'[/dim]")
        console.print()

    # Спрашиваем куда сохранить
    existing_cols = cm.list_collections()
    console.print("[bold]Куда сохранить найденные моды?[/bold]")
    console.print("  [0] Создать НОВУЮ коллекцию")
    for idx, c in enumerate(existing_cols, 1):
        console.print(f"  [{idx}] В существующую: [bold cyan]{c['name']}[/bold cyan] ({len(c.get('mods', []))} модов)")

    dest_choice = console.input(f"\nВыбор [0-{len(existing_cols)}]: ").strip()
    target_slug = None

    if dest_choice == "0":
        target_name = console.input("Название новой коллекции: ").strip()
        if not target_name:
            console.print("[yellow]Отменено.[/yellow]\n")
            return
        target_desc = console.input("Описание (опционально): ").strip()
        with console.status("[cyan]Создание коллекции в Gist...[/cyan]"):
            try:
                col_data = cm.create_collection(target_name, target_desc)
                target_slug = col_data["slug"]
            except Exception as e:
                console.print(f"[red][!] Ошибка создания коллекции: {e}[/red]\n")
                return
    elif dest_choice.isdigit() and 1 <= int(dest_choice) <= len(existing_cols):
        target_slug = existing_cols[int(dest_choice) - 1]["slug"]
    else:
        console.print("[yellow]Отменено.[/yellow]\n")
        return

    with console.status(f"[cyan]Добавление {len(unique_resolved)} модов в коллекцию '{target_slug}'...[/cyan]"):
        gist_service = GistService()
        cols = gist_service.get_collections()
        target_col = cols.get(target_slug)

        existing_in_col = {m.get("id") for m in target_col.get("mods", [])}
        added_count = 0

        for mod in unique_resolved:
            if mod.get("id") not in existing_in_col:
                target_col["mods"].append(mod)
                existing_in_col.add(mod.get("id"))
                added_count += 1

        cols[target_slug] = target_col
        gist_service.save_collections(cols)

    console.print(f"\n[bold green][+] Успешно сохранено {added_count} новых модов в коллекцию '{target_slug}'![/bold green]")
    console.print(f"[dim]Всего модов в коллекции:[/dim] {len(target_col['mods'])}\n")

def action_install_share():
    console.rule("[bold cyan]Установка по коду раздачи[/bold cyan]")

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
    passphrase = console.input("[bold]Введите 3 слова кода раздачи:[/bold] ").strip()
    if not passphrase:
        return

    gist_service = GistService()
    with console.status("[cyan]Проверка раздачи в облаке...[/cyan]"):
        try:
            share_data = gist_service.fetch_active_share(passphrase)
        except Exception as e:
            console.print(f"[red][!] Ошибка: {e}[/red]\n")
            return

    mods = share_data.get("mods", [])
    if not mods:
        console.print("[yellow][!] Раздача не содержит модов для установки.[/yellow]\n")
        return

    collections_included = ", ".join(share_data.get("collections", []))
    console.print(f"\n[green][+] Найдена раздача:[/green] [bold]{passphrase}[/bold]")
    if collections_included:
        console.print(f"[dim]Коллекции в составе:[/dim] [magenta]{collections_included}[/magenta]")
    console.print(f"[dim]Модов к установке:[/dim] [bold]{len(mods)}[/bold]\n")

    console.print(render_mods_table(mods, title=f"Содержимое раздачи: {passphrase}"))
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
        skipped_count = 0

        for idx, mod in enumerate(mods):
            mod_title = mod["name"][:28]

            # Проверяем, установлен ли уже мод
            if is_mod_already_installed(target_dir, mod):
                t = progress.add_task(f"[dim]↷ {mod_title}[/dim]", total=100, completed=100)
                progress.update(t, description=f"[dim green]✓ {mod_title} (уже установлен)[/dim green]")
                discord.update_live(passphrase, mods, idx, 100, 100, "Уже установлен", force=True)
                skipped_count += 1
                done_count += 1
                continue

            t = progress.add_task(f"[bold]{mod_title}[/bold]", total=None)

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
                folder_name = download_and_extract(
                    url=mod["download_url"],
                    filename=mod["filename"],
                    target_dir=target_dir,
                    on_start=_on_start,
                    on_chunk=_on_chunk,
                    on_extract=_on_extract,
                )
                # Фиксируем установку в .sync_state.json
                update_sync_state(
                    target_dir=target_dir,
                    mod_id=mod.get("id"),
                    file_id=mod.get("file_id"),
                    mod_name=mod.get("name"),
                    folder_name=folder_name,
                )
                progress.update(t, description=f"[green][+] {mod_title}[/green]")
                done_count += 1
            except Exception as e:
                progress.update(t, description=f"[red][!] {mod_title} ({e})[/red]")

    discord.finish(passphrase, mods, success=(done_count == len(mods)))

    summary_text = f"\n[bold green][+] Установка завершена.[/bold green] Установлено: [bold]{done_count - skipped_count}[/bold]"
    if skipped_count > 0:
        summary_text += f", пропущено: [yellow]{skipped_count}[/yellow]"
    summary_text += f". Путь: [cyan]{target_dir}[/cyan]\n"

    console.print(summary_text)


# ==================== УПРАВЛЕНИЕ КОЛЛЕКЦИЯМИ (АВТОР) ====================

def menu_collections():
    cm = CollectionManager()
    builder = PackBuilder()

    while True:
        console.clear()
        console.rule("[bold cyan]Управление коллекциями в облаке[/bold cyan]")
        cols = cm.list_collections()

        if not cols:
            console.print("[dim]У вас пока нет ни одной коллекции.[/dim]\n")
        else:
            console.print(render_collections_table(cols))
            console.print()

        console.print("[1] Открыть / редактировать коллекцию")
        console.print("[2] Создать новую коллекцию")
        console.print("[3] Удалить коллекцию")
        console.print("[0] Назад в главное меню\n")

        choice = console.input("Выбор [0-3]: ").strip()
        if choice == "0":
            break

        if choice == "2":
            name = console.input("Название коллекции: ").strip()
            if not name:
                continue
            desc = console.input("Описание (опционально): ").strip()
            with console.status("[cyan]Создание коллекции в Gist...[/cyan]"):
                try:
                    cm.create_collection(name, desc)
                    console.print(f"[green][+] Коллекция '{name}' создана![/green]")
                except Exception as e:
                    console.print(f"[red][!] Ошибка: {e}[/red]")
            console.input("[dim]Enter для продолжения...[/dim]")

        elif choice == "1" and cols:
            num = console.input("Номер коллекции для открытия: ").strip()
            if not num.isdigit() or not (1 <= int(num) <= len(cols)):
                continue
            selected_col = cols[int(num) - 1]
            _edit_collection(cm, builder, selected_col["slug"])

        elif choice == "3" and cols:
            num = console.input("Номер коллекции для УДАЛЕНИЯ: ").strip()
            if not num.isdigit() or not (1 <= int(num) <= len(cols)):
                continue
            selected_col = cols[int(num) - 1]
            confirm = console.input(f"Удалить '{selected_col['name']}'? [y/N]: ").strip().lower()
            if confirm == "y":
                with console.status("[cyan]Удаление из Gist...[/cyan]"):
                    cm.delete_collection(selected_col["slug"])
                console.print("[green][+] Удалено.[/green]")
                console.input("[dim]Enter для продолжения...[/dim]")


def _edit_collection(cm: CollectionManager, builder: PackBuilder, slug: str):
    while True:
        console.clear()
        col = cm.get_collection(slug)
        if not col:
            break

        console.rule(f"[bold cyan]Коллекция: {col['name']}[/bold cyan]")
        if col.get("description"):
            console.print(f"[dim italic]{col['description']}[/dim italic]\n")

        mods = col.get("mods", [])
        if not mods:
            console.print("[dim]В этой коллекции еще нет модов.[/dim]\n")
        else:
            console.print(render_mods_table(mods))
            console.print()

        console.print("[1] Добавить мод по ссылке mod.io")
        console.print("[2] Удалить мод из коллекции")
        console.print("[0] Назад к списку коллекций\n")

        sub = console.input("Выбор [0-2]: ").strip()
        if sub == "0":
            break

        if sub == "1":
            url = console.input("Ссылка на страницу мода (mod.io): ").strip()
            if not url:
                continue
            with console.status("[cyan]Получение PCVR-версии...[/cyan]"):
                ok, res = builder.resolve_mod_from_url(url)
                if not ok:
                    console.print(f"[red][!] {res}[/red]")
                else:
                    success, msg = cm.add_mod(slug, res)
                    if success:
                        console.print(f"[green][+] Мод '{res['name']}' добавлен![/green]")
                    else:
                        console.print(f"[yellow][!] {msg}[/yellow]")
            console.input("[dim]Enter для продолжения...[/dim]")

        elif sub == "2" and mods:
            m_num = console.input("Номер мода для удаления: ").strip()
            if m_num.isdigit() and (1 <= int(m_num) <= len(mods)):
                mod_to_del = mods[int(m_num) - 1]
                with console.status("[cyan]Удаление мода из коллекции...[/cyan]"):
                    cm.remove_mod(slug, mod_to_del["id"])
                console.print(f"[green][+] Мод '{mod_to_del['name']}' удален.[/green]")
                console.input("[dim]Enter для продолжения...[/dim]")


# ==================== ГЕНЕРАЦИЯ РАЗДАЧИ (SHARE CODE) ====================

def action_generate_share():
    console.clear()
    console.rule("[bold cyan]Сгенерировать код раздачи[/bold cyan]")

    cm = CollectionManager()
    cols = cm.list_collections()
    if not cols:
        console.print("[yellow][!] Сначала создайте хотя бы одну коллекцию в меню [1].[/yellow]\n")
        return

    console.print(render_collections_table(cols))
    console.print("\n[dim]Введите номера коллекций через запятую или пробел (например: 1, 2) или 'all':[/dim]")
    selection = console.input("Коллекции для объединения: ").strip()
    if not selection:
        return

    selected_cols = []
    if selection.lower() == "all":
        selected_cols = cols
    else:
        parts = [p.strip() for p in selection.replace(",", " ").split() if p.strip().isdigit()]
        for p in parts:
            idx = int(p) - 1
            if 0 <= idx < len(cols):
                selected_cols.append(cols[idx])

    if not selected_cols:
        console.print("[red][!] Ни одной коллекции не выбрано.[/red]\n")
        return

    merged_mods = cm.merge_mods(selected_cols)
    if not merged_mods:
        console.print("[yellow][!] В выбранных коллекциях нет модов.[/yellow]\n")
        return

    ttl_input = console.input("Срок действия кода в часах [по умолчанию 24]: ").strip()
    ttl_hours = int(ttl_input) if ttl_input.isdigit() and int(ttl_input) > 0 else 24

    passphrase = generate_passphrase()
    col_names = [c["name"] for c in selected_cols]

    console.print(f"\n[green]Формируется раздача:[/green] [bold bright_cyan]{passphrase}[/bold bright_cyan]")
    console.print(f"[dim]Включено коллекций:[/dim] {len(col_names)} ({', '.join(col_names)})")
    console.print(f"[dim]Уникальных файлов модов:[/dim] {len(merged_mods)}")
    console.print(f"[dim]Время жизни кода:[/dim] {ttl_hours} ч.\n")

    gist_service = GistService()
    with console.status("[cyan]Публикация временной раздачи в Gist...[/cyan]"):
        try:
            gist_service.create_share(passphrase, merged_mods, col_names, ttl_hours=ttl_hours)
            console.print(f"[bold green][+] Раздача готова![/bold green]")
            console.print(f"Код для друга: [bold bright_cyan]{passphrase}[/bold bright_cyan]\n")
        except Exception as e:
            console.print(f"[red][!] Ошибка публикации: {e}[/red]\n")


# ==================== МОНИТОРИНГ И ОТЗЫВ ====================

def action_manage_shares():
    console.clear()
    console.rule("[bold cyan]Активные раздачи[/bold cyan]")

    gist_service = GistService()
    with console.status("[cyan]Загрузка раздач из Gist...[/cyan]"):
        try:
            gist_service.cleanup_expired()
            shares = gist_service.get_shares()
        except Exception as e:
            console.print(f"[red][!] Ошибка: {e}[/red]\n")
            return

    if not shares:
        console.print("[dim]Нет активных раздач.[/dim]\n")
        return

    console.print(render_shares_table(shares))
    console.print()

    revoke_code = console.input("Введите код для ДОСРОЧНОГО отзыва (или Enter для выхода): ").strip()
    if not revoke_code:
        return

    with console.status("[cyan]Отзыв кода раздачи...[/cyan]"):
        if gist_service.revoke_share(revoke_code):
            console.print(f"[green][+] Раздача '{revoke_code}' отозвана и удалена из облака.[/green]\n")
        else:
            console.print(f"[yellow][!] Раздача с кодом '{revoke_code}' не найдена.[/yellow]\n")


# ==================== ГЛАВНЫЙ ЦИКЛ ====================

def run_app():
    while True:
        console.clear()
        print_banner(IS_AUTHOR_MODE)

        if IS_AUTHOR_MODE:
            console.print("[1] Мои коллекции (Создать / Редактировать)")
            console.print("[2] Импортировать установленные моды из игры в коллекцию [NEW]")
            console.print("[3] Сгенерировать код раздачи (Share Code)")
            console.print("[4] Активные раздачи (Мониторинг / Отозвать)")
            console.print("[5] Установить по коду раздачи")
            console.print("[0] Выход\n")
            choice = console.input("Выбор [0-5]: ").strip()
        else:
            console.print("[1] Установить моды по коду")
            console.print("[0] Выход\n")
            choice = console.input("Выбор [0-1]: ").strip()
            if choice == "1":
                choice = "5"

        if choice == "1" and IS_AUTHOR_MODE:
            menu_collections()
        elif choice == "2" and IS_AUTHOR_MODE:
            action_import_from_game()
            console.input("[dim]Enter для возврата в меню...[/dim]")
        elif choice == "3" and IS_AUTHOR_MODE:
            action_generate_share()
            console.input("[dim]Enter для возврата в меню...[/dim]")
        elif choice == "4" and IS_AUTHOR_MODE:
            action_manage_shares()
            console.input("[dim]Enter для возврата в меню...[/dim]")
        elif choice == "5":
            action_install_share()
            console.input("[dim]Enter для возврата в меню...[/dim]")
        elif choice == "0":
            console.print("[dim]Завершение работы.[/dim]")
            break