import json
from pathlib import Path
from typing import Dict, Any, Optional, Set


SYNC_STATE_FILENAME = ".sync_state.json"


def get_sync_state(target_dir: Path) -> Dict[str, Any]:
    """Считывает состояние ранее установленных через sync модов."""
    state_file = target_dir / SYNC_STATE_FILENAME
    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def update_sync_state(target_dir: Path, mod_id: int, file_id: int, mod_name: str, folder_name: Optional[str] = None):
    """Обновляет состояние после успешной установки мода."""
    state_file = target_dir / SYNC_STATE_FILENAME
    state = get_sync_state(target_dir)

    state[str(mod_id)] = {
        "file_id": file_id,
        "name": mod_name,
        "folder": folder_name or "",
    }

    try:
        state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def get_installed_folder_signatures(target_dir: Path) -> Set[str]:
    """
    Собирает все возможные признаки установленных модов:
    - Имена папок в Mods/ (в нижнем регистре)
    - Поля 'title' и 'barcode' из всех найденных manifest.json
    """
    signatures = set()
    if not target_dir.exists():
        return signatures

    for item in target_dir.iterdir():
        if item.is_dir():
            folder_clean = item.name.lower().replace(".", "").replace("_", "").replace("-", "")
            signatures.add(item.name.lower())
            signatures.add(folder_clean)

            manifest_file = item / "manifest.json"
            if manifest_file.exists():
                try:
                    data = json.loads(manifest_file.read_text(encoding="utf-8"))
                    title = data.get("title", "").strip().lower()
                    barcode = data.get("barcode", "").strip().lower()
                    if title:
                        signatures.add(title)
                    if barcode:
                        signatures.add(barcode)
                except Exception:
                    pass

    return signatures


def is_mod_already_installed(target_dir: Path, mod: Dict[str, Any]) -> bool:
    """
    Проверяет, установлен ли уже мод:
    1. По базе .sync_state.json (mod_id и file_id).
    2. По совпадению имени/сигнатуры с уже распакованными папками/manifest.json.
    """
    mod_id = str(mod.get("id"))
    file_id = mod.get("file_id")

    # 1. Проверка по нашему sync_state
    state = get_sync_state(target_dir)
    if mod_id in state:
        saved_info = state[mod_id]
        if saved_info.get("file_id") == file_id:
            folder = saved_info.get("folder")
            if not folder or (target_dir / folder).exists():
                return True

    # 2. Нечеткий поиск по существующим папкам/манифестам игры
    signatures = get_installed_folder_signatures(target_dir)
    mod_name_lower = mod.get("name", "").strip().lower()
    mod_name_clean = mod_name_lower.replace(" ", "").replace("_", "").replace("-", "")

    # Проверяем прямое совпадение title
    if mod_name_lower in signatures:
        return True

    # Проверяем очищенное имя (например "ammocan" в "doge15567ammocan")
    for sig in signatures:
        if mod_name_clean and mod_name_clean in sig:
            return True

    return False