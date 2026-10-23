import re
import requests
from typing import Optional, Dict, Any, List
from src.config import MODIO_API_KEY, MODIO_GAME_ID, MODIO_BASE_URL


def clean_tokens(text: str) -> set[str]:
    """Превращает 'DoomCollection (Weapons!)' в {'doom', 'collection', 'weapons'}."""
    if not text:
        return set()
    s = re.sub(r"([a-z])([A-Z0-9])", r"\1 \2", text)
    tokens = re.findall(r"[a-z0-9]+", s.lower())
    stop_words = {"patch", "p6", "v1", "v2", "v3", "updated", "pc", "pcvr", "mod", "pack"}
    return {t for t in tokens if len(t) > 1 and t not in stop_words}


def split_camel_case(text: str) -> str:
    """Превращает 'ArknightsEndfieldPack' в 'Arknights Endfield Pack'."""
    if not text:
        return ""
    if "." in text:
        text = text.split(".", 1)[-1]
    spaced = re.sub(r"([a-z])([A-Z0-9])", r"\1 \2", text)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    return spaced.strip()


class ModioClient:
    def __init__(self, api_key: str = MODIO_API_KEY, game_id: str = MODIO_GAME_ID):
        self.api_key = api_key
        self.game_id = game_id

    @staticmethod
    def extract_slug(url: str) -> Optional[str]:
        match = re.search(r"/m/([a-zA-Z0-9_-]+)", url)
        return match.group(1) if match else None

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "X-Modio-Platform": "windows",
        }

    def _parse_mod_item(self, mod: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        modfile = mod.get("modfile")
        if not modfile:
            return None
        return {
            "id": mod["id"],
            "name": mod["name"],
            "file_id": modfile["id"],
            "filename": modfile["filename"],
            "download_url": modfile.get("download", {}).get("binary_url"),
        }

    def fetch_pcvr_mod(self, slug: str) -> Optional[Dict[str, Any]]:
        params = {"api_key": self.api_key, "name_id": slug}
        url = f"{MODIO_BASE_URL}/games/{self.game_id}/mods"
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
        response.raise_for_status()

        data = response.json().get("data", [])
        return self._parse_mod_item(data[0]) if data else None

    def get_mod_by_id(self, mod_id: int) -> Optional[Dict[str, Any]]:
        url = f"{MODIO_BASE_URL}/games/{self.game_id}/mods/{mod_id}"
        response = requests.get(url, headers=self._get_headers(), params={"api_key": self.api_key}, timeout=10)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return self._parse_mod_item(response.json())

    def search_pcvr_mod(self, title: str, author: str = "", raw_folder: str = "") -> Optional[Dict[str, Any]]:
        """
        Честный универсальный поиск mod.io без хардкода:
        1. Проверка прямых слагов
        2. Поиск по нормализованному словосочетанию
        3. Fallback: поиск по уникальному ядру (наиболее длинным словам папки)
        """
        folder_clean_name = raw_folder.split(".", 1)[-1] if "." in raw_folder else raw_folder
        folder_spaced = split_camel_case(folder_clean_name)
        title_spaced = split_camel_case(title) if title != raw_folder else ""

        target_tokens = clean_tokens(folder_spaced) | clean_tokens(title_spaced)
        if not target_tokens:
            return None

        # Формируем список поисковых гипотез
        search_queries = []
        if title_spaced:
            cleaned_t = re.sub(r"\(.*?\)|\[.*?\]", "", title_spaced).strip()
            if cleaned_t:
                search_queries.append(cleaned_t)
        if folder_spaced and folder_spaced not in search_queries:
            search_queries.append(folder_spaced)

        # Выделяем самое длинное уникальное слово (длиной >= 5 букв, не служебное)
        words_by_len = sorted(list(target_tokens), key=len, reverse=True)
        meaningful_words = [w for w in words_by_len if len(w) >= 5 and w not in {"collection", "avatar", "weapons", "enemies"}]
        if meaningful_words:
            search_queries.append(meaningful_words[0])

        url = f"{MODIO_BASE_URL}/games/{self.game_id}/mods"

        # 1. Проверяем прямые слаги
        for q in search_queries:
            slug = q.lower().replace(" ", "-").replace(".", "-").replace("_", "-")
            try:
                resp = requests.get(url, headers=self._get_headers(), params={"api_key": self.api_key, "name_id": slug}, timeout=5)
                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    if data:
                        parsed = self._parse_mod_item(data[0])
                        if parsed:
                            return parsed
            except Exception:
                pass

        # 2. Полнотекстовый поиск mod.io
        for q in search_queries:
            if len(q) < 3:
                continue

            try:
                resp = requests.get(
                    url,
                    headers=self._get_headers(),
                    params={"api_key": self.api_key, "_q": q, "_limit": 10},
                    timeout=5,
                )
                if resp.status_code != 200:
                    continue

                results = resp.json().get("data", [])
                if not results:
                    continue

                best_mod = None
                best_overlap = 0

                for mod in results:
                    parsed = self._parse_mod_item(mod)
                    if not parsed:
                        continue

                    mod_tokens = clean_tokens(mod.get("name", ""))
                    if not mod_tokens:
                        continue

                    # Проверка на взаимоисключающие сущности (Weapons vs Enemies)
                    if "weapons" in target_tokens and "enemies" in mod_tokens and "weapons" not in mod_tokens:
                        continue
                    if "enemies" in target_tokens and "weapons" in mod_tokens and "enemies" not in mod_tokens:
                        continue

                    overlap = len(target_tokens & mod_tokens)

                    # Бонус за автора
                    mod_author = mod.get("submitted_by", {}).get("username", "").lower()
                    if author and author.lower() in mod_author:
                        overlap += 2

                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_mod = parsed

                if best_mod and best_overlap >= 1:
                    return best_mod

            except Exception:
                continue

        return None