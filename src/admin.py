#!/usr/bin/env python3
"""
Bonelab Mods Admin Panel v2.2
Управление профилями модов для https://github.com/LelaPo/bonelab-mods

Изменения v2.2:
- Используем поле platforms из мода для определения Windows file_id
- Поддержка прямых ссылок mod.io API (modapi.io)
- Улучшенный парсинг URL

Запуск из корня репозитория:
    python src/admin.py
"""

import os
import sys
import json
import re
import subprocess
from pathlib import Path
from datetime import datetime

# ================= НАСТРОЙКИ =================
GAME_ID = 3809  # Bonelab на mod.io
PROFILES_DIR = Path("profiles")
DEFAULT_PROFILE = "default"
ENV_FILE = Path(".env")
# =============================================

# Глобальное состояние
current_profile_name: str = DEFAULT_PROFILE
session = None


def load_dotenv():
    """Загружает переменные из .env файла."""
    if not ENV_FILE.exists():
        return
    
    with open(ENV_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            
            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip()
            
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            
            if key not in os.environ:
                os.environ[key] = value


def get_api_key() -> str:
    """Получает API ключ."""
    load_dotenv()
    
    key = os.environ.get("MOD_IO_API_KEY", "").strip()
    if not key:
        print("\n" + "=" * 60)
        print("❌ ОШИБКА: Не найден MOD_IO_API_KEY")
        print("=" * 60)
        print("\n📄 Создай файл .env в корне репозитория:")
        print("-" * 40)
        print("MOD_IO_API_KEY=ваш_ключ_здесь")
        print("-" * 40)
        print("\n🔑 Получить ключ: https://mod.io/me/access")
        print("=" * 60)
        sys.exit(1)
    return key


def get_session():
    """Ленивая инициализация requests.Session."""
    global session
    if session is None:
        try:
            import requests
        except ImportError:
            print("❌ Требуется: pip install requests")
            sys.exit(1)
        session = requests.Session()
        session.headers.update({"Accept": "application/json"})
    return session


def clear_console():
    os.system('cls' if os.name == 'nt' else 'clear')


# ================= РАБОТА С ПРОФИЛЯМИ =================

def get_profile_path(name: str) -> Path:
    if not name.endswith(".json"):
        name = f"{name}.json"
    return PROFILES_DIR / name


def list_profiles() -> list[str]:
    if not PROFILES_DIR.exists():
        return []
    profiles = []
    for f in PROFILES_DIR.glob("*.json"):
        if f.name == "index.json":
            continue
        profiles.append(f.stem)
    return sorted(profiles)


def load_profile(name: str) -> dict:
    path = get_profile_path(name)
    if not path.exists():
        return {
            "title": name.replace("_", " ").title(),
            "description": "",
            "mods": []
        }
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if "title" not in data:
        data["title"] = name.replace("_", " ").title()
    if "description" not in data:
        data["description"] = ""
    if "mods" not in data:
        data["mods"] = []
    return data


def save_profile(name: str, data: dict):
    errors = validate_profile(data)
    if errors:
        print(f"⚠️ Предупреждения валидации:")
        for e in errors:
            print(f"   - {e}")
    
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    path = get_profile_path(name)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"💾 Сохранено: {path}")


def validate_profile(data: dict) -> list[str]:
    errors = []
    if not isinstance(data.get("title"), str):
        errors.append("title должен быть строкой")
    if not isinstance(data.get("description"), str):
        errors.append("description должен быть строкой")
    if not isinstance(data.get("mods"), list):
        errors.append("mods должен быть списком")
        return errors
    
    for i, mod in enumerate(data["mods"]):
        if not isinstance(mod, dict):
            errors.append(f"mods[{i}] должен быть объектом")
            continue
        if not isinstance(mod.get("mod_id"), int):
            errors.append(f"mods[{i}].mod_id должен быть числом")
        if not isinstance(mod.get("file_id"), int):
            errors.append(f"mods[{i}].file_id должен быть числом")
    
    return errors


# ================= MOD.IO API =================

def api_request(endpoint: str, params: dict = None) -> dict:
    """Выполняет запрос к Mod.io API."""
    url = f"https://api.mod.io/v1/{endpoint}"
    all_params = {"api_key": get_api_key()}
    if params:
        all_params.update(params)
    
    r = get_session().get(url, params=all_params, timeout=15)
    r.raise_for_status()
    return r.json()


def parse_mod_url(url: str) -> dict | None:
    """
    Парсит различные форматы URL mod.io.
    
    Поддерживаемые форматы:
    1. https://mod.io/g/bonelab/m/mod-name
    2. https://mod.io/g/bonelab/m/mod-name#description
    3. https://g-3809.modapi.io/v1/games/3809/mods/5598648/files/7220249/download
    4. https://api.mod.io/v1/games/3809/mods/5598648/files/7220249
    
    Возвращает: {"type": "name_id"|"direct", "name_id": str, "mod_id": int, "file_id": int}
    """
    url = url.strip()
    
    # Формат 1-2: mod.io/g/bonelab/m/mod-name
    match = re.search(r'mod\.io/g/[^/]+/m/([^/?#]+)', url)
    if match:
        return {"type": "name_id", "name_id": match.group(1)}
    
    # Формат 3-4: modapi.io или api.mod.io с mod_id и file_id
    # Паттерн: /mods/{mod_id}/files/{file_id}
    match = re.search(r'/mods/(\d+)/files/(\d+)', url)
    if match:
        return {
            "type": "direct",
            "mod_id": int(match.group(1)),
            "file_id": int(match.group(2))
        }
    
    # Формат: только /mods/{mod_id}
    match = re.search(r'/mods/(\d+)(?:/|$|\?)', url)
    if match:
        return {"type": "mod_id_only", "mod_id": int(match.group(1))}
    
    return None


def get_mod_by_name_id(name_id: str) -> dict | None:
    """Получает мод по name_id (slug)."""
    print(f"🔎 Поиск: {name_id}...")
    try:
        data = api_request(f"games/{GAME_ID}/mods", {"name_id": name_id})
        if data["result_count"] == 0:
            print("❌ Мод не найден.")
            return None
        return data["data"][0]
    except Exception as e:
        print(f"❌ Ошибка API: {e}")
        return None


def get_mod_by_id(mod_id: int) -> dict | None:
    """Получает мод по ID."""
    print(f"🔎 Загрузка мода {mod_id}...")
    try:
        return api_request(f"games/{GAME_ID}/mods/{mod_id}")
    except Exception as e:
        print(f"❌ Ошибка API: {e}")
        return None


def get_windows_file_id_from_mod(mod_data: dict) -> int | None:
    """
    Извлекает file_id для Windows из данных мода.
    
    Использует поле 'platforms' которое содержит:
    [
        {"platform": "android", "modfile_live": 7220245},
        {"platform": "windows", "modfile_live": 7220249}
    ]
    """
    platforms = mod_data.get("platforms", [])
    
    # Ищем Windows
    for p in platforms:
        if p.get("platform") == "windows":
            file_id = p.get("modfile_live")
            if file_id:
                print(f"✅ Windows file_id: {file_id}")
                return file_id
    
    # Fallback: если только одна платформа - берём её
    if len(platforms) == 1:
        file_id = platforms[0].get("modfile_live")
        platform_name = platforms[0].get("platform", "unknown")
        print(f"⚠️ Только одна платформа ({platform_name}): file_id={file_id}")
        return file_id
    
    # Если platforms пустой - старый fallback через /files
    if not platforms:
        print("⚠️ Поле 'platforms' пустое, пробуем через /files...")
        return get_windows_file_id_fallback(mod_data["id"])
    
    # Есть platforms но нет windows
    print(f"❌ Windows версия не найдена!")
    print(f"   Доступные платформы: {[p.get('platform') for p in platforms]}")
    return None


def get_windows_file_id_fallback(mod_id: int) -> int | None:
    """
    Fallback: получает file_id через endpoint /files.
    Используется если поле platforms пустое.
    """
    try:
        data = api_request(f"games/{GAME_ID}/mods/{mod_id}/files")
        files = data.get("data", [])
        
        if not files:
            print("⚠️ У мода нет файлов!")
            return None
        
        # Сортируем: новые первые
        files = sorted(files, key=lambda x: x.get("date_added", 0), reverse=True)
        
        # По platforms в файле
        for f in files:
            platforms = f.get("platforms", [])
            if "windows" in platforms:
                print(f"✅ Windows (file.platforms): file_id={f['id']}")
                return f["id"]
        
        # По filename
        for f in files:
            fname = f.get("filename", "").lower()
            if not any(x in fname for x in ["quest", "android", "oculus"]):
                print(f"✅ PC (filename): file_id={f['id']} | {f['filename']}")
                return f["id"]
        
        # Первый файл
        print(f"⚠️ Fallback: первый файл: {files[0]['id']}")
        return files[0]["id"]
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return None


# ================= КОМАНДЫ МЕНЮ =================

def cmd_list_profiles():
    profiles = list_profiles()
    print(f"\n📂 Профили в {PROFILES_DIR}/:")
    if not profiles:
        print("   (пусто)")
        return
    for p in profiles:
        marker = " 👈" if p == current_profile_name else ""
        data = load_profile(p)
        title = data.get("title", "")
        mods_count = len(data.get("mods", []))
        print(f"   • {p:<20} | {title:<25} | {mods_count} модов{marker}")


def cmd_switch_profile():
    global current_profile_name
    
    cmd_list_profiles()
    
    print(f"\nТекущий: {current_profile_name}")
    print("Введите имя профиля (существующего или нового):")
    name = input("> ").strip().lower().replace(" ", "_")
    
    if not name:
        print("Отмена.")
        return
    
    if not re.match(r'^[a-z0-9_-]+$', name):
        print("❌ Имя может содержать только a-z, 0-9, _, -")
        return
    
    current_profile_name = name
    path = get_profile_path(name)
    
    if not path.exists():
        print(f"🆕 Будет создан новый профиль: {name}")
        data = load_profile(name)
        
        title = input(f"Title [{data['title']}]: ").strip()
        if title:
            data["title"] = title
        
        desc = input("Description: ").strip()
        if desc:
            data["description"] = desc
        
        save_profile(name, data)
    else:
        print(f"✅ Переключено на: {name}")


def cmd_edit_metadata():
    data = load_profile(current_profile_name)
    
    print(f"\n📝 Редактирование метаданных [{current_profile_name}]")
    print(f"Текущий title: {data['title']}")
    print(f"Текущий description: {data['description']}")
    
    title = input(f"\nНовый title (Enter = оставить): ").strip()
    if title:
        data["title"] = title
    
    desc = input(f"Новый description (Enter = оставить): ").strip()
    if desc:
        data["description"] = desc
    
    save_profile(current_profile_name, data)


def cmd_show_mods():
    data = load_profile(current_profile_name)
    mods = data.get("mods", [])
    
    print(f"\n📜 Моды в профиле [{current_profile_name}]:")
    print(f"   Title: {data.get('title', '')}")
    print(f"   Description: {data.get('description', '')}")
    print()
    
    if not mods:
        print("   (пусто)")
        return
    
    for i, m in enumerate(mods, 1):
        name = m.get("name", "???")
        print(f"   {i:2}. {name:<40} mod_id={m['mod_id']:<8} file_id={m['file_id']}")
    print(f"\n   Всего: {len(mods)} модов")


def cmd_add_mod():
    """Добавляет мод в профиль."""
    data = load_profile(current_profile_name)
    
    print("\n" + "=" * 50)
    print("ДОБАВЛЕНИЕ МОДА")
    print("=" * 50)
    print("\nПоддерживаемые форматы ввода:")
    print("  1. https://mod.io/g/bonelab/m/mod-name")
    print("  2. https://g-3809.modapi.io/.../mods/12345/files/67890/download")
    print("  3. mod_id (число) — автоопределение Windows версии")
    print("  4. mod_id file_id (два числа через пробел)")
    print()
    
    inp = input("> ").strip()
    if not inp:
        print("Отмена.")
        return
    
    mod_info = None
    
    # Проверяем URL
    if inp.startswith("http"):
        parsed = parse_mod_url(inp)
        
        if not parsed:
            print("❌ Не удалось распознать URL.")
            print("   Поддерживаемые форматы:")
            print("   • https://mod.io/g/bonelab/m/mod-name")
            print("   • https://g-3809.modapi.io/v1/games/3809/mods/ID/files/ID/download")
            return
        
        if parsed["type"] == "name_id":
            # Обычная ссылка mod.io
            mod_obj = get_mod_by_name_id(parsed["name_id"])
            if not mod_obj:
                return
            
            mod_name = mod_obj["name"]
            mod_id = mod_obj["id"]
            print(f"📦 Мод: {mod_name}")
            
            file_id = get_windows_file_id_from_mod(mod_obj)
            if not file_id:
                return
            
            mod_info = {"name": mod_name, "mod_id": mod_id, "file_id": file_id}
        
        elif parsed["type"] == "direct":
            # Прямая ссылка с mod_id и file_id
            mod_id = parsed["mod_id"]
            file_id = parsed["file_id"]
            
            print(f"📍 Прямая ссылка: mod_id={mod_id}, file_id={file_id}")
            
            # Получаем имя мода
            mod_obj = get_mod_by_id(mod_id)
            mod_name = mod_obj["name"] if mod_obj else f"Mod_{mod_id}"
            
            print(f"📦 Мод: {mod_name}")
            mod_info = {"name": mod_name, "mod_id": mod_id, "file_id": file_id}
        
        elif parsed["type"] == "mod_id_only":
            # Только mod_id в URL
            mod_id = parsed["mod_id"]
            mod_obj = get_mod_by_id(mod_id)
            if not mod_obj:
                return
            
            mod_name = mod_obj["name"]
            print(f"📦 Мод: {mod_name}")
            
            file_id = get_windows_file_id_from_mod(mod_obj)
            if not file_id:
                return
            
            mod_info = {"name": mod_name, "mod_id": mod_id, "file_id": file_id}
    
    # Два числа через пробел: mod_id file_id
    elif " " in inp:
        parts = inp.split()
        try:
            mod_id = int(parts[0])
            file_id = int(parts[1])
        except (ValueError, IndexError):
            print("❌ Формат: mod_id file_id (два числа)")
            return
        
        mod_obj = get_mod_by_id(mod_id)
        mod_name = mod_obj["name"] if mod_obj else f"Mod_{mod_id}"
        
        mod_info = {"name": mod_name, "mod_id": mod_id, "file_id": file_id}
    
    # Одно число: mod_id
    else:
        try:
            mod_id = int(inp)
        except ValueError:
            print("❌ Введите URL, mod_id или 'mod_id file_id'")
            return
        
        mod_obj = get_mod_by_id(mod_id)
        if not mod_obj:
            return
        
        mod_name = mod_obj["name"]
        print(f"📦 Мод: {mod_name}")
        
        file_id = get_windows_file_id_from_mod(mod_obj)
        if not file_id:
            return
        
        mod_info = {"name": mod_name, "mod_id": mod_id, "file_id": file_id}
    
    # Проверяем дубликат
    for i, existing in enumerate(data["mods"]):
        if existing["mod_id"] == mod_info["mod_id"]:
            if existing["file_id"] != mod_info["file_id"]:
                print(f"🔄 Обновление: file_id {existing['file_id']} → {mod_info['file_id']}")
            else:
                print("✅ Уже в профиле с актуальной версией")
            data["mods"][i] = mod_info
            save_profile(current_profile_name, data)
            return
    
    data["mods"].append(mod_info)
    print(f"✅ Добавлен: {mod_info['name']}")
    save_profile(current_profile_name, data)


def cmd_remove_mod():
    data = load_profile(current_profile_name)
    mods = data.get("mods", [])
    
    if not mods:
        print("Список пуст.")
        return
    
    cmd_show_mods()
    
    try:
        idx = int(input("\nНомер для удаления (0 = отмена): "))
    except ValueError:
        print("Отмена.")
        return
    
    if idx <= 0 or idx > len(mods):
        print("Отмена.")
        return
    
    removed = mods.pop(idx - 1)
    data["mods"] = mods
    save_profile(current_profile_name, data)
    print(f"🗑️ Удалён: {removed.get('name', removed['mod_id'])}")


def cmd_update_all():
    """Проверяет обновления всех модов."""
    data = load_profile(current_profile_name)
    mods = data.get("mods", [])
    
    if not mods:
        print("Список пуст.")
        return
    
    print(f"\n🔄 Проверка обновлений ({len(mods)} модов)...")
    updated = 0
    
    for i, mod in enumerate(mods):
        name = mod.get("name", f"Mod_{mod['mod_id']}")
        print(f"\n[{i+1}/{len(mods)}] {name}...")
        
        mod_obj = get_mod_by_id(mod["mod_id"])
        if not mod_obj:
            print("   ⚠️ Не удалось получить данные мода")
            continue
        
        new_file_id = get_windows_file_id_from_mod(mod_obj)
        if not new_file_id:
            print("   ⚠️ Не удалось получить file_id")
            continue
        
        if new_file_id != mod["file_id"]:
            print(f"   🆙 UPDATE: {mod['file_id']} → {new_file_id}")
            data["mods"][i]["file_id"] = new_file_id
            # Обновляем имя если изменилось
            data["mods"][i]["name"] = mod_obj["name"]
            updated += 1
        else:
            print("   ✅ Актуально")
    
    if updated > 0:
        save_profile(current_profile_name, data)
        print(f"\n✅ Обновлено: {updated} модов")
    else:
        print("\n💤 Всё актуально")


def cmd_validate():
    data = load_profile(current_profile_name)
    errors = validate_profile(data)
    
    if errors:
        print(f"\n❌ Ошибки в профиле [{current_profile_name}]:")
        for e in errors:
            print(f"   • {e}")
    else:
        print(f"\n✅ Профиль [{current_profile_name}] валиден")
        print(f"   Title: {data['title']}")
        print(f"   Description: {data['description']}")
        print(f"   Mods: {len(data['mods'])}")


def cmd_clear_profile():
    confirm = input("Введите YES для очистки: ").strip()
    if confirm != "YES":
        print("Отмена.")
        return
    
    data = load_profile(current_profile_name)
    data["mods"] = []
    save_profile(current_profile_name, data)
    print("🧹 Список модов очищен")


# ================= GIT =================

def run_git(*args) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True,
            text=True,
            timeout=60
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return -1, "", "Git не установлен"
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout"


def cmd_git_push():
    print("\n🚀 Git: commit + push")
    
    print("\n📥 git pull --no-rebase...")
    code, out, err = run_git("pull", "--no-rebase")
    if code != 0 and "CONFLICT" in (err + out):
        print("\n❌ КОНФЛИКТ! Разреши вручную и повтори.")
        return
    
    code, out, err = run_git("status", "--porcelain")
    changes = [l for l in out.strip().split("\n") if l and "profiles/" in l]
    
    if not changes:
        print("⚠️ Нет изменений в profiles/")
        return
    
    print(f"\n📝 Изменения:")
    for line in changes:
        print(f"   {line}")
    
    run_git("add", "profiles/")
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = f"Update profiles {timestamp}"
    custom_msg = input(f"\nCommit message [{msg}]: ").strip()
    if custom_msg:
        msg = custom_msg
    
    code, out, err = run_git("commit", "-m", msg)
    if code != 0 and "nothing to commit" in (out + err):
        print("⚠️ Нечего коммитить")
        return
    
    print("\n📤 git push...")
    code, out, err = run_git("push")
    if code != 0:
        print(f"❌ Push error: {err}")
        return
    
    print("✅ Push OK!")


def cmd_git_status():
    code, out, err = run_git("status", "-s")
    print("\n📋 Git status:")
    print(out if out.strip() else "   (чисто)")


def cmd_create_env():
    if ENV_FILE.exists():
        print(f"⚠️ {ENV_FILE} уже существует!")
        if input("Перезаписать? (y/N): ").strip().lower() != 'y':
            return
    
    api_key = input("MOD_IO_API_KEY (Enter для пустого): ").strip()
    
    content = f"""# Bonelab Mods Admin
# НЕ КОММИТИТЬ В GIT!

MOD_IO_API_KEY={api_key}
"""
    
    with open(ENV_FILE, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"✅ Создан {ENV_FILE}")


# ================= ГЛАВНОЕ МЕНЮ =================

def main_menu():
    global current_profile_name
    
    while True:
        clear_console()
        
        env_status = "✅ .env" if ENV_FILE.exists() else "⚠️ .env отсутствует"
        
        print(f"\033[1;36m{'=' * 50}\033[0m")
        print(f"\033[1;36m  BONELAB MODS ADMIN v2.2\033[0m")
        print(f"\033[1;36m  Профиль: [{current_profile_name}] | {env_status}\033[0m")
        print(f"\033[1;36m{'=' * 50}\033[0m")
        
        print("\n📦 МОДЫ:")
        print("  1. Показать список")
        print("  2. Добавить мод")
        print("  3. Удалить мод")
        print("  4. Проверить обновления")
        print("  5. Очистить список")
        
        print("\n📂 ПРОФИЛИ:")
        print("  6. Список профилей")
        print("  7. Сменить/создать профиль")
        print("  8. Редактировать title/description")
        print("  9. Валидация")
        
        print("\n🔧 GIT & CONFIG:")
        print("  p. PUSH")
        print("  s. Status")
        print("  e. Создать .env")
        
        print("\n  q. Выход")
        
        choice = input("\n> ").strip().lower()
        
        actions = {
            "1": cmd_show_mods,
            "2": cmd_add_mod,
            "3": cmd_remove_mod,
            "4": cmd_update_all,
            "5": cmd_clear_profile,
            "6": cmd_list_profiles,
            "7": cmd_switch_profile,
            "8": cmd_edit_metadata,
            "9": cmd_validate,
            "p": cmd_git_push,
            "s": cmd_git_status,
            "e": cmd_create_env,
        }
        
        if choice == "q":
            print("\n👋 Пока!")
            break
        elif choice in actions:
            actions[choice]()
        else:
            print("❓ Неизвестная команда")
        
        if choice != "q":
            input("\n⏎ Enter...")


def main():
    if not Path(".git").exists():
        print("⚠️ Запускай из корня репозитория")
        sys.exit(1)
    
    PROFILES_DIR.mkdir(exist_ok=True)
    main_menu()


if __name__ == "__main__":
    main()
