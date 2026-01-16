import os
import json
import re
import glob
import subprocess
import requests
from datetime import datetime

# ================= НАСТРОЙКИ АДМИНА =================
MOD_IO_API_KEY = "cc192d4610be216a225b6f8e0ab62780"
GAME_ID = 3809  # Bonelab ID
# ====================================================

HEADERS = {'Accept': 'application/json', 'Content-Type': 'application/json'}
PARAMS = {'api_key': MOD_IO_API_KEY}

current_profile = "manifest.json"

def clear_console():
    """Очищает консоль для Windows и Linux"""
    os.system('cls' if os.name == 'nt' else 'clear')

def load_manifest():
    if not os.path.exists(current_profile):
        return {"last_updated": "", "mods": []}
    with open(current_profile, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_manifest(data):
    data['last_updated'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(current_profile, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"💾 Профиль '{current_profile}' сохранен.")

# --- УПРАВЛЕНИЕ ПРОФИЛЯМИ ---
def list_profiles():
    files = glob.glob("*.json")
    return [f for f in files if f != "manifest_schema.json"]

def switch_profile():
    global current_profile
    profiles = list_profiles()
    
    print(f"📂 Текущий профиль: {current_profile}")
    print("Доступные профили:")
    for i, p in enumerate(profiles, 1):
        print(f"{i}. {p}")
    
    print("\nВведите номер, имя существующего или имя для НОВОГО профиля:")
    choice = input("> ").strip()
    
    if not choice: return

    if choice.isdigit() and 1 <= int(choice) <= len(profiles):
        current_profile = profiles[int(choice)-1]
    else:
        if not choice.endswith(".json"): choice += ".json"
        current_profile = choice
        if not os.path.exists(current_profile):
            print(f"🆕 Будет создан новый профиль: {current_profile}")
            save_manifest({"last_updated": "", "mods": []})

# --- РАБОТА С МОДАМИ ---
def get_windows_file_id(mod_id, mod_name=""):
    """
    Получает Windows-версию мода.
    Логика:
    1. Фильтруем по platforms=['windows']
    2. Если нет - ищем по filename (без 'quest', 'android')
    3. Если несколько вариантов - берём с МЕНЬШИМ file_id (Windows обычно раньше)
    """
    try:
        r = requests.get(f"https://api.mod.io/v1/games/{GAME_ID}/mods/{mod_id}/files",
                         params=PARAMS, headers=HEADERS, timeout=10)
        r.raise_for_status()
        files = r.json()['data']
        
        if not files:
            return None
        
        # Сортируем по дате (старые первые - обычно это Windows)
        files = sorted(files, key=lambda x: x['date_added'])
        
        # Шаг 1: Пробуем найти файлы с platforms=['windows']
        windows_files = [f for f in files if 'windows' in f.get('platforms', [])]
        
        if windows_files:
            latest = windows_files[-1]  # Берём самый свежий Windows
            print(f"✅ Windows (по platforms): file_id={latest['id']}")
            return latest['id']
        
        # Шаг 2: Фильтруем по filename
        print(f"⚠️ Поле 'platforms' пустое, фильтрую по filename...")
        
        # Исключаем Quest/Android версии
        pc_files = []
        for f in files:
            fname = f['filename'].lower()
            if 'quest' not in fname and 'android' not in fname and 'oculus' not in fname:
                pc_files.append(f)
        
        if not pc_files:
            print(f"⚠️ Не найдено PC-версий по filename, беру первый файл (обычно Windows)")
            return files[0]['id']
        
        # Берём самый РАННИЙ файл (Windows обычно загружается первым)
        selected = pc_files[0]
        print(f"✅ PC версия (по filename): file_id={selected['id']} | {selected['filename']}")
        return selected['id']
        
    except Exception as e:
        print(f"❌ Ошибка получения файлов: {e}")
        return None

def get_mod_info(url):
    match = re.search(r'/m/([^/?#]+)', url)
    if not match:
        print("❌ Ссылка должна быть вида .../m/mod-name")
        return None
    
    name_id = match.group(1)
    print(f"🔎 Поиск API: {name_id}...")

    try:
        r = requests.get(f"https://api.mod.io/v1/games/{GAME_ID}/mods", 
                         params={**PARAMS, 'name_id': name_id}, headers=HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        if data['result_count'] == 0:
            print("❌ Мод не найден.")
            return None
        
        mod_obj = data['data'][0]
        mod_id = mod_obj['id']
        mod_name = mod_obj['name']
        
        print(f"📦 Мод: {mod_name}")
        
        # 🔥 ВАЖНО: получаем Windows-версию
        file_id = get_windows_file_id(mod_id, mod_name)
        
        if not file_id:
            print(f"⚠️ У мода '{mod_name}' нет файлов!")
            return None
            
        return {
            "name": mod_name,
            "mod_id": mod_id,
            "file_id": file_id,
            "url": url,
            "required": True
        }
    except Exception as e:
        print(f"❌ Ошибка API: {e}")
        return None

def add_mod(url):
    manifest = load_manifest()
    new_mod = get_mod_info(url)
    if not new_mod: return

    for i, mod in enumerate(manifest['mods']):
        if mod['mod_id'] == new_mod['mod_id']:
            if mod['file_id'] != new_mod['file_id']:
                print(f"🔄 Апдейт версии: {mod['file_id']} -> {new_mod['file_id']}")
            else:
                print(f"✅ Уже актуальная версия")
            manifest['mods'][i] = new_mod
            save_manifest(manifest)
            return

    manifest['mods'].append(new_mod)
    print(f"✅ Добавлен: {new_mod['name']}")
    save_manifest(manifest)

def remove_single_mod():
    manifest = load_manifest()
    mods = manifest['mods']
    if not mods:
        print("Список пуст.")
        return

    print(f"\n--- Удаление мода из {current_profile} ---")
    for i, mod in enumerate(mods, 1):
        print(f"{i}. {mod['name']}")
    
    try:
        idx = int(input("\nНомер для удаления (0 - отмена): "))
        if idx > 0 and idx <= len(mods):
            removed = mods.pop(idx-1)
            manifest['mods'] = mods
            save_manifest(manifest)
            print(f"🗑️ Удален: {removed['name']}")
        else:
            print("Отмена.")
    except ValueError: pass

def update_all():
    manifest = load_manifest()
    print(f"🔄 Проверка {len(manifest['mods'])} модов...")
    count = 0
    
    for i, mod in enumerate(manifest['mods']):
        print(f"\n[{i+1}/{len(manifest['mods'])}] {mod['name']}...")
        try:
            # 🔥 Получаем актуальную Windows-версию
            new_file_id = get_windows_file_id(mod['mod_id'], mod['name'])
            
            if new_file_id and new_file_id != mod['file_id']:
                print(f"   🆙 UPDATE: {mod['file_id']} -> {new_file_id}")
                manifest['mods'][i]['file_id'] = new_file_id
                count += 1
            else:
                print(f"   ✅ OK")
        except Exception as e:
            print(f"   ❌ {e}")
    
    if count > 0: 
        save_manifest(manifest)
        print(f"\n✅ Обновлено {count} модов")
    else: 
        print("\n💤 Обновлений нет.")

def push_to_github():
    print("\n🚀 Отправка на GitHub...")
    try:
        subprocess.run(["git", "add", "*.json"], check=True)
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not status.stdout.strip():
            print("⚠️ Нет изменений для отправки.")
            return

        subprocess.run(["git", "commit", "-m", f"Mods Update {datetime.now().strftime('%H:%M')}"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("✅ Успешно отправлено!")
    except Exception as e:
        print(f"❌ Ошибка Git: {e}")

def show_list():
    manifest = load_manifest()
    print(f"\n📜 Список модов в '{current_profile}':")
    for i, m in enumerate(manifest['mods'], 1):
        print(f"{i:2}. {m['name']} (ID: {m['mod_id']}, File: {m['file_id']})")
    print(f"Всего: {len(manifest['mods'])}")

# ==========================================
# ОСНОВНОЙ ЦИКЛ
# ==========================================
def main():
    while True:
        clear_console()
        
        print(f"\033[1;36m=== ADMIN PANEL [{current_profile}] ===\033[0m")
        print("1. ➕ Добавить мод (ссылка)")
        print("2. ➖ Удалить один мод")
        print("3. 🔄 Проверить обновления (исправляет Quest->PC)")
        print("4. 📂 Сменить / Создать профиль")
        print("5. 📜 Показать список")
        print("6. 🧹 Очистить весь список")
        print("7. 🚀 ОТПРАВИТЬ (GIT PUSH)")
        print("q. Выход")
        
        c = input("\nВыбор: ").strip()
        
        if c == '1': 
            add_mod(input("Ссылка: ").strip())
            input("\nНажмите Enter...")
            
        elif c == '2': 
            remove_single_mod()
            input("\nНажмите Enter...")
            
        elif c == '3': 
            update_all()
            input("\nНажмите Enter...")
            
        elif c == '4': 
            switch_profile()
            
        elif c == '5': 
            show_list()
            input("\nНажмите Enter...")
            
        elif c == '6':
            if input("Напиши YES для очистки: ") == "YES":
                save_manifest({"last_updated": "", "mods": []})
                print("Очищено.")
            input("\nНажмите Enter...")
            
        elif c == '7': 
            push_to_github()
            input("\nНажмите Enter...")
            
        elif c == 'q': 
            break

if __name__ == "__main__":
    main()