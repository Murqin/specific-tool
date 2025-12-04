# modules/core.py
import os
import json
import sys
import shutil
from pathlib import Path
import winreg
import time
import psutil
import win32gui
import win32process
import atexit
import logging
from logging.handlers import RotatingFileHandler
from typing import List, Dict, Any, Optional
from .constants import APP_NAME, DATA_DIR, LOG_FILE, CONFIG_FILE
from .hardware import IMouseBackend, IGPUBackend, IOSMouseService

def setup_logging():
    if not os.path.exists(DATA_DIR):
        try: os.makedirs(DATA_DIR)
        except: pass
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            RotatingFileHandler(
                LOG_FILE, 
                maxBytes=2*1024*1024, 
                backupCount=2,     
                encoding='utf-8',
                mode='a'          
            ), 
            logging.StreamHandler(sys.stdout)
        ]
    )

setup_logging()
logger = logging.getLogger(__name__)



class AppManager:
    """
    Manages application installation and startup persistence.
    
    Handles startup registry operations
    the Windows Registry key for startup execution.
    """
    def __init__(self):
        self.appdata_dir = DATA_DIR
        if getattr(sys, 'frozen', False):
            self.current_path = sys.executable
            self.exe_name = os.path.basename(sys.executable)
        else:
            self.current_path = os.path.abspath(sys.argv[0])
            self.exe_name = f"{APP_NAME}.exe"
        self.target_path = self.current_path
        self.reg_key = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def is_startup_enabled(self) -> bool:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.reg_key, 0, winreg.KEY_READ)
            val, _ = winreg.QueryValueEx(key, APP_NAME)
            winreg.CloseKey(key)
            return self.current_path in val
        except Exception as e:
            logger.warning(f"Failed to check startup status: {e}")
            return False

    def set_startup(self, enable=True):
        try:
            import subprocess
            if enable:
                subprocess.run([
                "powershell",
                "-Command",
                "Start-Process reg -ArgumentList 'add HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run /v \"%s\" /t REG_SZ /d \"%s\" /f' -Verb RunAs" 
                % (APP_NAME, self.current_path)
                ])
            else:
                subprocess.run([
                "powershell",
                "-Command",
                "Start-Process reg -ArgumentList 'delete HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run /v \"%s\" /f' -Verb RunAs" 
                % APP_NAME
            ])
            return True
        except Exception as e:
            logger.error(f"Failed to set startup: {e}")
            return False

    def set_startup_value(self, val):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.reg_key, 0, winreg.KEY_ALL_ACCESS)
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, val)
            winreg.CloseKey(key)
        except: pass

class ConfigManager:
    """
    Manages application settings and game profiles.
    
    Loads and saves configuration from a JSON file in the AppData directory.
    """
    def __init__(self):
        self.path = CONFIG_FILE
        self.games: List[str] = []
        self.settings: Dict[str, Any] = {
            "start_in_tray": False, 
            "single_monitor": True, 
            "startup": False,
            "murqin_mode": False
        }
        self._load()

    @property
    def murqin_mode(self) -> bool:
        return self.settings.get("murqin_mode", False)

    @murqin_mode.setter
    def murqin_mode(self, value: bool):
        self.settings["murqin_mode"] = value
        self.save()

    def _load(self):
        if not os.path.exists(self.path): return
        try:
            with open(self.path, "r") as f:
                data = json.load(f)
                if isinstance(data, list): self.games = data
                else:
                    self.games = data.get("games", [])
                    self.settings.update(data.get("settings", {}))
        except json.JSONDecodeError:
            logger.error("Settings file is corrupted. Using defaults.")
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")

    def save(self):
        if not os.path.exists(os.path.dirname(self.path)): os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as f:
            json.dump({"games": self.games, "settings": self.settings}, f)

class ProcessMonitor:
    """
    Monitors the active foreground window to detect running games.
    """
    def get_active_exe(self) -> str:
        """
        Retrieves the executable name of the current foreground window.
        
        Returns:
            str: The executable name (lowercase), or empty string if failed.
        """
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd: return ""
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid <= 0: return ""
            return psutil.Process(pid).name().lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return ""
        except Exception as e:
            logger.debug(f"Process monitor error: {e}")
            return ""

class AutomationEngine:
    """
    Core automation logic.
    
    Runs in a background thread, monitors the active process, and switches
    profiles (Mouse/GPU) based on whether a configured game is active.
    """
    def __init__(self, config: ConfigManager, mouse: IMouseBackend, gpu: IGPUBackend, os_mouse: IOSMouseService, ui_provider):
        self.cfg, self.mouse, self.gpu, self.os_mouse = config, mouse, gpu, os_mouse
        self.ui_provider = ui_provider
        self.running = True
        self.current_state = "unknown"
        self._pm = ProcessMonitor()

    def loop(self):
        stable, req, last = 0, 2, ""
        while True:
            if not self.running: time.sleep(1); continue
            try:
                curr = self._pm.get_active_exe()
                if curr != last: stable = 0; last = curr
                else: stable += 1
                
                if stable < req: time.sleep(0.5); continue

                is_game = any(g in curr for g in self.cfg.games)
                v_desk = self.ui_provider('vib_desk')
                v_game = self.ui_provider('vib_game')
                murqin = self.ui_provider('murqin')
                single_mon = self.cfg.settings.get("single_monitor", True)

                if is_game:
                    if self.current_state != "game":
                        self.gpu.set_vibrance(v_game, single_mon)
                        self.mouse.set_game_mode()
                        
                        # Sync Murqin Mode from UI to Config if changed, or enforce config
                        # Since we can't easily read UI state here without a callback, we rely on the UI calling us or us checking a shared state.
                        # However, the requirement is "remember on next startup".
                        # So we just need to make sure that when the UI toggles it, it saves to config.
                        # But here in the loop, we are applying the mode.
                        
                        if murqin: 
                            self.os_mouse.optimize(800, 1600)
                            if not self.cfg.murqin_mode: # If config says False but UI says True (user toggled it on)
                                self.cfg.murqin_mode = True
                        else:
                            if self.cfg.murqin_mode: # If config says True but UI says False (user toggled it off)
                                self.cfg.murqin_mode = False
                        
                        self.ui_provider('status')("GAME MODE ACTIVE", True)
                        self.current_state = "game"
                else:
                    if self.current_state != "desktop":
                        self.gpu.set_vibrance(v_desk, single_mon)
                        self.mouse.set_desktop_mode()
                        self.os_mouse.reset()
                        self.ui_provider('status')("DESKTOP MODE", False)
                        self.current_state = "desktop"
            except Exception as e:
                logger.error(f"Automation loop error: {e}")
            time.sleep(0.5)

class SafetyProtocol:
    def __init__(self, mouse: IMouseBackend, gpu: IGPUBackend, os_mouse: IOSMouseService, ui_provider):
        self.mouse, self.gpu, self.os_mouse, self.ui = mouse, gpu, os_mouse, ui_provider
        self._executed = False
        atexit.register(self.execute)

    def execute(self):
        if self._executed: return
        self._executed = True
        print("[Safety] Restoring Defaults...")
        try: self.os_mouse.reset()
        except Exception as e: logger.error(f"Safety reset mouse error: {e}")
        try: self.mouse.set_desktop_mode()
        except Exception as e: logger.error(f"Safety reset hardware mouse error: {e}")
        try:
            d_vib = self.ui('vib_desk') if self.ui else 50
            self.gpu.set_vibrance(d_vib, primary_only=False)
        except Exception as e: logger.error(f"Safety reset GPU error: {e}")
