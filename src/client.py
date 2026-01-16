import os
import sys
import json
import time
import shutil
import zipfile
import argparse
import logging
import platform
import requests
from pathlib import Path
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= HARDCODED BOOTSTRAP SETTINGS =================
# Единственная вещь, которую мы "зашиваем" - это откуда брать конфиг.
# Укажите здесь ваш RAW URL репозитория (должен заканчиваться слэшем).
REPO_BASE_URL = "https://raw.githubusercontent.com/LelaPo/bonelab-mods/main/"
CONFIG_FILENAME = "config.json"
DEFAULT_PROFILE = "manifest.json"
APP_NAME = "BonelabModLoader"
VERSION = "2.0.0"
# ================================================================

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(APP_NAME)

class ModInstaller:
    def __init__(self, args):
        self.args = args
        self.repo_url = self._normalize_url(REPO_BASE_URL)
        self.config = {}
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': f'{APP_NAME}/{VERSION}'})
        
        # Paths
        self.install_path = self._resolve_install_path(args.path)
        self.temp_dir = self.install_path / "_temp_install"
    
    @staticmethod
    def _normalize_url(url):
        return url.strip().rstrip('/') + '/'

    def _resolve_install_path(self, user_path):
        """Определяет путь установки: аргумент -> окружение -> дефолт."""
        if user_path:
            return Path(user_path).resolve()
            
        # Авто-определение для Windows
        if platform.system() == "Windows":
            appdata = os.environ.get('USERPROFILE')
            candidates = [
                Path(appdata) / "AppData/LocalLow/Stress Level Zero/BONELAB/Mods",
                Path(appdata) / "AppData/Roaming/Godot/app_userdata/Bonelab/Mods"
            ]
            for p in candidates:
                if p.parent.exists():
                    log.info(f"📂 Обнаружен путь игры: {p}")
                    return p
        
        # Fallback
        cwd_path = Path.cwd() / "Bonelab_Mods"
        log.warning(f"⚠️ Путь игры не найден. Использую локальную папку: {cwd_path}")
        return cwd_path

    def load_remote_config(self):
        """Загружает конфиг с ключами и вебхуком из GitHub."""
        url = f"{self.repo_url}{CONFIG_FILENAME}"
        log.info(f"📡 Загрузка конфигурации: {url}")
        try:
            r = self.session.get(url, timeout=10)
            r.raise_for_status()
            self.config = r.json()
            # Валидация
            if not self.config.get('mod_io_key'):
                log.warning("⚠️ В конфиге нет API ключа mod.io!")
        except Exception as e:
            log.error(f"❌ Не удалось загрузить конфиг: {e}")
            sys.exit(1)

    def load_manifest(self):
        profile = self.args.profile if self.args.profile.endswith('.json') else f"{self.args.profile}.json"
        url = f"{self.repo_url}{profile}"
        log.info(f"📜 Загрузка профиля: {profile}")
        
        try:
            r = self.session.get(url, params={'t': int(time.time())}, timeout=10)
            if r.status_code == 404:
                log.error(f"❌ Профиль '{profile}' не найден в репозитории.")
                sys.exit(1)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(f"❌ Ошибка загрузки манифеста: {e}")
            sys.exit(1)

    def send_webhook(self, message, color=0x3498db, is_error=False):
        """Отправляет лог в Discord (или прокси), если настроено."""
        if self.args.dry_run or not self.config.get('webhook_url'):
            return

        payload = {
            "username": APP_NAME,
            "embeds": [{
                "description": message,
                "color": color,
                "footer": {"text": f"Ver: {VERSION} | User: {os.environ.get('USERNAME', 'Anon')}"},
                "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            }]
        }
        
        try:
            # Fire and forget
            requests.post(self.config['webhook_url'], json=payload, timeout=2)
        except:
            pass # Игнорируем ошибки логирования, чтобы не ломать основной процесс

    def get_mod_download_url(self, mod_id, file_id):
        """Получает прямую ссылку на скачивание через API Mod.io."""
        api_key = self.config.get('mod_io_key')
        if not api_key:
            raise ValueError("Mod.io API Key is missing in config")

        url = f"https://api.mod.io/v1/games/3809/mods/{mod_id}/files/{file_id}"
        r = self.session.get(url, params={'api_key': api_key}, timeout=10)
        
        if r.status_code == 404:
            raise FileNotFoundError(f"Mod/File {mod_id}:{file_id} удален с Mod.io")
        r.raise_for_status()
        
        data = r.json()
        return data['download']['binary_url']

    def _safe_extract(self, zip_ref, target_path):
        """Защита от Zip Slip: проверяет, что пути не выходят за пределы."""
        target_path = target_path.resolve()
        for member in zip_ref.infolist():
            member_path = (target_path / member.filename).resolve()
            if target_path not in member_path.parents:
                raise RuntimeError(f"Security: Zip Slip attempt detected in {member.filename}")
            zip_ref.extract(member, target_path)

    def install_mod(self, mod):
        name = mod.get('name', 'Unknown')
        mod_id = mod['mod_id']
        file_id = mod['file_id']
        
        marker_path = self.install_path / f"mod_{mod_id}.version"
        
        # 1. Проверка версии (Idempotency)
        if marker_path.exists():
            try:
                with open(marker_path, 'r') as f:
                    local_data = json.load(f)
                if local_data.get('fid') == file_id:
                    if self.args.verbose: log.info(f"✅ {name} (актуален)")
                    return True # Success
            except: pass

        prefix = "🆕" if not marker_path.exists() else "🔄"
        log.info(f"{prefix} Установка: {name}...")

        if self.args.dry_run:
            return True

        # 2. Скачивание и Установка (Atomic)
        try:
            download_url = self.get_mod_download_url(mod_id, file_id)
            
            # Создаем временную папку для конкретного мода
            mod_tmp_dir = self.temp_dir / str(mod_id)
            if mod_tmp_dir.exists(): shutil.rmtree(mod_tmp_dir)
            mod_tmp_dir.mkdir(parents=True)

            # Скачивание (Chunked)
            zip_path = mod_tmp_dir / "download.zip"
            with self.session.get(download_url, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(zip_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        f.write(chunk)
            
            # Распаковка
            with zipfile.ZipFile(zip_path) as z:
                self._safe_extract(z, mod_tmp_dir)
            
            zip_path.unlink() # Удаляем архив

            # 3. Перемещение в целевую папку
            # Структура zip обычно: ModName/files... или просто files...
            # Mod.io для Bonelab обычно пакует корневую папку.
            # Мы перемещаем всё содержимое mod_tmp_dir в install_path
            
            extracted_items = list(mod_tmp_dir.iterdir())
            
            for item in extracted_items:
                dest = self.install_path / item.name
                if dest.exists():
                    if dest.is_dir(): shutil.rmtree(dest)
                    else: dest.unlink()
                shutil.move(str(item), str(dest))
            
            # Очистка и создание маркера
            shutil.rmtree(mod_tmp_dir)
            with open(marker_path, 'w') as f:
                json.dump({'fid': file_id, 'name': name, 'timestamp': time.time()}, f)
            
            log.info(f"✨ Готово: {name}")
            return True

        except Exception as e:
            log.error(f"❌ Ошибка установки {name}: {e}")
            if not self.args.dry_run:
                self.send_webhook(f"Ошибка установки **{name}**: {e}", 0xe74c3c, is_error=True)
            return False

    def run(self):
        log.info(f"🚀 {APP_NAME} v{VERSION}")
        log.info(f"📂 Целевая папка: {self.install_path}")
        
        if not self.install_path.exists():
            if not self.args.dry_run:
                self.install_path.mkdir(parents=True, exist_ok=True)
        
        # Инициализация
        self.load_remote_config()
        manifest = self.load_manifest()
        
        mods = manifest.get('mods', [])
        log.info(f"📦 Найдено модов в профиле: {len(mods)}")
        
        self.send_webhook(f"🚀 Запуск синхронизации: **{self.args.profile}** ({len(mods)} модов)", 0x3498db)

        # Очистка временной папки
        if self.temp_dir.exists(): shutil.rmtree(self.temp_dir)
        
        # Параллельная установка
        success_count = 0
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(self.install_mod, mod): mod for mod in mods}
            
            for future in as_completed(futures):
                if future.result():
                    success_count += 1
        
        # Cleanup
        if self.temp_dir.exists(): shutil.rmtree(self.temp_dir)
        
        log.info(f"🏁 Завершено. Успешно: {success_count}/{len(mods)}")
        self.send_webhook(f"✅ Синхронизация завершена. Установлено/Проверено: {success_count}/{len(mods)}", 0x2ecc71)
        
        if platform.system() == "Windows":
             input("\nНажмите Enter, чтобы выйти...")

def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} Installer")
    parser.add_argument('--profile', default=DEFAULT_PROFILE, help='Имя профиля (например: pvp)')
    parser.add_argument('--path', help='Переопределить путь к папке Mods')
    parser.add_argument('--dry-run', action='store_true', help='Только проверка, без скачивания')
    parser.add_argument('--verbose', action='store_true', help='Подробный вывод')
    
    args = parser.parse_args()
    
    try:
        installer = ModInstaller(args)
        installer.run()
    except KeyboardInterrupt:
        print("\n🛑 Отменено пользователем.")
    except Exception as e:
        log.critical(f"🔥 Критическая ошибка: {e}")
        input("Нажмите Enter для выхода...")

if __name__ == "__main__":
    main()