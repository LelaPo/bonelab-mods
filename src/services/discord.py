import time
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from src.config import DISCORD_WEBHOOK_URL


class DiscordTracker:
    def __init__(self, webhook_url: Optional[str] = DISCORD_WEBHOOK_URL):
        self.url = webhook_url
        self.message_id: Optional[str] = None
        self.last_update = 0.0
        self.update_interval = 2.0

    @property
    def is_enabled(self) -> bool:
        return bool(self.url and self.url.strip())

    def _make_progress_bar(self, percent: int, length: int = 16) -> str:
        filled = int(length * (percent / 100))
        return "█" * filled + "░" * (length - filled)

    def _build_checklist(self, mods: List[Dict[str, Any]], current_idx: int = -1, current_pct: int = 0) -> str:
        lines = []
        for i, m in enumerate(mods):
            name = m["name"][:34]
            if current_idx == -1:
                lines.append(f"[-] {name}")
            elif i < current_idx:
                lines.append(f"[+] {name}")
            elif i == current_idx:
                lines.append(f"[>] {name} ({current_pct}%)")
            else:
                lines.append(f"[-] {name}")

        result = "```ini\n" + "\n".join(lines[:10])
        if len(mods) > 10:
            result += f"\n...и еще {len(mods) - 10} в очереди"
        result += "\n```"
        return result

    def start(self, pack_name: str, mods: List[Dict[str, Any]]):
        if not self.is_enabled:
            return

        payload = {
            "username": "Bonelab Sync",
            "embeds": [{
                "title": f"Синхронизация пака: {pack_name}",
                "color": 0x34495E,
                "fields": [
                    {"name": "Пак", "value": f"`{pack_name}`", "inline": True},
                    {"name": "Файлов к загрузке", "value": f"`{len(mods)}`", "inline": True},
                    {"name": "Очередь", "value": self._build_checklist(mods), "inline": False},
                ],
                "footer": {"text": "Bonelab Mod Sync • Инициализация"},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }],
        }
        try:
            r = requests.post(f"{self.url}?wait=true", json=payload, timeout=5)
            if r.status_code in (200, 201):
                self.message_id = r.json().get("id")
        except Exception:
            pass

    def update_live(
        self,
        pack_name: str,
        mods: List[Dict[str, Any]],
        current_idx: int,
        downloaded: int,
        total: int,
        speed: str = "",
        force: bool = False,
    ):
        if not self.is_enabled or not self.message_id:
            return

        now = time.time()
        if not force and (now - self.last_update < self.update_interval):
            return
        self.last_update = now

        file_pct = int((downloaded / total * 100)) if total > 0 else 0
        file_mb = downloaded / (1024 * 1024)
        total_mb = total / (1024 * 1024) if total > 0 else 0

        p_bar = self._make_progress_bar(file_pct)
        speed_text = f" • {speed}" if speed else ""

        payload = {
            "embeds": [{
                "title": f"Загрузка: {pack_name}",
                "color": 0x2980B9,
                "fields": [
                    {"name": "Прогресс", "value": f"`[{current_idx + 1}/{len(mods)}]`", "inline": True},
                    {"name": "Текущий файл", "value": f"`{mods[current_idx]['name'][:30]}`", "inline": True},
                    {
                        "name": f"Скачивание ({file_pct}%)",
                        "value": f"`{p_bar}` {file_mb:.1f}/{total_mb:.1f} MB{speed_text}",
                        "inline": False,
                    },
                    {"name": "Статус", "value": self._build_checklist(mods, current_idx, file_pct), "inline": False},
                ],
                "footer": {"text": "Bonelab Mod Sync • В процессе..."},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]
        }
        try:
            requests.patch(f"{self.url}/messages/{self.message_id}", json=payload, timeout=5)
        except Exception:
            pass

    def finish(self, pack_name: str, mods: List[Dict[str, Any]], success: bool = True):
        if not self.is_enabled or not self.message_id:
            return

        checklist = "```ini\n" + "\n".join([f"[+] {m['name'][:34]}" for m in mods[:10]])
        if len(mods) > 10:
            checklist += f"\n...и еще {len(mods) - 10}"
        checklist += "\n```"

        payload = {
            "embeds": [{
                "title": f"Пак {pack_name} установлен",
                "color": 0x27AE60 if success else 0xC0392B,
                "fields": [
                    {"name": "Пак", "value": f"`{pack_name}`", "inline": True},
                    {"name": "Успешно", "value": f"`{len(mods)} из {len(mods)}`", "inline": True},
                    {"name": "Список установленных модов", "value": checklist, "inline": False},
                ],
                "footer": {"text": "Bonelab Mod Sync • Готово к игре"},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]
        }
        try:
            requests.patch(f"{self.url}/messages/{self.message_id}", json=payload, timeout=5)
        except Exception:
            pass