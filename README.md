# 🔧 Исправление Quest -> Windows версий модов

## Проблема
Mod.io хранит разные версии модов для Quest и PCVR. У них разные `file_id`, и если в манифест попадает Quest-версия, на PC моды не работают (нет моделек).

## Решение

### ✅ Что изменено:

**admin.py:**
- Умная логика определения Windows-версии:
  1. Сначала ищет по `platforms=['windows']`
  2. Если нет — фильтрует по filename (исключает 'quest', 'android', 'oculus')
  3. Берёт самый РАННИЙ файл (Windows обычно загружается первым)

**client.py:**
- Двойная проверка при скачивании:
  1. Проверяет `platforms` — если нет 'windows', пропускает
  2. Проверяет `filename` — если есть 'quest'/'android'/'oculus', пропускает

**migrate.py (новый):**
- Автоматически мигрирует старые манифесты
- Заменяет Quest file_id на Windows file_id

---

## 🚀 Как исправить твою finskaya.json за 1 клик:

### Вариант 1: Автоматическая миграция (РЕКОМЕНДУЕТСЯ)

```bash
python migrate.py finskaya.json
```

Это создаст `finskaya_fixed.json` с правильными Windows-версиями.

Потом просто:
```bash
mv finskaya_fixed.json finskaya.json  # Заменить старый
git add finskaya.json
git commit -m "Fixed Quest->Windows versions"
git push
```

### Вариант 2: Через admin.py

1. Открой `admin.py`
2. Выбери пункт **3 (Проверить обновления)**
3. Он автоматически пройдётся по всем модам и исправит file_id
4. Выбери пункт **7 (GIT PUSH)**

---

## 📝 Пример работы

### Было (Quest версия):
```json
{
  "name": "M82A1",
  "mod_id": 4908624,
  "file_id": 6391403,  ← Quest
}
```

### Стало (Windows версия):
```json
{
  "name": "M82A1",
  "mod_id": 4908624,
  "file_id": 6391402,  ← Windows
}
```

---

## 🔍 Как проверить что всё работает:

1. Запусти `admin.py`
2. Выбери **5 (Показать список)**
3. Проверь file_id для M82A1 — должен быть **6391402**, а не 6391403

Или просто:
```bash
python migrate.py finskaya.json
```

И посмотри в консоль — там будет написано что изменилось.

---

## ⚠️ Важно

После миграции друзья ДОЛЖНЫ пересинхронизироваться через `client.py` (пункт 1), чтобы скачать правильные версии.

Если у них уже стоят Quest-версии, можно:
1. Выбрать пункт **5 (Удалить все моды)**
2. Потом пункт **1 (Синхронизировать)** — чистая установка

---

## 📦 Структура файлов:

```
Bonelab_Sync/
├── admin.py          ← Обновлённый (умная логика Windows)
├── client.py         ← Обновлённый (двойная проверка)
├── migrate.py        ← НОВЫЙ (автомиграция)
├── finskaya.json     ← Твой манифест
└── README.md         ← Эта инструкция
```

---

## 🎯 Быстрый старт:

```bash
# 1. Исправь манифест
python migrate.py finskaya.json
mv finskaya_fixed.json finskaya.json

# 2. Залей на GitHub
git add .
git commit -m "Fixed Quest->PC versions + migration script"
git push

# 3. Скомпилируй новый client.exe (если нужно)
pyinstaller --onefile --noconsole client.py

# 4. Друзья обновят моды через client.exe
```

Готово! 🎉