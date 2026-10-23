import re
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from src.services.gist import GistService


def slugify(text: str) -> str:
    text = text.lower().strip()
    return re.sub(r"[^\w\s-]", "", text).replace(" ", "-")


class CollectionManager:
    def __init__(self, gist_service: Optional[GistService] = None):
        self.gist = gist_service or GistService()

    def list_collections(self) -> List[Dict[str, Any]]:
        cols = self.gist.get_collections()
        return list(cols.values())

    def get_collection(self, slug: str) -> Optional[Dict[str, Any]]:
        cols = self.gist.get_collections()
        return cols.get(slug)

    def create_collection(self, name: str, description: str = "") -> Dict[str, Any]:
        slug = slugify(name)
        if not slug:
            raise ValueError("Имя коллекции не может быть пустым.")

        cols = self.gist.get_collections()
        if slug in cols:
            raise FileExistsError(f"Коллекция с идентификатором '{slug}' уже существует.")

        col_data = {
            "slug": slug,
            "name": name,
            "description": description,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "mods": []
        }
        cols[slug] = col_data
        self.gist.save_collections(cols)
        return col_data

    def delete_collection(self, slug: str) -> bool:
        cols = self.gist.get_collections()
        if slug in cols:
            del cols[slug]
            self.gist.save_collections(cols)
            return True
        return False

    def add_mod(self, slug: str, mod_item: Dict[str, Any]) -> Tuple[bool, str]:
        cols = self.gist.get_collections()
        col = cols.get(slug)
        if not col:
            return False, f"Коллекция '{slug}' не найдена."

        # Проверка на дубликат по id мода
        for existing in col["mods"]:
            if existing.get("id") == mod_item.get("id"):
                return False, f"Мод '{mod_item['name']}' уже присутствует в коллекции."

        col["mods"].append(mod_item)
        col["updated_at"] = datetime.now(timezone.utc).isoformat()
        cols[slug] = col
        self.gist.save_collections(cols)
        return True, "Мод успешно добавлен."

    def remove_mod(self, slug: str, mod_id: int) -> bool:
        cols = self.gist.get_collections()
        col = cols.get(slug)
        if not col:
            return False

        init_len = len(col["mods"])
        col["mods"] = [m for m in col["mods"] if m.get("id") != mod_id]
        if len(col["mods"]) < init_len:
            col["updated_at"] = datetime.now(timezone.utc).isoformat()
            cols[slug] = col
            self.gist.save_collections(cols)
            return True
        return False

    @staticmethod
    def merge_mods(collections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Объединяет моды из нескольких коллекций без дубликатов."""
        seen_ids = set()
        merged = []
        for col in collections:
            for mod in col.get("mods", []):
                mid = mod.get("id")
                if mid not in seen_ids:
                    seen_ids.add(mid)
                    merged.append(mod)
        return merged