from typing import List, Dict, Any, Tuple
from src.passphrases import generate_passphrase
from src.services.modio import ModioClient


class PackBuilder:
    def __init__(self, modio_client: ModioClient | None = None):
        self.modio = modio_client or ModioClient()

    def create_empty_pack(self, passphrase: str | None = None) -> Dict[str, Any]:
        code = passphrase or generate_passphrase()
        return {
            "passphrase": code,
            "mods": []
        }

    def resolve_mod_from_url(self, url: str) -> Tuple[bool, Dict[str, Any] | str]:
        """
        Парсит URL и находит PCVR файл.
        Возвращает: (True, mod_item) или (False, error_message)
        """
        slug = self.modio.extract_slug(url)
        if not slug:
            return False, "Некорректный формат URL mod.io"

        try:
            mod_data = self.modio.fetch_pcvr_mod(slug)
            if not mod_data:
                return False, f"Файл для PCVR (Windows) не найден в моде '{slug}'"
            return True, mod_data
        except Exception as e:
            return False, f"Ошибка API mod.io: {e}"