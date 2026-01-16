import os
import json
import glob

# Настройки
PROFILES_DIR = "profiles"
INDEX_FILE = "profiles/index.json"

def main():
    index = {}
    
    # Ищем все .json файлы в папке profiles
    files = glob.glob(os.path.join(PROFILES_DIR, "*.json"))
    
    print(f"🔄 Сканирование {len(files)} файлов...")

    for filepath in files:
        filename = os.path.basename(filepath)
        if filename == "index.json": continue # Пропускаем сам индекс
        
        profile_id = os.path.splitext(filename)[0] # "pvp.json" -> "pvp"
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Извлекаем метаданные или ставим дефолт
            title = data.get('title', profile_id.capitalize())
            desc = data.get('description', 'Описание отсутствует')
            
            index[profile_id] = {
                "path": f"{PROFILES_DIR}/{filename}",
                "title": title,
                "description": desc
            }
            print(f"✅ Добавлен: {profile_id}")
            
        except Exception as e:
            print(f"⚠️ Ошибка чтения {filename}: {e}")

    # Сортируем по ключу для красоты
    sorted_index = dict(sorted(index.items()))

    # Сохраняем index.json
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(sorted_index, f, indent=2, ensure_ascii=False)
    
    print(f"💾 Индекс сохранен: {INDEX_FILE}")

if __name__ == "__main__":
    main()