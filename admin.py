import os
import json
import re
import subprocess
import requests
from datetime import datetime

# ================= НАСТРОЙКИ =================
MOD_IO_API_KEY = "cc192d4610be216a225b6f8e0ab62780"
GAME_ID = 3809  # Bonelab

# По умолчанию работаем с основным манифестом
DEFAULT_PROFILE = "manifest.json"
# =============================================

HEADERS = {'Accept': 'application/json', 'Content-Type': 'application/json'}
PARAMS = {'api_key': MOD_IO_API_KEY}

# Глобальная переменная текущего профиля
current_profile = DEFAULT_PROFILE

def load_manifest():
    if not os.path.exists(current_profile):
        return {"last_updated": "", "mods": []}
    with open(current_profile, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_manifest(data):
    data['last_updated'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(current_profile, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"💾 Профиль '{current_profile}' сохранен. Модов: {len(data['mods'])}")

def switch_profile():
    global current_profile
    print(f"\nТекущий профиль: {current_profile}")
    name = input("Введите имя профиля (например 'pvp' или 'main'): ").strip()
    if not name: return
    
    # Если пользователь не ввел расширение .json, добавим его
    if not name.endswith(".json"):
        name += ".json"
    
    current_profile = name
    
    # Если файла нет, создадим пустой
    if not os.path.exists(current_profile):
        print(f"🆕 Создан новый профиль: {current_profile}")
        save_manifest({"last_updated": "", "mods": []})
    else:
        print(f"📂 Переключились на: {current_profile}")

def clear_manifest():
    print(f"\n⚠️ ВНИМАНИЕ! Вы собираетесь удалить ВСЕ моды из профиля '{current_profile}'.")
    confirm = input("Напишите 'YES' для подтверждения: ")
    if confirm == "YES":
        data = load_manifest()
        data['mods'] = []
        save_manifest(data)
        print("🗑️ Список очищен.")
    else:
        print("Отмена.")

def get_mod_info(url):
    match = re.search(r'/m/([^/?#]+)', url)
    if not match:
        print("❌ Ссылка должна быть вида .../m/mod-name")
        return None
    
    name_id = match.group(1)
    print(f"🔎 Ищем: {name_id}...")

    try:
        # Ищем ID
        r = requests.get(f"https://api.mod.io/v1/games/{GAME_ID}/mods", 
                         params={**PARAMS, 'name_id': name_id}, headers=HEADERS)
        r.raise_for_status()
        data = r.json()
        
        if data['result_count'] == 0:
            print("❌ Мод не найден.")
            return None
        
        mod_obj = data['data'][0]
        
        if not mod_obj.get('modfile'):
            print(f"⚠️ У мода '{mod_obj['name']}' нет файлов!")
            return None
            
        return {
            "name": mod_obj['name'],
            "mod_id": mod_obj['id'],
            "file_id": mod_obj['modfile']['id'],
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
            print(f"🔄 Обновление версии: {mod['file_id']} -> {new_mod['file_id']}")
            manifest['mods'][i] = new_mod
            save_manifest(manifest)
            return

    manifest['mods'].append(new_mod)
    print(f"✅ Добавлен: {new_mod['name']}")
    save_manifest(manifest)

def update_all():
    manifest = load_manifest()
    print(f"🔄 Проверка {len(manifest['mods'])} модов в '{current_profile}'...")
    count = 0
    for i, mod in enumerate(manifest['mods']):
        try:
            url = f"https://api.mod.io/v1/games/{GAME_ID}/mods/{mod['mod_id']}"
            r = requests.get(url, params=PARAMS, headers=HEADERS)
            latest = r.json().get('modfile')
            if latest and latest['id'] != mod['file_id']:
                print(f"🆙 UPDATE: {mod['name']}")
                manifest['mods'][i]['file_id'] = latest['id']
                count += 1
            else:
                print(f". {mod['name']} ok")
        except: pass
    
    if count > 0: save_manifest(manifest)
    else: print("💤 Обновлений нет.")

def push_to_github():
    print("\n🚀 Отправка ВСЕХ профилей на GitHub...")
    try:
        # git add . добавляет все новые файлы (включая новые профили)
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", f"Update profiles {datetime.now().strftime('%H:%M')}"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("✅ Успешно!")
    except Exception as e:
        print(f"❌ Ошибка Git: {e}")

def main():
    while True:
        print(f"\n--- ADMIN PANEL [{current_profile}] ---")
        print("1. Добавить мод")
        print("2. Проверить обновления")
        print("3. Сменить профиль / Создать новый")
        print("4. Очистить текущий список")
        print("5. ОТПРАВИТЬ (Git Push)")
        print("q. Выход")
        
        c = input("Выбор: ").strip()
        if c == '1': add_mod(input("Ссылка: ").strip())
        elif c == '2': update_all()
        elif c == '3': switch_profile()
        elif c == '4': clear_manifest()
        elif c == '5': push_to_github()
        elif c == 'q': break

if __name__ == "__main__":
    main()