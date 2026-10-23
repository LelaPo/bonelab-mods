import os
import zipfile
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable


def count_installed_mods(mods_path: Path) -> int:
    """Считает количество установленных папок модов."""
    if not mods_path.exists():
        return 0
    return sum(1 for item in mods_path.iterdir() if item.is_dir())


def backup_existing_mods(mods_path: Path, on_progress: Optional[Callable[[str], None]] = None) -> Optional[Path]:
    """
    Архивирует текущие моды в папку Backups рядом с Mods.
    Возвращает путь к созданному zip-файлу или None, если папка пуста.
    """
    if not mods_path.exists() or count_installed_mods(mods_path) == 0:
        return None

    backup_folder = mods_path.parent / "Backups"
    backup_folder.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = backup_folder / f"Mods_Backup_{timestamp}.zip"

    if on_progress:
        on_progress(f"Создание резервной копии: {zip_path.name}...")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_ref:
        for root, _, files in os.walk(mods_path):
            for file in files:
                full_file = Path(root) / file
                arcname = full_file.relative_to(mods_path)
                zip_ref.write(full_file, arcname)

    return zip_path