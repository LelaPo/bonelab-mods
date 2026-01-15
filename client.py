import os
import shutil
import json
import requests
import zipfile
import time
import sys
import platform
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# ================= НАСТРОЙКИ КЛИЕНТА =================
# Укажи ссылку на папку репозитория.
# СКРИПТ САМ ИСПРАВИТ ОШИБКИ В ССЫЛКЕ, не бойся.
REPO_BASE_URL = "https://raw.githubusercontent.com/LelaPo/bonelab-mods/main/"

MOD_IO_API_KEY = "cc192d4610be216a225b6f8e0ab62780"
WEBHOOK_URL = "https://discord.com/api/webhooks/1439528412493385758/kF2yBi6Og9ae8-A9E6Yrg1FClkQWD-cnvCp_6xnXYsTuN_osZegTGL9OL_HRRO9wMc32"
GAME_ID = 3809 
# =====================================================

USER_NAME = os.environ.get('USERNAME', 'User')

def normalize_base_url(url):
    """Исправляет кривые ссылки от пользователя"""
    url = url.strip()
    # Если юзер вставил ссылку на конкретный файл, убираем имя файла
    if url.lower().endswith(".json"):
        url = url.rsplit('/', 1)[0]
    # Убеждаемся, что есть слэш в конце
    if not url.endswith("/"):
        url += "/"
    return url

REPO_BASE_URL = normalize_base_url(REPO_BASE_URL)

def send_log(message, color=0x00ff00):
    if not WEBHOOK_URL: return
    try:
        payload = {
            "username": "BonLab Updater",
            "embeds": [{
                "description": message,
                "color": color,
                "footer": {"text": f"User: {USER_NAME}"},
                "timestamp": datetime.utcnow().isoformat()
            }]
        }
        requests.post(WEBHOOK_URL, json=payload, timeout=2)
    except: pass

from datetime import datetime

def find_default_path():
    user = os.environ.get('USERPROFILE')
    paths = [
        Path(user) / "AppData/LocalLow/Stress Level Zero/BONELAB/Mods",
        Path(user) / "AppData/Roaming/Godot/app_userdata/Bonelab/Mods",
    ]
    for p in paths:
        if p.parent.exists(): return p
    return Path(os.getcwd()) / "Bonelab_Mods"

def get_manifest(profile_name):
    if not profile_name.endswith(".json"): profile_name += ".json"
    url = f"{REPO_BASE_URL}{profile_name}"
    
    print(f"📡 Подключение к профилю: {profile_name}")
    
    try:
        r = requests.get(f"{url}?t={int(time.time())}", timeout=10)
        if r.status_code == 404:
            print("❌ ОШИБКА 404: Профиль не найден!")
            print(f"Ссылка: {url}")
            return None
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"❌ Ошибка сети: {e}")
        return None

def clear_mods_folder(path):
    print(f"\n⚠️ ВНИМАНИЕ! Это удалит ВСЕ файлы в папке:\n{path}")
    check = input("Введите 'DELETE' для подтверждения: ")
    if check != 'DELETE':
        print("Отмена.")
        return

    print("🗑️ Удаление файлов...")
    send_log(f"🧹 **{USER_NAME}** полностью очистил папку модов.", 0xff0000)
    
    try:
        # Удаляем все содержимое, но оставляем саму папку Mods
        for item in path.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        print("✅ Папка очищена. Теперь чистая установка.")
    except Exception as e:
        print(f"❌ Ошибка при удалении: {e}")

def process_mod(mod, install_dir, dry_run=False):
    name = mod['name']
    mod_id = mod['mod_id']
    file_id = mod['file_id']
    marker = install_dir / f"mod_{mod_id}.version"
    
    status = "MISSING"
    if marker.exists():
        try:
            with open(marker, 'r') as f:
                if json.load(f).get('fid') == file_id: status = "OK"
                else: status = "UPDATE"
        except: status = "BROKEN"
    
    if dry_run:
        if status == "OK": print(f"   [OK] {name}")
        elif status == "MISSING": print(f"🆕 [NEW] {name}")
        elif status == "UPDATE": print(f"🆙 [UPD] {name}")
        return

    if status == "OK":
        print(f"🆗 {name}")
        return

    print(f"⬇️ {name} — Загрузка...")
    try:
        api_url = f"https://api.mod.io/v1/games/{GAME_ID}/mods/{mod_id}/files/{file_id}"
        r = requests.get(api_url, params={'api_key': MOD_IO_API_KEY}, timeout=15)
        if r.status_code == 404:
            print(f"⛔ {name} удален с Mod.io")
            send_log(f"❌ Мод **{name}** не найден на Mod.io", 0xff0000)
            return
        r.raise_for_status()
        
        file_data = r.json()
        
        # 🔥 ПРОВЕРКА 1: Platforms
        platforms = file_data.get('platforms', [])
        if platforms and 'windows' not in platforms:
            print(f"⚠️ {name} — Не Windows версия!")
            print(f"   Платформы: {platforms} | Пропускаю.")
            send_log(f"⚠️ **{name}** пропущен (Quest версия)", 0xffa500)
            return
        
        # 🔥 ПРОВЕРКА 2: Filename (дополнительная защита)
        filename = file_data.get('filename', '').lower()
        if 'quest' in filename or 'android' in filename or 'oculus' in filename:
            print(f"⚠️ {name} — Quest-версия по filename!")
            print(f"   Файл: {file_data.get('filename')} | Пропускаю.")
            send_log(f"⚠️ **{name}** пропущен (Quest по filename)", 0xffa500)
            return
        
        binary_url = file_data['download']['binary_url']
        
        with requests.get(binary_url, stream=True) as fr:
            fr.raise_for_status()
            with zipfile.ZipFile(BytesIO(fr.content)) as z:
                z.extractall(install_dir)
        
        with open(marker, 'w') as f:
            json.dump({'fid': file_id, 'name': name}, f)
        
        print(f"✅ {name} — ГОТОВО")
        send_log(f"✅ Установлен: **{name}**", 0x00ff00)
        
    except Exception as e:
        print(f"❌ {name}: {e}")
        send_log(f"⚠️ Сбой **{name}**: {e}", 0xffa500)

def main():
    install_path = find_default_path()
    active_profile = "manifest.json" 
    
    # Цвета для винды (включаем поддержку ANSI)
    os.system('') 

    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print("\033[1;36m========================================\033[0m")
        print(f"   BONLAB ULTIMATE SYNC | \033[33m{USER_NAME}\033[0m")
        print("\033[1;36m========================================\033[0m")
        print(f"📂 Папка: \033[90m{install_path}\033[0m")
        print(f"📜 Профиль: \033[1;32m{active_profile}\033[0m")
        print("----------------------------------------")
        
        print("1. \033[1;32m🚀 СИНХРОНИЗИРОВАТЬ\033[0m")
        print("2. 🔍 Проверка (Dry Run)")
        print("3. 🔄 Сменить профиль")
        print("4. 📂 Изменить путь установки")
        print("5. \033[1;31m🗑️ УДАЛИТЬ ВСЕ МОДЫ (Очистка)\033[0m")
        print("q. Выход")
        
        c = input("\n> ").strip().lower()
        
        if c == '1':
            if not install_path.exists():
                print(f"⚠️ Папки нет, создаем: {install_path}")
                install_path.mkdir(parents=True, exist_ok=True)

            manifest = get_manifest(active_profile)
            if manifest:
                mods = manifest['mods']
                print(f"\nЗапуск установки {len(mods)} модов...")
                send_log(f"🚀 **{USER_NAME}** начал установку `{active_profile}` ({len(mods)} шт).", 0x3498db)
                
                with ThreadPoolExecutor(max_workers=3) as ex:
                    futures = [ex.submit(process_mod, m, install_path, False) for m in mods]
                    for f in futures: f.result()
                
                print("\n✨ \033[1;32mВСЕ ОПЕРАЦИИ ЗАВЕРШЕНЫ!\033[0m")
                send_log(f"🏁 **{USER_NAME}** всё установил.", 0x3498db)
            input("Нажми Enter...")
            
        elif c == '2':
            manifest = get_manifest(active_profile)
            if manifest:
                print("\n--- Предпросмотр изменений ---")
                for m in manifest['mods']: process_mod(m, install_path, True)
            input("Нажми Enter...")
            
        elif c == '3':
            new_p = input("Имя профиля (например 'pvp'): ").strip()
            if new_p: active_profile = new_p
            
        elif c == '4':
            p = input("Новый путь: ").strip().strip('"')
            if p: install_path = Path(p)
            
        elif c == '5':
            clear_mods_folder(install_path)
            input("Нажми Enter...")
            
        elif c == 'q':
            sys.exit()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt: pass