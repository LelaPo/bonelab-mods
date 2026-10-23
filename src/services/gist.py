import json
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from src.config import MASTER_GIST_ID, GITHUB_TOKEN


class GistService:
    def __init__(self, master_gist_id: str = MASTER_GIST_ID, token: Optional[str] = GITHUB_TOKEN):
        self.master_gist_id = master_gist_id
        self.token = token
        self.base_headers = {"User-Agent": "BonelabModSync/2.0"}

    def _get_auth_headers(self) -> Dict[str, str]:
        if not self.token:
            raise ValueError("Для управления коллекциями и раздачами требуется GITHUB_TOKEN в .env!")
        return {
            **self.base_headers,
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
        }

    def _fetch_master_gist(self) -> Dict[str, Any]:
        """Получает сырые данные мастер-гиста."""
        if not self.master_gist_id:
            raise ValueError("MASTER_GIST_ID не задан в конфигурации (.env)!")

        headers = self._get_auth_headers() if self.token else self.base_headers
        url = f"https://api.github.com/gists/{self.master_gist_id}"
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json().get("files", {})

    def _patch_master_gist(self, files_payload: Dict[str, Dict[str, str]]):
        """Отправляет изменения в мастер-гист."""
        headers = self._get_auth_headers()
        url = f"https://api.github.com/gists/{self.master_gist_id}"
        resp = requests.patch(url, headers=headers, json={"files": files_payload}, timeout=15)
        resp.raise_for_status()

    # ==================== КОЛЛЕКЦИИ ====================

    def get_collections(self) -> Dict[str, Any]:
        """Возвращает словарь всех коллекций автора: {slug: {...}}."""
        files = self._fetch_master_gist()
        if "collections.json" not in files:
            return {}
        try:
            return json.loads(files["collections.json"]["content"])
        except Exception:
            return {}

    def save_collections(self, collections: Dict[str, Any]):
        """Сохраняет обновленный словарь коллекций в Gist."""
        payload = {
            "collections.json": {
                "content": json.dumps(collections, indent=2, ensure_ascii=False)
            }
        }
        self._patch_master_gist(payload)

    # ==================== СЕССИИ РАЗДАЧ (SHARES) ====================

    def get_shares(self) -> Dict[str, Any]:
        """Возвращает словарь активных раздач: {passphrase: {...}}."""
        files = self._fetch_master_gist()
        if "shares.json" not in files:
            # Обратная совместимость с registry.json, если был
            if "registry.json" in files:
                return json.loads(files["registry.json"]["content"])
            return {}
        try:
            return json.loads(files["shares.json"]["content"])
        except Exception:
            return {}

    def create_share(
        self,
        passphrase: str,
        mods: List[Dict[str, Any]],
        collection_names: List[str],
        ttl_hours: int = 24
    ) -> Dict[str, Any]:
        """Создает временную раздачу на заданное количество часов."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=ttl_hours)

        shares = self.get_shares()
        share_data = {
            "passphrase": passphrase,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "collections": collection_names,
            "mods": mods
        }
        shares[passphrase] = share_data

        # Заодно подчищаем старые
        cleaned_shares = self._filter_active_shares(shares)

        payload = {
            "shares.json": {
                "content": json.dumps(cleaned_shares, indent=2, ensure_ascii=False)
            }
        }
        self._patch_master_gist(payload)
        return share_data

    def revoke_share(self, passphrase: str) -> bool:
        """Досрочно удаляет раздачу."""
        shares = self.get_shares()
        if passphrase in shares:
            del shares[passphrase]
            payload = {
                "shares.json": {
                    "content": json.dumps(shares, indent=2, ensure_ascii=False)
                }
            }
            self._patch_master_gist(payload)
            return True
        return False

    def fetch_active_share(self, passphrase: str) -> Dict[str, Any]:
        """
        Клиентский метод: находит раздачу по 3 словам и проверяет срок ее действия.
        """
        shares = self.get_shares()
        share = shares.get(passphrase)
        if not share:
            raise FileNotFoundError(f"Раздача с кодом '{passphrase}' не найдена.")

        # Проверка срока жизни
        expires_at_str = share.get("expires_at")
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str)
            if datetime.now(timezone.utc) > expires_at:
                raise TimeoutError(f"Срок действия кода '{passphrase}' истек.")

        return share

    def cleanup_expired(self) -> int:
        """Удаляет просроченные раздачи."""
        shares = self.get_shares()
        active = self._filter_active_shares(shares)
        removed = len(shares) - len(active)
        if removed > 0:
            payload = {
                "shares.json": {
                    "content": json.dumps(active, indent=2, ensure_ascii=False)
                }
            }
            self._patch_master_gist(payload)
        return removed

    @staticmethod
    def _filter_active_shares(shares: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        active = {}
        for code, data in shares.items():
            exp_str = data.get("expires_at")
            if not exp_str:
                active[code] = data
                continue
            try:
                if datetime.fromisoformat(exp_str) > now:
                    active[code] = data
            except Exception:
                pass
        return active