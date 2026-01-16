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
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= НАСТРОЙКИ =================
# Ссылка на RAW корень репозитория (обязательно с / в конце)
REPO_BASE_URL = "https://raw.githubusercontent.com/LelaPo/bonelab-mods/main/"
CONFIG_FILENAME = "config.public.json"
PROFILES_INDEX = "profiles/index.json"
APP_NAME = "BonelabModLoader"
VERSION = "3.2.0"
# =============================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(APP_NAME)

class ModInstaller:
    def __init__(self, args):
        self.args = args
        self.repo_url = REPO_BASE_URL.strip().rstrip('/') + '/'
        self.config = {}
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': f'{APP_NAME}/{VERSION}'})
        self.install_path = self._resolve_install_path(args.path)
        self.temp_dir = self.install_path / "_temp_install"

    def _resolve_install_path(self, user_path):
        if user_path: return Path(user_path).resolve()
        if platform.system() == "Windows":
            appdata = os.environ.get('USERPROFILE')
            candidates = [
                Path(appdata) / "AppData/LocalLow/Stress Level Zero/BONELAB/Mods",
                Path(appdata) / "AppData/Roaming/Godot/app_userdata/Bonelab/Mods"
            ]
            for p in candidates:
                if p.parent.exists(): return p
        return Path.cwd() / "Bonelab_Mods"

    def load_config(self):
        url = f"{self.repo_url}{CONFIG_FILENAME}"
        try:
            r = self.session.get(url, params={'t': int(time.time())}, timeout=5)
            r.raise_for_status()
            self.config = r.json()
        except Exception as e:
            log.warning(f"⚠️ Не удалось загрузить конфиг ({e}). Используем дефолты.")

    def get_profile_url(self):
        """Логика выбора профиля через index.json"""
        index_url = f"{self.repo_url}{PROFILES_INDEX}"
        profiles_index = {}
        
        # 1. Пробуем скачать индекс
        try:
            r = self.session.get(index_url, params={'t': int(time.time())}, timeout=5)
            if r.status_code == 200:
                profiles_index = r.json()
        except Exception as e:
            log.warning(f"⚠️ Не удалось скачать список профилей: {e}")

        # 2. Если пользователь попросил список
        if self.args.list_profiles:
            print(f"\n📋 Доступные профили:")
            if not profiles_index:
                print("   (Список пуст или недоступен)")
            else:
                print(f"{'ID':<15} | {'Название':<20} | {'Описание'}")
                print("-" * 65)
                for pid, data in profiles_index.items():
                    print(f"{pid:<15} | {data.get('title', ''):<20} | {data.get('description', '')}")
                print("-" * 65)
            sys.exit(0)

        target = self.args.profile

        # 3. Ищем в индексе
        if target in profiles_index:
            rel_path = profiles_index[target]['path']
            log.info(f"🎯 Профиль найден в индексе: {target} -> {rel_path}")
            return f"{self.repo_url}{rel_path}"

        # 4. Fallback: если default, берем из конфига
        if target == "default":
            cfg_default = self.config.get("default_profile", "profiles/default.json")
            log.info(f"ℹ️ Используем дефолтный путь: {cfg_default}")
            return f"{self.repo_url}{cfg_default}"

        # 5. Fallback: пробуем как прямой файл
        if not target.endswith(".json"): target += ".json"
        log.warning(f"⚠️ Профиль '{self.args.profile}' не в индексе. Пробую прямой путь: profiles/{target}")
        return f"{self.repo_url}profiles/{target}"

    def load_manifest(self):
        url = self.get_profile_url()
        log.info(f"📡 Скачивание манифеста: {url}")
        try:
            r = self.session.get(url, params={'t': int(time.time())}, timeout=10)
            if r.status_code == 404:
                log.error("❌ Профиль не найден (404). Проверьте имя.")
                sys.exit(1)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(f"❌ Ошибка загрузки манифеста: {e}")
            sys.exit(1)

    def send_log(self, message, color=0x3498db):
        if self.args.dry_run or not self.config.get('worker_url'): return
        payload = {
            "username": APP_NAME,
            "embeds": [{
                "description": message,
                "color": color,
                "footer": {"text": f"User: {os.environ.get('USERNAME', 'Anon')} | Ver: {VERSION}"}
            }]
        }
        try:
            requests.post(self.config['worker_url'], json=payload, timeout=2)
        except: pass

    def _safe_extract(self, zip_ref, target_path):
        target_path = target_path.resolve()
        for member in zip_ref.infolist():
            member_path = (target_path / member.filename).resolve()
            if target_path not in member_path.parents:
                raise RuntimeError(f"Zip Slip detected: {member.filename}")
            zip_ref.extract(member, target_path)

    def install_mod(self, mod):
        name = mod.get('name', 'Unknown')
        mod_id = mod['mod_id']
        file_id = mod['file_id']
        marker_path = self.install_path / f"mod_{mod_id}.version"
        
        if marker_path.exists():
            try:
                with open(marker_path, 'r') as f:
                    if json.load(f).get('fid') == file_id: return True
            except: pass

        log.info(f"📥 Установка: {name} (ID: {mod_id})")
        if self.args.dry_run: return True

        try:
            api_key = self.config.get('mod_io_key')
            if not api_key: raise ValueError("Нет API ключа Mod.io")
            
            # Get download URL
            meta_url = f"https://api.mod.io/v1/games/3809/mods/{mod_id}/files/{file_id}"
            r = self.session.get(meta_url, params={'api_key': api_key}, timeout=10)
            r.raise_for_status()
            download_url = r.json()['download']['binary_url']

            # Download & Extract
            tmp_mod = self.temp_dir / str(mod_id)
            if tmp_mod.exists(): shutil.rmtree(tmp_mod)
            tmp_mod.mkdir(parents=True)
            
            zip_file = tmp_mod / "mod.zip"
            with self.session.get(download_url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(zip_file, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=65536): f.write(chunk)
            
            with zipfile.ZipFile(zip_file) as z:
                self._safe_extract(z, tmp_mod)
            zip_file.unlink()

            # Move files
            for item in tmp_mod.iterdir():
                dest = self.install_path / item.name
                if dest.exists():
                    if dest.is_dir(): shutil.rmtree(dest)
                    else: dest.unlink()
                shutil.move(str(item), str(dest))
            
            shutil.rmtree(tmp_mod)
            with open(marker_path, 'w') as f:
                json.dump({'fid': file_id, 'name': name}, f)
            return True

        except Exception as e:
            log.error(f"❌ Сбой {name}: {e}")
            if not self.args.dry_run:
                self.send_log(f"🔥 Ошибка установки **{name}**: {e}", 0xe74c3c)
            return False

    def run(self):
        log.info(f"🚀 {APP_NAME} v{VERSION}")
        self.load_config()
        
        if self.args.list_profiles:
            self.get_profile_url() # This will print list and exit
            
        manifest = self.load_manifest()
        mods = manifest.get('mods', [])
        
        if not self.install_path.exists() and not self.args.dry_run:
            self.install_path.mkdir(parents=True)

        self.send_log(f"🚀 Старт: **{self.args.profile}** ({len(mods)} модов)", 0x3498db)
        
        if self.temp_dir.exists(): shutil.rmtree(self.temp_dir)
        
        success = 0
        with ThreadPoolExecutor(max_workers=3) as ex:
            futures = {ex.submit(self.install_mod, m): m for m in mods}
            for f in as_completed(futures):
                if f.result(): success += 1
        
        if self.temp_dir.exists(): shutil.rmtree(self.temp_dir)
        
        log.info(f"✅ Успешно: {success}/{len(mods)}")
        self.send_log(f"🏁 Финиш: {success}/{len(mods)}", 0x2ecc71)
        if platform.system() == "Windows": input("\nНажмите Enter...")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', default='default', help='Название профиля (pvp, default)')
    parser.add_argument('--list-profiles', action='store_true', help='Показать список профилей')
    parser.add_argument('--path', help='Путь к папке Mods')
    parser.add_argument('--dry-run', action='store_true')
    try:
        ModInstaller(parser.parse_args()).run()
    except KeyboardInterrupt: pass
    except Exception as e:
        log.critical(f"FATAL: {e}")
        input("Error. Press Enter...")