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
import threading
import queue
import tkinter as tk
import ctypes  # Для MessageBox в Windows
from tkinter import ttk, filedialog, scrolledtext, messagebox
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= НАСТРОЙКИ =================
REPO_BASE_URL = "https://raw.githubusercontent.com/LelaPo/bonelab-mods/main/"
CONFIG_FILENAME = "config.public.json"
PROFILES_INDEX = "profiles/index.json"
APP_NAME = "BonelabModLoader"
VERSION = "4.1.0"
LOG_FILE = "BonelabModLoader.log"
# =============================================

# Очередь для передачи логов из потоков в GUI
log_queue = queue.Queue()

class QueueHandler(logging.Handler):
    """Отправляет логи в очередь для GUI"""
    def emit(self, record):
        log_queue.put(record)

# Настройка базового логгера
log = logging.getLogger(APP_NAME)
log.setLevel(logging.INFO)

# ================= CORE LOGIC =================

class ModInstaller:
    def __init__(self, config_source, progress_callback=None):
        """
        config_source: может быть argparse.Namespace ИЛИ dict
        progress_callback: функция(current, total, status_text)
        """
        self.repo_url = REPO_BASE_URL.strip().rstrip('/') + '/'
        self.config = {}
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': f'{APP_NAME}/{VERSION}'})
        self.progress_callback = progress_callback
        
        # 1. НОРМАЛИЗАЦИЯ АРГУМЕНТОВ (Fix NameError)
        # Превращаем входные данные в словарь params
        if isinstance(config_source, dict):
            self.params = config_source
        else:
            # Если это argparse.Namespace
            self.params = vars(config_source)

        # Извлекаем параметры безопасно
        path_arg = self.params.get('path')
        self.profile_name = self.params.get('profile', 'default')
        self.is_dry_run = self.params.get('dry_run', False)

        # 2. Определение путей
        self.install_path = self._resolve_install_path(path_arg)
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
            log.warning(f"⚠️ Не удалось загрузить конфиг: {e}. Используем дефолты.")

    def get_profiles_list(self):
        try:
            url = f"{self.repo_url}{PROFILES_INDEX}"
            r = self.session.get(url, params={'t': int(time.time())}, timeout=5)
            if r.status_code == 200:
                return r.json()
        except: pass
        return {}

    def get_profile_url(self, target_profile):
        profiles_index = self.get_profiles_list()
        
        # Если есть в индексе
        if target_profile in profiles_index:
            rel_path = profiles_index[target_profile]['path']
            return f"{self.repo_url}{rel_path}"

        # Дефолт из конфига
        if target_profile == "default":
            cfg_default = self.config.get("default_profile", "profiles/default.json")
            if cfg_default.startswith("http"): return cfg_default
            return f"{self.repo_url}{cfg_default}"

        # Прямой путь
        if not target_profile.endswith(".json"): target_profile += ".json"
        return f"{self.repo_url}profiles/{target_profile}"

    def load_manifest(self, profile_name):
        url = self.get_profile_url(profile_name)
        log.info(f"📡 Загрузка манифеста: {url}")
        try:
            r = self.session.get(url, params={'t': int(time.time())}, timeout=10)
            if r.status_code == 404:
                raise FileNotFoundError(f"Профиль не найден (404): {url}")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(f"❌ Ошибка загрузки манифеста: {e}")
            raise

    def send_log_webhook(self, message, color=0x3498db):
        if self.is_dry_run or not self.config.get('worker_url'): return
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
                raise RuntimeError(f"Security Alert: Zip Slip detected in {member.filename}")
            zip_ref.extract(member, target_path)

    def install_mod(self, mod):
        name = mod.get('name', 'Unknown')
        mod_id = mod['mod_id']
        file_id = mod['file_id']
        marker_path = self.install_path / f"mod_{mod_id}.version"
        
        # Check if installed
        if marker_path.exists():
            try:
                with open(marker_path, 'r') as f:
                    if json.load(f).get('fid') == file_id: return True
            except: pass

        log.info(f"📥 Скачивание: {name}")
        if self.is_dry_run: return True

        try:
            api_key = self.config.get('mod_io_key')
            if not api_key: raise ValueError("Нет API ключа Mod.io в конфиге")
            
            # 1. Get Metadata
            meta_url = f"https://api.mod.io/v1/games/3809/mods/{mod_id}/files/{file_id}"
            r = self.session.get(meta_url, params={'api_key': api_key}, timeout=10)
            r.raise_for_status()
            download_url = r.json()['download']['binary_url']

            # 2. Download Stream
            tmp_mod = self.temp_dir / str(mod_id)
            if tmp_mod.exists(): shutil.rmtree(tmp_mod)
            tmp_mod.mkdir(parents=True)
            
            zip_file = tmp_mod / "mod.zip"
            with self.session.get(download_url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(zip_file, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=65536): f.write(chunk)
            
            # 3. Extract Securely
            with zipfile.ZipFile(zip_file) as z:
                self._safe_extract(z, tmp_mod)
            zip_file.unlink()

            # 4. Install (Move)
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
            if not self.is_dry_run:
                self.send_log_webhook(f"🔥 Ошибка установки **{name}**: {e}", 0xe74c3c)
            return False

    def run_installation(self):
        """Возвращает True если всё ок, False если критическая ошибка"""
        self.load_config()
        
        # Если dry_run - пишем об этом
        if self.is_dry_run:
            log.info("⚠️ РЕЖИМ DRY-RUN: Скачивание отключено.")

        try:
            manifest = self.load_manifest(self.profile_name)
        except Exception:
            return False

        mods = manifest.get('mods', [])
        total_mods = len(mods)
        
        if not self.install_path.exists() and not self.is_dry_run:
            try:
                self.install_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                log.error(f"Не могу создать папку {self.install_path}: {e}")
                return False

        self.send_log_webhook(f"🚀 Старт: **{self.profile_name}** ({total_mods} модов)", 0x3498db)
        
        if self.temp_dir.exists(): shutil.rmtree(self.temp_dir)
        
        if self.progress_callback:
            self.progress_callback(0, total_mods, "Подготовка...")

        success_count = 0
        processed_count = 0
        
        with ThreadPoolExecutor(max_workers=3) as ex:
            futures = {ex.submit(self.install_mod, m): m for m in mods}
            
            for f in as_completed(futures):
                processed_count += 1
                result = f.result()
                if result: success_count += 1
                
                mod_name = futures[f].get('name', 'Unknown')
                if self.progress_callback:
                    status = f"Готово: {mod_name}" if result else f"Ошибка: {mod_name}"
                    self.progress_callback(processed_count, total_mods, status)

        if self.temp_dir.exists(): shutil.rmtree(self.temp_dir)
        
        log.info(f"🏁 Завершено. Успешно: {success_count}/{total_mods}")
        self.send_log_webhook(f"✅ Финиш: {success_count}/{total_mods}", 0x2ecc71)
        return True

# ================= GUI MODE =================

class BonelabGUI:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} v{VERSION}")
        self.root.geometry("600x550")
        try:
            self.root.iconbitmap("icon.ico")
        except: pass
        
        # Пустой инсталлер для получения списка профилей и путей
        self.installer_helper = ModInstaller({}) 
        self.profiles = {}

        # Styles
        style = ttk.Style()
        style.theme_use('clam')
        
        # Layout
        main_frame = ttk.Frame(root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=5)
        ttk.Label(header_frame, text=APP_NAME, font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT)
        ttk.Label(header_frame, text=f"v{VERSION}", foreground="gray").pack(side=tk.LEFT, padx=5, pady=(5,0))

        # Settings
        settings_frame = ttk.LabelFrame(main_frame, text="Настройки", padding="10")
        settings_frame.pack(fill=tk.X, pady=10)

        # Path
        path_frame = ttk.Frame(settings_frame)
        path_frame.pack(fill=tk.X)
        ttk.Label(path_frame, text="Папка Mods:").pack(side=tk.LEFT)
        self.path_var = tk.StringVar(value=str(self.installer_helper.install_path))
        self.path_entry = ttk.Entry(path_frame, textvariable=self.path_var)
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(path_frame, text="Обзор...", command=self.browse_path).pack(side=tk.LEFT)

        # Profile
        profile_frame = ttk.Frame(settings_frame)
        profile_frame.pack(fill=tk.X, pady=5)
        ttk.Label(profile_frame, text="Профиль:").pack(side=tk.LEFT)
        self.profile_combo = ttk.Combobox(profile_frame, state="readonly")
        self.profile_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.profile_desc = ttk.Label(profile_frame, text="Загрузка списка...", foreground="gray")
        self.profile_desc.pack(side=tk.LEFT)

        # Checkbox
        self.dry_run_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(settings_frame, text="Dry Run (только тест, без скачивания)", variable=self.dry_run_var).pack(anchor="w", pady=5)

        # Button
        action_frame = ttk.Frame(main_frame)
        action_frame.pack(fill=tk.X, pady=10)
        self.btn_install = ttk.Button(action_frame, text="🚀 УСТАНОВИТЬ МОДЫ", command=self.start_install_thread)
        self.btn_install.pack(fill=tk.X, ipady=10)

        # Progress
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=(0, 5))
        self.status_label = ttk.Label(main_frame, text="Готов к работе")
        self.status_label.pack(anchor="w")

        # Logs
        log_frame = ttk.LabelFrame(main_frame, text="Журнал событий", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.log_area = scrolledtext.ScrolledText(log_frame, state='disabled', height=10, font=("Consolas", 9))
        self.log_area.pack(fill=tk.BOTH, expand=True)
        self.log_area.tag_config("INFO", foreground="black")
        self.log_area.tag_config("WARNING", foreground="#cf6a00") # Dark Orange
        self.log_area.tag_config("ERROR", foreground="red")

        ttk.Button(log_frame, text="Копировать лог", command=self.copy_logs).pack(anchor="e", pady=5)

        # Initialization
        self.setup_logging()
        threading.Thread(target=self.fetch_profiles, daemon=True).start()
        self.root.after(100, self.update_gui_from_queue)

    def setup_logging(self):
        queue_handler = QueueHandler()
        queue_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', '%H:%M:%S'))
        logging.getLogger().addHandler(queue_handler)

    def browse_path(self):
        d = filedialog.askdirectory(initialdir=self.path_var.get())
        if d: self.path_var.set(d)

    def fetch_profiles(self):
        self.profiles = self.installer_helper.get_profiles_list()
        if 'default' not in self.profiles:
            self.profiles['default'] = {"title": "Default", "description": "По умолчанию"}
        
        values = list(self.profiles.keys())
        if 'default' in values:
            values.insert(0, values.pop(values.index('default')))
        
        def _update():
            self.profile_combo['values'] = values
            self.profile_combo.current(0)
            self.on_profile_change(None)
            self.profile_combo.bind("<<ComboboxSelected>>", self.on_profile_change)
        
        self.root.after(0, _update)

    def on_profile_change(self, event):
        val = self.profile_combo.get()
        if val in self.profiles:
            desc = self.profiles[val].get('description', '')
            self.profile_desc.config(text=desc)

    def update_gui_from_queue(self):
        while not log_queue.empty():
            try:
                record = log_queue.get_nowait()
                self.log_area.configure(state='normal')
                msg = f"{record.levelname}: {record.getMessage()}\n"
                self.log_area.insert(tk.END, msg, record.levelname)
                self.log_area.see(tk.END)
                self.log_area.configure(state='disabled')
            except queue.Empty: break
        self.root.after(100, self.update_gui_from_queue)

    def update_progress(self, current, total, status):
        def _update():
            if total > 0:
                pct = (current / total) * 100
                self.progress_var.set(pct)
            self.status_label.config(text=f"[{current}/{total}] {status}")
        self.root.after(0, _update)

    def start_install_thread(self):
        self.btn_install.config(state="disabled")
        self.path_entry.config(state="disabled")
        self.profile_combo.config(state="disabled")
        self.log_area.configure(state='normal')
        self.log_area.delete(1.0, tk.END)
        self.log_area.configure(state='disabled')
        
        args = {
            "path": self.path_var.get(),
            "profile": self.profile_combo.get(),
            "dry_run": self.dry_run_var.get()
        }

        threading.Thread(target=self.run_process, args=(args,), daemon=True).start()

    def run_process(self, args_dict):
        installer = ModInstaller(args_dict, progress_callback=self.update_progress)
        
        try:
            success = installer.run_installation()
            status = "✅ Готово!" if success else "❌ Ошибка (см. лог)"
        except Exception as e:
            log.error(f"Critical GUI error: {e}")
            status = "❌ Критическая ошибка!"

        def _finish():
            self.btn_install.config(state="normal")
            self.path_entry.config(state="normal")
            self.profile_combo.config(state="normal")
            self.status_label.config(text=status)
            messagebox.showinfo(APP_NAME, status)
        
        self.root.after(0, _finish)

    def copy_logs(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log_area.get(1.0, tk.END))
        messagebox.showinfo("Info", "Скопировано")

# ================= CLI MODE =================

def run_cli():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} CLI")
    parser.add_argument('--profile', default='default', help='Имя профиля')
    parser.add_argument('--list-profiles', action='store_true', help='Список профилей')
    parser.add_argument('--path', help='Путь к папке Mods')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    # Если запускаем CLI, но консоли нет (например, noconsole build + args),
    # нам нужно писать логи в файл, иначе никто не узнает об ошибках.
    handlers = []
    
    # Пишем в файл всегда при CLI запуске
    file_h = logging.FileHandler(LOG_FILE, mode='w', encoding='utf-8')
    file_h.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    handlers.append(file_h)

    # Если есть реальная консоль (stdout), добавляем вывод туда
    if sys.stdout is not None:
        console_h = logging.StreamHandler(sys.stdout)
        console_h.setFormatter(logging.Formatter('%(message)s'))
        handlers.append(console_h)
    
    logging.basicConfig(level=logging.INFO, handlers=handlers)

    installer = ModInstaller(args)
    
    # 1. Список профилей
    if args.list_profiles:
        log.info("Загрузка списка профилей...")
        profs = installer.get_profiles_list()
        log.info(f"\n📋 Доступные профили:")
        for k, v in profs.items():
            desc = v.get('description', '')
            log.info(f"{k:<15} | {v.get('title',''):<20} | {desc}")
        return

    # 2. Установка
    try:
        success = installer.run_installation()
        if not success:
            msg = f"Ошибка установки! Подробности в {LOG_FILE}"
            log.error(msg)
            # Если консоли нет, показываем алерт (Windows)
            if sys.stdout is None and platform.system() == "Windows":
                 ctypes.windll.user32.MessageBoxW(0, msg, f"{APP_NAME} Error", 0x10)
    except Exception as e:
        log.critical(f"Fatal CLI Error: {e}")
        if sys.stdout is None and platform.system() == "Windows":
             ctypes.windll.user32.MessageBoxW(0, str(e), f"{APP_NAME} Critical", 0x10)

    # Если консоль есть, ждем Enter (старое поведение)
    # Но проверяем, не перенаправлен ли ввод
    if sys.stdout is not None and sys.stdin is not None and sys.stdin.isatty():
         input("\nНажмите Enter для выхода...")

# ================= ENTRY POINT =================

def main():
    # Если переданы аргументы -> CLI
    if len(sys.argv) > 1:
        run_cli()
    else:
        # Иначе GUI
        root = tk.Tk()
        app = BonelabGUI(root)
        root.mainloop()

if __name__ == "__main__":
    main()