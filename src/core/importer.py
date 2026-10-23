import json
import re
from pathlib import Path
from typing import List, Dict, Any, Tuple, Callable, Optional
from src.services.modio import ModioClient
from src.services.gist import GistService
from src.core.detector import get_sync_state


def get_known_mods_from_gist(gist_service: GistService) -> Dict[str, Dict[str, Any]]:
    known = {}
    try:
        collections = gist_service.get_collections()
        for col in collections.values():
            for mod in col.get("mods", []):
                filename = mod.get("filename", "").lower()
                clean_fn = re.sub(r"[^a-zA-Z0-9]", "", filename)
                if clean_fn:
                    known[clean_fn] = mod

                mod_name = mod.get("name", "").lower()
                clean_mn = re.sub(r"[^a-zA-Z0-9]", "", mod_name)
                if clean_mn:
                    known[clean_mn] = mod
    except Exception:
        pass
    return known


def get_local_mods_manifests(mods_dir: Path) -> List[Dict[str, Any]]:
    local_mods = []
    if not mods_dir.exists():
        return local_mods

    sync_state = get_sync_state(mods_dir)

    for item in sorted(mods_dir.iterdir()):
        if not item.is_dir():
            continue

        title = item.name
        author = ""
        known_mod_id = None

        manifest_path = item / "manifest.json"
        sibling_manifest = mods_dir / f"{item.name}.manifest"
        chosen = manifest_path if manifest_path.exists() else (sibling_manifest if sibling_manifest.exists() else None)

        if chosen:
            try:
                data = json.loads(chosen.read_text(encoding="utf-8"))
                title = data.get("title", item.name).strip() or item.name
                author = data.get("author", "").strip()
            except Exception:
                pass

        for mid, info in sync_state.items():
            if info.get("folder") == item.name or info.get("name", "").lower() == title.lower():
                try:
                    known_mod_id = int(mid)
                except ValueError:
                    pass
                break

        local_mods.append({
            "folder_name": item.name,
            "title": title,
            "author": author,
            "known_mod_id": known_mod_id,
        })

    return local_mods


def scan_and_resolve_mods(
    mods_dir: Path,
    modio_client: Optional[ModioClient] = None,
    gist_service: Optional[GistService] = None,
    on_progress: Optional[Callable[[str, int, int], None]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    client = modio_client or ModioClient()
    gist = gist_service or GistService()

    local_items = get_local_mods_manifests(mods_dir)
    known_gist_mods = get_known_mods_from_gist(gist)
    total = len(local_items)

    resolved = []
    unresolved = []

    for idx, item in enumerate(local_items, 1):
        folder = item["folder_name"]
        title = item["title"]

        if on_progress:
            on_progress(folder, idx, total)

        mod_data = None
        folder_clean = re.sub(r"[^a-zA-Z0-9]", "", folder.lower())

        # 1. Проверяем кэш облачных коллекций Gist
        for key, known_mod in known_gist_mods.items():
            if len(key) >= 4 and (key in folder_clean or folder_clean in key):
                mod_data = known_mod
                break

        # 2. Проверяем локальный sync_state
        if not mod_data and item["known_mod_id"]:
            try:
                mod_data = client.get_mod_by_id(item["known_mod_id"])
            except Exception:
                pass

        # 3. Честный многоступенчатый поиск mod.io
        if not mod_data:
            mod_data = client.search_pcvr_mod(
                title=title,
                author=item["author"],
                raw_folder=folder
            )

        if mod_data:
            resolved.append(mod_data)
        else:
            unresolved.append(item)

    return resolved, unresolved