import customtkinter as ctk
import threading
import os
import sys
import tempfile
import queue
import psutil
import pystray
from typing import Union
from PIL import Image, ImageDraw

# Assuming these modules/constants exist in the application's structure
from .constants import APP_NAME, VERSION, THEME, FONT_HEADER, FONT_SUBHEAD, FONT_BODY, FONT_SMALL
from .core import AppManager, ConfigManager, AutomationEngine, SafetyProtocol
from .hardware import VXEMouseBackend, NvidiaService, WindowsMouseService

# ==========================================================
# ICON GENERATION UTILITY
# ==========================================================

def setup_custom_icon(window_instance: ctk.CTk) -> Union[str, None]:
    """
    Generates and sets a minimalist Kaomoji icon for the application window.

    Args:
        window_instance: The customtkinter window instance.

    Returns:
        str: Path to the generated icon file, or None if failed.
    """
    try:
        size = 64
        # Create a dark background image
        img = Image.new('RGB', (size, size), color=(18, 18, 18))
        draw = ImageDraw.Draw(img)
        white = (224, 224, 224)

        # Draw the kaomoji face elements (minimalist design)
        draw.rectangle([10, 28, 25, 32], fill=white)  # Left eye
        draw.rectangle([39, 28, 54, 32], fill=white)  # Right eye
        draw.rectangle([18, 48, 46, 52], fill=white)  # Mouth

        # Save as a temporary ICO file
        path = os.path.join(tempfile.gettempdir(), "specific_kaomoji.ico")
        img.save(path, format='ICO', sizes=[(64, 64)])
        
        # Set the window icon
        window_instance.iconbitmap(path)
        return path
    except Exception:
        return None

# ==========================================================
# MAIN APPLICATION CLASS
# ==========================================================

class App(ctk.CTk):
    """
    Main Application Class.

    Inherits from customtkinter.CTk. Handles the UI layout, user interactions,
    and coordinates the backend services (Hardware, Automation).
    """
    def __init__(self):
        super().__init__()

        # --- 1. Managers & Hardware Initialization ---
        self._init_managers_and_hardware()

        # --- 2. App State Initialization ---
        self._init_app_state()

        # --- 3. Core Logic Setup ---
        self.safety = SafetyProtocol(self.hw_mouse, self.hw_gpu, self.hw_os, self.get_ui_state)
        self.engine = AutomationEngine(self.cfg, self.hw_mouse, self.hw_gpu, self.hw_os, self.get_ui_state)

        # --- 4. UI Setup & System Integration ---
        self.setup_window()
        self.setup_layout()

        self._init_system_integration()
        self.process_ui_queue()  # Start the UI update loop

        # Start the main automation loop in a separate daemon thread
        threading.Thread(target=self.engine.loop, daemon=True).start()

        # Handle startup minimized argument
        if "--minimized" in sys.argv:
            self.withdraw()

    def _init_managers_and_hardware(self):
        """Initializes configuration managers and hardware services."""
        self.cfg = ConfigManager()
        self.cfg.save()  # Ensure configuration is saved on startup
        self.mgr = AppManager()
        

        self.hw_mouse = VXEMouseBackend()
        self.hw_mouse_connected = self.hw_mouse.connect()
        self.hw_gpu = NvidiaService()
        self.hw_os = WindowsMouseService()

    def _init_app_state(self):
        """Initializes application state variables and thread safety mechanisms."""
        self.icon_path = setup_custom_icon(self)
        self.tray_icon = None
        self.running = False
        self.murqin_mode = False

        # Thread-safe queue for UI updates
        # Tkinter is NOT thread-safe, so all UI manipulation must be queued
        self.ui_queue = queue.Queue()

    def _init_system_integration(self):
        """Sets up window close protocol, minimize binding, and system tray icon."""
        self.init_tray()
        # Override default close behavior to quit safely
        self.protocol("WM_DELETE_WINDOW", self.quit_safe)
        # Handle minimization to hide window and show tray icon
        self.bind("<Unmap>", self.on_minimize)

    # ==========================================================
    # THREAD-SAFE UI UPDATE MECHANISM
    # ==========================================================

    def process_ui_queue(self):
        """
        Periodically checks the UI queue for pending updates and executes them
        in the main thread, ensuring thread safety for Tkinter operations.
        """
        try:
            while True:
                # Use get_nowait() to avoid blocking the main thread
                func = self.ui_queue.get_nowait()
                func()
        except queue.Empty:
            pass
        finally:
            # Schedule the next check in 100ms
            self.after(100, self.process_ui_queue)

    def enqueue_ui_update(self, func):
        """
        Adds a callable to the UI queue to be executed in the main thread.

        Args:
            func: A callable (function or lambda) containing the UI update code.
        """
        self.ui_queue.put(func)

    def get_ui_state(self, key: str):
        """
        Callback method passed to AutomationEngine to retrieve current UI values safely.

        Args:
            key (str): The identifier for the requested state (e.g., 'vib_desk').

        Returns:
            The value of the requested UI element, or a default value if retrieval failed.
        """
        try:
            if key == 'vib_desk':
                # Note: get() is thread-safe for CTk variables, but slider state is usually safe too.
                return int(self.slider_vib_desk.get())
            if key == 'vib_game':
                return int(self.slider_vib_game.get())
            if key == 'murqin':
                return bool(self.chk_murqin.get())
            if key == 'status':
                return self.update_status_ui
        except Exception:
            # Provide a safe default value
            return 50 if 'vib' in key else None

    def update_status_ui(self, text: str, is_game: bool):
        """
        Updates the main status label and dot color, ensuring it's executed
        in the main UI thread via the queue.
        """
        def _update():
            dot_color = THEME["ACCENT"] if is_game else THEME["TEXT_SEC"]
            text_color = THEME["TEXT_PRI"] if is_game else THEME["TEXT_SEC"]
            self.lbl_status_dot.configure(text_color=dot_color)
            self.lbl_status_text.configure(text=text, text_color=text_color)
        self.enqueue_ui_update(_update)

    # ==========================================================
    # LAYOUT CONSTRUCTION
    # ==========================================================

    def setup_window(self):
        """Configures basic window properties."""
        self.title(APP_NAME)
        self.geometry("450x750")
        self.resizable(False, False)
        self.configure(fg_color=THEME["BG"])
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("dark-blue")

    def setup_layout(self):
        """Sets up the main grid structure."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1) # Row 2 (content) takes remaining space

        self._build_header()
        self._build_tabs()
        self._build_content_area()

        self.switch_tab("Dashboard")

    def _build_header(self):
        """Constructs the application header."""
        self.header = ctk.CTkFrame(self, fg_color="transparent", height=60)
        self.header.grid(row=0, column=0, sticky="ew", padx=25, pady=(25, 10))

        # Title
        ctk.CTkLabel(self.header, text="Specific Tool", font=FONT_HEADER, text_color=THEME["TEXT_PRI"]).pack(side="left")
        # Version
        ctk.CTkLabel(self.header, text=VERSION, font=FONT_SMALL, text_color=THEME["TEXT_PRI"]).pack(side="left", padx=5, pady=(0, 15))

    def _build_tabs(self):
        """Constructs the tab navigation bar."""
        self.tabs_frame = ctk.CTkFrame(self, fg_color="transparent", height=40)
        self.tabs_frame.grid(row=1, column=0, sticky="ew", padx=25, pady=(0, 15))

        self.tab_btns = {}
        for tab in ["Dashboard", "Profiles", "Settings"]:
            btn = ctk.CTkButton(
                self.tabs_frame, text=tab, font=FONT_BODY, width=80, height=30,
                fg_color="transparent", text_color=THEME["TEXT_SEC"], hover_color=THEME["HOVER"],
                corner_radius=6, command=lambda t=tab: self.switch_tab(t)
            )
            btn.pack(side="left", padx=(0, 5))
            self.tab_btns[tab] = btn

    def _build_content_area(self):
        """Sets up the content area and builds the view frames."""
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=2, column=0, sticky="nsew", padx=25, pady=(0, 25))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.views = {}
        for view_name in ["Dashboard", "Profiles", "Settings"]:
            frame = ctk.CTkFrame(self.content, fg_color="transparent")
            frame.grid(row=0, column=0, sticky="nsew")
            self.views[view_name] = frame
            # Dynamically call the view-specific builder method
            getattr(self, f"build_{view_name.lower()}")(frame)

    # --- Component Builders ---

    def create_status_row(self, parent, label: str, status: str, active: bool):
        """Creates a full-width status row with visible border."""
        # Container
        row = ctk.CTkFrame(parent, fg_color="transparent", border_width=1, border_color=THEME["BORDER"], corner_radius=8)
        row.pack(fill="x", pady=(0, 10))

        # Inner Layout
        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(fill="x", padx=15, pady=12)

        # Label (Left)
        ctk.CTkLabel(inner, text=label, font=("Arial", 11, "bold"), text_color=THEME["TEXT_SEC"]).pack(side="left")

        # Dot (Right)
        dot_color = THEME["SUCCESS"] if active else THEME["CRITICAL"]
        canvas = ctk.CTkCanvas(inner, width=8, height=8, bg=THEME["BG"], highlightthickness=0)
        canvas.pack(side="right", padx=(10, 0))
        canvas.create_oval(1, 1, 7, 7, fill=dot_color, outline="")

        # Status Text (Right of Dot)
        stat_txt = status.upper()
        ctk.CTkLabel(inner, text=stat_txt, font=("Arial", 11, "bold"), text_color=THEME["TEXT_PRI"]).pack(side="right")

    def create_vercel_switch(self, parent, text: str, subtext: str, cmd=None):
        """Creates a switch component with main and sub text, resembling Vercel's UI style."""
        f = ctk.CTkFrame(parent, fg_color="transparent")
        lbl_f = ctk.CTkFrame(f, fg_color="transparent")
        lbl_f.pack(side="left")

        # Main Text
        ctk.CTkLabel(lbl_f, text=text, font=FONT_BODY, text_color=THEME["TEXT_PRI"]).pack(anchor="w")
        # Sub Text
        ctk.CTkLabel(lbl_f, text=subtext, font=FONT_SMALL, text_color=THEME["TEXT_SEC"]).pack(anchor="w")

        # Switch
        s = ctk.CTkSwitch(f, text="", progress_color=THEME["ACCENT"], fg_color=THEME["BORDER"],
                          button_color="#555555", button_hover_color="#777777", width=40, command=cmd)
        s.pack(side="right")
        return s, f

    def switch_tab(self, name: str):
        """Raises the selected content view and updates the tab button appearance."""
        self.views[name].tkraise()
        for n, btn in self.tab_btns.items():
            btn.configure(text_color=THEME["TEXT_PRI"] if n == name else THEME["TEXT_SEC"])

    # --- View Content Builders ---

    def build_dashboard(self, p: ctk.CTkFrame):
        """Constructs the content for the Dashboard view."""
        # 1. Status Card (Toggle Button)
        card = ctk.CTkFrame(p, fg_color="transparent", border_width=1, border_color=THEME["BORDER"], corner_radius=8)
        card.pack(fill="x", pady=(0, 15))

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=20)

        is_running = self.engine.running

        # Status Dot
        dot_color = THEME["ACCENT"] if is_running else THEME["TEXT_SEC"]
        self.lbl_status_dot = ctk.CTkLabel(top, text="●", font=("Arial", 12), text_color=dot_color)
        self.lbl_status_dot.pack(side="left", padx=(0, 5))
        # Status Text
        status_text = "Monitoring Process..." if is_running else "System Idle"
        self.lbl_status_text = ctk.CTkLabel(top, text=status_text, font=FONT_SUBHEAD, text_color=THEME["TEXT_SEC"])
        self.lbl_status_text.pack(side="left")

        # Toggle Button
        btn_text = "STOP AUTOMATION" if is_running else "Start Automation"
        btn_color = THEME["CRITICAL"] if is_running else THEME["ACCENT"]
        text_color = "#FFFFFF" if is_running else "#000000"
        self.btn_toggle = ctk.CTkButton(
            card,
            text=btn_text,
            font=FONT_SUBHEAD, height=45,
            fg_color=btn_color,
            text_color=text_color,
            hover_color="#CCCCCC", corner_radius=6,
            command=self.toggle_engine
        )
        self.btn_toggle.pack(fill="x", padx=20, pady=(0, 20))

        # 2. Config Card (Murqin Mode)
        conf_card = ctk.CTkFrame(p, fg_color="transparent", border_width=1, border_color=THEME["BORDER"], corner_radius=8)
        conf_card.pack(fill="x", pady=(0, 20))
        self.chk_murqin, f = self.create_vercel_switch(conf_card, "Murqin Mode", "Input Normalization", self.toggle_murqin)
        if self.cfg.settings.get("murqin_mode", False):
            self.chk_murqin.select()
            self.murqin_mode = True
        else:
            self.chk_murqin.deselect()
            self.murqin_mode = False
        f.pack(fill="x", padx=20, pady=20)

        # 3. Hardware Status Area
        footer_label = ctk.CTkLabel(p, text="HARDWARE STATUS", font=("Arial", 10, "bold"), text_color=THEME["BORDER"])
        footer_label.pack(fill="x", anchor="w", padx=5, pady=(10, 10))

        status_container = ctk.CTkFrame(p, fg_color="transparent")
        status_container.pack(fill="x")

        # Mouse Status Row
        m_status = "ONLINE" if self.hw_mouse_connected else "OFFLINE"
        self.create_status_row(status_container, "MOUSE", m_status, self.hw_mouse_connected)

        # NVIDIA Status Row
        g_status = "READY" if self.hw_gpu.available else "NOT FOUND"
        self.create_status_row(status_container, "NVIDIA", g_status, self.hw_gpu.available)

    def build_profiles(self, p: ctk.CTkFrame):
        """Constructs the content for the Profiles view."""
        # 1. Unified Input Bar (Add Game)
        inp_card = ctk.CTkFrame(p, fg_color="transparent", border_width=1, border_color=THEME["BORDER"], corner_radius=8)
        inp_card.pack(fill="x", pady=(0, 15))

        # Add Button
        ctk.CTkButton(inp_card, text="+", width=40, height=32, fg_color=THEME["ACCENT"], text_color="#000000", hover_color="#CCCCCC", corner_radius=6, command=self.add_game).pack(side="right", padx=(5, 8), pady=4)
        # Scan Button
        ctk.CTkButton(inp_card, text="Scan", width=40, height=32, fg_color=THEME["ACCENT"], text_color="#000000", hover_color="#CCCCCC", corner_radius=6, border_width=0, command=self.scan_process).pack(side="right", padx=(0, 5))
        # Entry Field
        self.entry_game = ctk.CTkEntry(inp_card, placeholder_text="executable_name.exe", border_width=0, fg_color="transparent", text_color=THEME["TEXT_PRI"], placeholder_text_color=THEME["TEXT_SEC"], height=32, font=FONT_BODY)
        self.entry_game.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=0)

        # 2. Game List
        self.scroll_list = ctk.CTkScrollableFrame(p, fg_color="transparent", border_width=1, border_color=THEME["BORDER"], corner_radius=8)
        self.scroll_list.pack(fill="both", expand=True, pady=(0, 15))
        self.update_game_list()

        # 3. In-Game Vibrance Slider
        vib_card = ctk.CTkFrame(p, fg_color="transparent", border_width=1, border_color=THEME["BORDER"], corner_radius=8)
        vib_card.pack(fill="x")

        # Slider Label/Value Row
        top = ctk.CTkFrame(vib_card, fg_color="transparent")
        top.pack(fill="x", padx=15, pady=(15, 5))
        ctk.CTkLabel(top, text="In-Game Vibrance", font=FONT_BODY, text_color=THEME["TEXT_PRI"]).pack(side="left")
        self.lbl_vib_game = ctk.CTkLabel(top, text="100%", font=FONT_BODY, text_color=THEME["TEXT_SEC"])
        self.lbl_vib_game.pack(side="right")

        # Slider
        self.slider_vib_game = ctk.CTkSlider(
            vib_card, from_=0, to=100, number_of_steps=100,
            button_color=THEME["ACCENT"], progress_color=THEME["ACCENT"],
            button_hover_color="#FFFFFF", command=lambda v: self.on_vib_change(v, True)
        )
        self.slider_vib_game.set(100)
        self.slider_vib_game.pack(fill="x", padx=15, pady=(0, 15))

    def build_settings(self, p: ctk.CTkFrame):
        """Constructs the content for the Settings view."""
        # 1. System Settings Card
        card = ctk.CTkFrame(p, fg_color="transparent", border_width=1, border_color=THEME["BORDER"], corner_radius=8)
        card.pack(fill="x", pady=(0, 15))

        # Windows Startup Switch
        self.chk_startup, f1 = self.create_vercel_switch(card, "Windows Startup", "Launch on boot", self.toggle_startup)
        f1.pack(fill="x", padx=20, pady=(20, 10))
        if self.mgr.is_startup_enabled():
            self.chk_startup.select()

        # Start Minimized Switch
        self.chk_tray, f2 = self.create_vercel_switch(card, "Start Minimized", "Boot to tray icon", self.save_settings)
        f2.pack(fill="x", padx=20, pady=10)
        if self.cfg.settings.get("start_in_tray", True):
            self.chk_tray.select()

        # Single Monitor Switch
        self.chk_single, f3 = self.create_vercel_switch(card, "Single Monitor", "Primary display only", self.save_settings)
        f3.pack(fill="x", padx=20, pady=(10, 20))
        if self.cfg.settings.get("single_monitor", True):
            self.chk_single.select()

        # 2. Desktop Vibrance Card
        d_card = ctk.CTkFrame(p, fg_color="transparent", border_width=1, border_color=THEME["BORDER"], corner_radius=8)
        d_card.pack(fill="x", pady=(0, 15))

        # Slider Label/Value Row
        top = ctk.CTkFrame(d_card, fg_color="transparent")
        top.pack(fill="x", padx=15, pady=(15, 5))
        ctk.CTkLabel(top, text="Desktop Vibrance", font=FONT_BODY, text_color=THEME["TEXT_PRI"]).pack(side="left")
        self.lbl_vib_desk = ctk.CTkLabel(top, text="50%", font=FONT_BODY, text_color=THEME["TEXT_SEC"])
        self.lbl_vib_desk.pack(side="right")

        # Slider
        self.slider_vib_desk = ctk.CTkSlider(
            d_card, from_=0, to=100, number_of_steps=100,
            button_color=THEME["ACCENT"], progress_color=THEME["ACCENT"],
            button_hover_color="#FFFFFF", command=lambda v: self.on_vib_change(v, False)
        )
        self.slider_vib_desk.set(50)
        self.slider_vib_desk.pack(fill="x", padx=15, pady=(0, 15))

        # 3. Config Folder Button
        ctk.CTkButton(
            p, text="Open Config Folder", fg_color="transparent", text_color=THEME["TEXT_SEC"],
            font=FONT_SMALL, hover_color=THEME["HOVER"],
            command=lambda: os.startfile(self.mgr.appdata_dir)
        ).pack()

    # ==========================================================
    # ACTIONS / COMMANDS
    # ==========================================================

    def toggle_engine(self):
        """Toggles the automation engine on/off and updates the dashboard UI."""
        self.engine.running = not self.engine.running
        is_running = self.engine.running

        if is_running:
            self.btn_toggle.configure(text="STOP AUTOMATION", fg_color=THEME["CRITICAL"], text_color="#FFFFFF")
            self.lbl_status_text.configure(text="Monitoring Process...")
            self.lbl_status_dot.configure(text_color=THEME["ACCENT"])
        else:
            self.btn_toggle.configure(text="START AUTOMATION", fg_color=THEME["ACCENT"], text_color="#000000")
            # Execute safety protocol (e.g., reset settings) on stop
            self.safety.execute()
            self.lbl_status_text.configure(text="System Idle")
            self.lbl_status_dot.configure(text_color=THEME["TEXT_SEC"])
            self.engine.current_state = "unknown"

    def on_vib_change(self, value: float, is_game: bool):
        """
        Updates the vibrance label and applies the setting if the engine is running
        and the current state matches the change (game or desktop).
        """
        val = int(value)
        lbl = self.lbl_vib_game if is_game else self.lbl_vib_desk
        lbl.configure(text=f"{val}%")

        mode = "game" if is_game else "desktop"
        # Only apply the setting if the engine is active in the corresponding state
        if self.engine.running and self.engine.current_state == mode:
            try:
                primary_only = bool(self.chk_single.get())
            except AttributeError:
                # Fallback if chk_single is not yet initialized (shouldn't happen post-setup)
                primary_only = False
            self.hw_gpu.set_vibrance(val, primary_only=primary_only)

    def toggle_murqin(self):
        """Toggles the Murqin Mode setting."""
        state = bool(self.chk_murqin.get())
        self.cfg.settings["murqin_mode"] = state
        self.cfg.save()
        self.murqin_mode = state


    def toggle_startup(self):
        """
        Handles the Windows Startup switch logic, including the optional
        'start minimized' argument.
        """
        state = bool(self.chk_startup.get())
        
        if state:
            start_minimized = bool(self.chk_tray.get())
            path = f'"{self.mgr.target_path}"'
            if start_minimized:
                path += " --minimized"
            self.mgr.set_startup_value(path)
        else:
            self.mgr.set_startup(False)

        self.cfg.settings.update({"startup": state})
        self.cfg.save()

    def save_settings(self):
        """Saves configuration settings related to the Settings tab."""
        self.cfg.settings["start_in_tray"] = bool(self.chk_tray.get())
        self.cfg.settings["single_monitor"] = bool(self.chk_single.get())
        self.cfg.save()

        # Update startup path if startup is enabled and minimized setting changed
        if bool(self.chk_startup.get()):
            minimized = bool(self.chk_tray.get())
            path = f'"{self.mgr.target_path}"'
            if minimized:
                path += " --minimized"
            self.mgr.set_startup_value(path)

    def add_game(self):
        """Adds a process executable name to the tracked games list."""
        game_name = self.entry_game.get().lower().strip()
        if game_name and game_name not in self.cfg.games:
            self.cfg.games.append(game_name)
            self.cfg.save()
            self.update_game_list()
            self.entry_game.delete(0, "end")

    def remove_game(self, game_name: str):
        """Removes a process executable name from the tracked games list."""
        if game_name in self.cfg.games:
            self.cfg.games.remove(game_name)
            self.cfg.save()
            self.update_game_list()

    def update_game_list(self):
        """Clears and repopulates the scrollable frame with the current list of games."""
        # Clear existing widgets
        for w in self.scroll_list.winfo_children():
            w.destroy()
        
        # Create a row for each game
        for g in self.cfg.games:
            r = ctk.CTkFrame(self.scroll_list, fg_color="transparent", height=40)
            r.pack(fill="x", pady=2)
            ctk.CTkLabel(r, text=g, font=FONT_BODY, text_color=THEME["TEXT_PRI"]).pack(side="left", padx=10)
            ctk.CTkButton(
                r, text="Delete", width=50, height=25,
                fg_color="transparent", border_width=1,
                border_color=THEME["BORDER"], text_color=THEME["TEXT_SEC"],
                hover_color=THEME["CRITICAL"],
                command=lambda n=g: self.remove_game(n)
            ).pack(side="right", padx=10)

    def scan_process(self):
        """Opens a new top-level window for scanning and selecting running processes."""
        top = ctk.CTkToplevel(self)
        top.title(f"{APP_NAME} - Scanner")
        top.geometry("400x500")
        top.configure(fg_color=THEME["BG"])
        
        # Set icon for Toplevel
        if self.icon_path and os.path.exists(self.icon_path):
            # Must use after() to ensure the window is mapped before setting the icon
            top.after(200, lambda: top.iconbitmap(self.icon_path))

        # Header
        head = ctk.CTkFrame(top, fg_color="transparent")
        head.pack(fill="x", padx=20, pady=(20, 10))
        ctk.CTkLabel(head, text=APP_NAME.upper(), font=FONT_HEADER, text_color=THEME["ACCENT"]).pack(side="left", padx=5, pady=(0, 5))
        ctk.CTkLabel(head, text="PROCESS SCANNER", font=FONT_SMALL, text_color=THEME["BORDER"]).pack(side="left", padx=5, pady=(5, 0))

        # Search Input
        f = ctk.CTkFrame(top, fg_color=THEME["SURFACE"])
        f.pack(fill="x", padx=15, pady=10)
        e = ctk.CTkEntry(f, placeholder_text="Search processes...", border_width=0, fg_color="#2B2B2B", text_color=THEME["TEXT_PRI"])
        e.pack(fill="x", padx=10, pady=10)

        # Scrollable List
        s = ctk.CTkScrollableFrame(top, fg_color="transparent")
        s.pack(fill="both", expand=True, padx=15, pady=10)

        def sel(process_name: str):
            """Callback to select a process, populate the entry, and add it to the list."""
            self.entry_game.delete(0, "end")
            self.entry_game.insert(0, process_name)
            self.add_game()
            top.destroy()

        def load(filter_txt: str = ""):
            """Loads and filters the list of running processes."""
            for w in s.winfo_children():
                w.destroy()
            # Fetch unique process names and sort them
            procs = sorted(list(set([
                p.info['name'].lower()
                for p in psutil.process_iter(['name']) if p.info['name']
            ])))
            # Display filtered processes
            for p in procs:
                if filter_txt.lower() in p:
                    ctk.CTkButton(
                        s, text=p, anchor="w", fg_color="transparent",
                        text_color=THEME["TEXT_SEC"], hover_color=THEME["HOVER"],
                        command=lambda n=p: sel(n)
                    ).pack(fill="x")

        # Bind search input to the load function
        e.bind("<KeyRelease>", lambda ev: load(e.get()))
        # Initial load
        load()

    # ==========================================================
    # SYSTEM TRAY INTEGRATION
    # ==========================================================

    # --- pystray Callbacks ---

    def show_safe(self, i=None, it=None):
        """Thread-safe method to show the main window."""
        self.after(0, self._show)

    def _show(self):
        """Shows and focuses the main window."""
        self.deiconify() # Restore window if hidden
        self.lift()      # Bring to front
        self.focus_force() # Focus the window

    def quit_safe(self, i=None, it=None):
        """Thread-safe method to safely exit the application."""
        self.after(0, self._quit)

    def _quit(self):
        """Performs cleanup and shuts down the application."""
        if self.tray_icon:
            self.tray_icon.stop() # Stop the pystray thread
        self.safety.execute() # Execute final safety protocol (e.g., reset vibrance)
        self.destroy() # Destroy the main window
        sys.exit() # Exit the process

    def on_minimize(self, event):
        """Event handler for when the window is minimized (iconic state)."""
        # <Unmap> is triggered when window is minimized or hidden
        if self.state() == 'iconic':
            self.withdraw() # Hide the window when minimized to system tray

    def init_tray(self):
        """Initializes and starts the system tray icon in a new thread."""
        def loop():
            try:
                if not self.icon_path:
                    return

                # Define the tray icon menu
                menu = (
                    pystray.MenuItem('Show', self.show_safe, default=True),
                    pystray.MenuItem('Quit', self.quit_safe)
                )
                # Initialize and run the icon
                self.tray_icon = pystray.Icon(
                    APP_NAME,
                    Image.open(self.icon_path), # Use the generated icon file
                    APP_NAME,
                    menu
                )
                self.tray_icon.run()
            except Exception:
                # Handle pystray initialization errors gracefully
                pass

        # Run pystray in a dedicated daemon thread
        threading.Thread(target=loop, daemon=True).start()