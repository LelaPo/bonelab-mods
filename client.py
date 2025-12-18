import os
import json
import requests
import zipfile
import time
import sys
import platform
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# ================= НАСТРОЙКИ =================
# Укажи базу репозитория (без имени файла в конце!)
# Пример: https://raw.githubusercontent.com/User/Repo/main/
REPO_BASE_URL = "https://raw.githubusercontent.com/LelaPo/bonelab-mods/refs/heads/main/"

MOD_IO_API_KEY = "cc192d4610be216a225b6f8e0ab62780"
GAME_ID = 3809 

# Сюда вставь ссылку на Вебхук Дискорда
WEBHOOK_URL = "https://discord.com/api/webhooks/1449419271775064155/nC-thoDkpEaS3u29UP6uEzxKKFA4Cj62ok14Dc1eODbKN5ncQ17rrEQOA8dsgaT2z1Mc"
# =============================================

# Имя пользователя Windows (для логов)
USER_NAME = os.environ.get('USERNAME', 'Unknown User')

def send_log(message, color=0x00ff00):
    """Отправляет сообщение в Discord"""
    if not WEBHOOK_URL: return
    
    payload = {
        "username": "BonLab Updater",
        "embeds": [{
            "description": message,
            "color": color,
            "footer": {"text": f"User: {USER_NAME} | OS: {platform.system()}"},
            "timestamp": datetime.utcnow().isoformat()
        }]
    }
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=2)
    except:
        pass # Логи не должны ломать работу программы

from datetime import datetime # Нужен для таймстемпа в логах

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
    # Если пользователь ввел 'pvp', добавляем '.json'
    if not profile_name.endswith(".json"):
        profile_name += ".json"
        
    url = f"{REPO_BASE_URL}{profile_name}"
    print(f"📡 Загрузка профиля: {profile_name}...")
    
    try:
        r = requests.get(f"{url}?t={int(time.time())}", timeout=10)
        if r.status_code == 404:
            print("❌ Профиль не найден на сервере!")
            return None
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"❌ Ошибка сети: {e}")
        return None

def process_mod(mod, install_dir, dry_run=False):
    name = mod['name']
    mod_id = mod['mod_id']
    file_id = mod['file_id']
    marker = install_dir / f"mod_{mod_id}.version"
    
    # Проверка
    status = "MISSING"
    if marker.exists():
        try:
            with open(marker, 'r') as f:
                if json.load(f).get('fid') == file_id: status = "OK"
                else: status = "UPDATE"
        except: status = "BROKEN"
    
    if dry_run:
        if status != "OK": print(f"👉 {name} [{status}]")
        return

    if status == "OK":
        print(f"🆗 {name}")
        return

    print(f"⬇️ {name} — Скачивание...")
    try:
        # Получение ссылки
        api_url = f"https://api.mod.io/v1/games/{GAME_ID}/mods/{mod_id}/files/{file_id}"
        r = requests.get(api_url, params={'api_key': MOD_IO_API_KEY}, timeout=15)
        if r.status_code == 404:
            print(f"⛔ {name} удален с Mod.io")
            send_log(f"❌ Ошибка: Мод **{name}** удален с Mod.io", 0xff0000)
            return
        r.raise_for_status()
        binary_url = r.json()['download']['binary_url']
        
        # Скачивание
        with requests.get(binary_url, stream=True) as fr:
            fr.raise_for_status()
            with zipfile.ZipFile(BytesIO(fr.content)) as z:
                z.extractall(install_dir)
        
        with open(marker, 'w') as f:
            json.dump({'fid': file_id, 'name': name}, f)
        
        print(f"✅ {name} — ГОТОВО")
        # Логируем успешную установку (только если это было обновление или установка)
        send_log(f"✅ Установлен мод: **{name}**", 0x00ff00)
        
    except Exception as e:
        print(f"❌ {name}: {e}")
        send_log(f"⚠️ Ошибка установки **{name}**: {e}", 0xffa500)

def main():
    install_path = find_default_path()
    # По умолчанию основной профиль
    active_profile = "manifest.json" 
    
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print("========================================")
        print(f"   BONLAB SYNC | User: {USER_NAME}")
        print("========================================")
        print(f"📂 Папка: {install_path}")
        print(f"📜 Профиль: {active_profile}")
        print("----------------------------------------")
        
        print("1. 🚀 СИНХРОНИЗИРОВАТЬ")
        print("2. 🔍 Проверка (Dry Run)")
        print("3. 🔄 Сменить профиль (stable/pvp/etc)")
        print("4. 📂 Изменить папку")
        print("q. Выход")
        
        c = input("\n> ").strip().lower()
        
        if c == '1':
            manifest = get_manifest(active_profile)
            if manifest:
                mods = manifest['mods']
                print(f"\nЗапуск установки {len(mods)} модов...")
                send_log(f"🚀 **{USER_NAME}** начал синхронизацию профиля `{active_profile}` ({len(mods)} модов).", 0x3498db)
                
                with ThreadPoolExecutor(max_workers=3) as ex:
                    futures = [ex.submit(process_mod, m, install_path, False) for m in mods]
                    for f in futures: f.result()
                
                print("\n✨ Готово!")
                send_log(f"🏁 **{USER_NAME}** завершил синхронизацию.", 0x3498db)
            input("Enter...")
            
        elif c == '2':
            manifest = get_manifest(active_profile)
            if manifest:
                print("\n--- Что изменится ---")
                for m in manifest['mods']: process_mod(m, install_path, True)
            input("Enter...")
            
        elif c == '3':
            new_p = input("Введите имя профиля (по умолчанию manifest): ").strip()
            if new_p: active_profile = new_p
            
        elif c == '4':
            p = input("Путь: ").strip().strip('"')
            if p: install_path = Path(p)
            
        elif c == 'q':
            sys.exit()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt: pass