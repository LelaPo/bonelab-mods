import json
import requests
from typing import Dict, Any, Optional
from src.config import MASTER_GIST_ID, GITHUB_TOKEN


class GistService:
    def __init__(self, master_gist_id: str = MASTER_GIST_ID, token: Optional[str] = GITHUB_TOKEN):
        self.master_gist_id = master_gist_id
        self.token = token
        self.base_headers = {"User-Agent": "BonelabModSync/2.0"}

    def _get_auth_headers(self) -> Dict[str, str]:
        if not self.token:
            raise ValueError("Для публикации пака требуется GITHUB_TOKEN в .env!")
        return {
            **self.base_headers,
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
        }

    def get_registry(self) -> Dict[str, str]:
        """Получает маппинг: passphrase -> raw_url пака."""
        url = f"https://api.github.com/gists/{self.master_gist_id}"
        resp = requests.get(url, headers=self.base_headers, timeout=10)
        resp.raise_for_status()

        files = resp.json().get("files", {})
        if "registry.json" not in files:
            raise KeyError("Файл registry.json не найден в мастер-гисте!")

        return json.loads(files["registry.json"]["content"])

    def fetch_pack(self, passphrase: str) -> Dict[str, Any]:
        """Ищет пак в реестре и загружает его манифест."""
        registry = self.get_registry()
        pack_url = registry.get(passphrase)
        if not pack_url:
            raise FileNotFoundError(f"Пак '{passphrase}' не найден в реестре.")

        resp = requests.get(pack_url, headers=self.base_headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def publish_pack(self, passphrase: str, pack_data: dict) -> str:
        """Создает отдельный Gist под пак и обновляет registry.json."""
        headers = self._get_auth_headers()

        # 1. Создаем Gist для пака
        payload = {
            "description": f"Bonelab Pack: {passphrase}",
            "public": False,
            "files": {
                f"{passphrase}.json": {
                    "content": json.dumps(pack_data, indent=2, ensure_ascii=False)
                }
            },
        }
        res = requests.post("https://api.github.com/gists", headers=headers, json=payload, timeout=15)
        res.raise_for_status()
        raw_url = res.json()["files"][f"{passphrase}.json"]["raw_url"]

        # 2. Обновляем мастер-реестр
        registry = self.get_registry()
        registry[passphrase] = raw_url

        patch_payload = {
            "files": {
                "registry.json": {
                    "content": json.dumps(registry, indent=2, ensure_ascii=False)
                }
            }
        }
        update_res = requests.patch(
            f"https://api.github.com/gists/{self.master_gist_id}",
            headers=headers,
            json=patch_payload,
            timeout=15,
        )
        update_res.raise_for_status()
        return raw_url