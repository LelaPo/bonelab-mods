import re
import requests
from typing import Optional, Dict, Any
from src.config import MODIO_API_KEY, MODIO_GAME_ID, MODIO_BASE_URL


class ModioClient:
    def __init__(self, api_key: str = MODIO_API_KEY, game_id: str = MODIO_GAME_ID):
        self.api_key = api_key
        self.game_id = game_id

    @staticmethod
    def extract_slug(url: str) -> Optional[str]:
        """Извлекает слаг мода из ссылки mod.io (например /m/gm-construct -> gm-construct)."""
        match = re.search(r"/m/([a-zA-Z0-9_-]+)", url)
        return match.group(1) if match else None

    def fetch_pcvr_mod(self, slug: str) -> Optional[Dict[str, Any]]:
        """
        Запрашивает информацию о моде по слагу и отбирает файл для платформы Windows.
        """
        headers = {
            "Accept": "application/json",
            "X-Modio-Platform": "windows",
        }
        params = {
            "api_key": self.api_key,
            "name_id": slug,
        }

        url = f"{MODIO_BASE_URL}/games/{self.game_id}/mods"
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()

        data = response.json().get("data", [])
        if not data or not data[0].get("modfile"):
            return None

        mod = data[0]
        modfile = mod["modfile"]

        return {
            "id": mod["id"],
            "name": mod["name"],
            "file_id": modfile["id"],
            "filename": modfile["filename"],
            "download_url": modfile.get("download", {}).get("binary_url"),
        }