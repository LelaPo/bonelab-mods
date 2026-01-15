#!/usr/bin/env python3
"""
СКРИПТ МИГРАЦИИ: Quest -> Windows версии модов
Использование: python migrate.py finskaya.json
Результат: finskaya_fixed.json
"""
import json
import sys
import requests
from datetime import datetime

MOD_IO_API_KEY = "cc192d4610be216a225b6f8e0ab62780"
GAME_ID = 3809
HEADERS = {'Accept': 'application/json', 'Content-Type': 'application/json'}
PARAMS = {'api_key': MOD_IO_API_KEY}

def get_windows_file_id(mod_id, mod_name):
    """Получает Windows-версию мода (умная логика)"""
    try:
        r = requests.get(f"https://api.mod.io/v1/games/{GAME_ID}/mods/{mod_id}/files",
                         params=PARAMS, headers=HEADERS, timeout=10)
        r.raise_for_status()
        files = r.json()['data']
        
        if not files:
            return None
        
        # Сортируем по дате (старые первые)
        files = sorted(files, key=lambda x: x['date_added'])
        
        # Шаг 1: Пробуем platforms
        windows_files = [f for f in files if 'windows' in f.get('platforms', [])]
        if windows_files:
            return windows_files[-1]['id']  # Самый свежий Windows
        
        # Шаг 2: Фильтруем по filename
        pc_files = []
        for f in files:
            fname = f['filename'].lower()
            if 'quest' not in fname and 'android' not in fname and 'oculus' not in fname:
                pc_files.append(f)
        
        if pc_files:
            return pc_files[0]['id']  # Самый ранний (обычно Windows)
        
        # Фолбек: первый файл
        return files[0]['id']
        
    except Exception as e:
        print(f"  ❌ Ошибка API: {e}")
        return None

def migrate_manifest(input_file):
    """Мигрирует старый манифест в новый с Windows-версиями"""
    
    print(f"\n🔄 Открываю: {input_file}")
    
    with open(input_file, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    
    total = len(manifest['mods'])
    print(f"📦 Найдено модов: {total}\n")
    print("="*60)
    
    updated = 0
    errors = 0
    
    for i, mod in enumerate(manifest['mods'], 1):
        print(f"\n[{i}/{total}] {mod['name']}")
        print(f"   Текущий file_id: {mod['file_id']}")
        
        try:
            new_file_id = get_windows_file_id(mod['mod_id'], mod['name'])
            
            if not new_file_id:
                print(f"   ⚠️ Не удалось получить file_id")
                errors += 1
                continue
            
            if new_file_id != mod['file_id']:
                print(f"   🔄 ИЗМЕНЁН: {mod['file_id']} -> {new_file_id}")
                manifest['mods'][i-1]['file_id'] = new_file_id
                updated += 1
            else:
                print(f"   ✅ Уже правильная версия")
                
        except Exception as e:
            print(f"   ❌ Ошибка: {e}")
            errors += 1
    
    # Сохраняем
    manifest['last_updated'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    output_file = input_file.replace('.json', '_fixed.json')
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    
    print("\n" + "="*60)
    print(f"\n✅ ГОТОВО!")
    print(f"   Обновлено: {updated} модов")
    print(f"   Без изменений: {total - updated - errors}")
    print(f"   Ошибок: {errors}")
    print(f"\n📁 Сохранено в: {output_file}")
    print("\nТеперь можешь заменить старый файл на новый и сделать git push!")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python migrate.py <имя_файла.json>")
        print("Пример: python migrate.py finskaya.json")
        sys.exit(1)
    
    input_file = sys.argv[1]
    migrate_manifest(input_file)