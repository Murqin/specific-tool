# modules/ui.py
import customtkinter as ctk
import threading
import os
import sys
import tempfile
import pystray
import psutil
import queue
from PIL import Image, ImageDraw
from .constants import *
from .core import AppManager, ConfigManager, AutomationEngine, SafetyProtocol
from .hardware import VXEMouseBackend, NvidiaService, WindowsMouseService

def setup_custom_icon(window_instance):
    """
    Generates and sets a minimalist Kaomoji icon for the application window.
    
    Args:
        window_instance: The tkinter/customtkinter window instance.
        
    Returns:
        str: Path to the generated icon file, or None if failed.
    """
    try:
        size = 64
        img = Image.new('RGB', (size, size), color=(18, 18, 18))
        draw = ImageDraw.Draw(img)
        white = (224, 224, 224)
        draw.rectangle([10, 28, 25, 32], fill=white)
        draw.rectangle([39, 28, 54, 32], fill=white)
        draw.rectangle([18, 48, 46, 52], fill=white)
        path = os.path.join(tempfile.gettempdir(), "specific_kaomoji.ico")
        img.save(path, format='ICO', sizes=[(64, 64)])
        window_instance.iconbitmap(path)
        return path
    except: return None

class App(ctk.CTk):
    """
    Main Application Class.
    
    Inherits from customtkinter.CTk. Handles the UI layout, user interactions,
    and coordinates the backend services (Hardware, Automation).
    """
    def __init__(self):
        super().__init__()
        
        # --- Managers & Hardware ---
        self.cfg = ConfigManager()
        self.mgr = AppManager()
        self.mgr.ensure_installed()
        
        self.hw_mouse = VXEMouseBackend()
        self.hw_mouse_connected = self.hw_mouse.connect()
        self.hw_gpu = NvidiaService()
        self.hw_os = WindowsMouseService()
        
        # --- App State ---
        self.icon_path = setup_custom_icon(self)
        self.tray_icon = None
        self.running = False
        self.murqin_mode = False
        
        # --- Thread Safety ---
        # Queue to handle UI updates from background threads (AutomationEngine).
        # Tkinter is NOT thread-safe, so all UI updates must happen in the main thread.
        self.ui_queue = queue.Queue()
        
        # --- Core Logic ---
        self.safety = SafetyProtocol(self.hw_mouse, self.hw_gpu, self.hw_os, self.get_ui_state)
        self.engine = AutomationEngine(self.cfg, self.hw_mouse, self.hw_gpu, self.hw_os, self.get_ui_state)

        # --- Window Init ---
        self.setup_window()
        self.setup_layout()
        
        # --- System Integration ---
        self.init_tray()
        self.protocol("WM_DELETE_WINDOW", self.quit_safe)
        self.bind("<Unmap>", self.on_minimize)
        
        self.process_ui_queue()
        
        if "--minimized" in sys.argv: self.withdraw()
        threading.Thread(target=self.engine.loop, daemon=True).start()

    # ==========================
    # UI STATE PROVIDER
    # ==========================
    def process_ui_queue(self):
        """
        Periodically checks the UI queue for pending updates and executes them
        in the main thread. This ensures thread safety.
        """
        try:
            while True:
                func = self.ui_queue.get_nowait()
                func()
        except queue.Empty:
            pass
        # Schedule the next check in 100ms
        self.after(100, self.process_ui_queue)

    def enqueue_ui_update(self, func):
        """
        Adds a function to the UI queue to be executed in the main thread.
        
        Args:
            func: A callable (function or lambda) containing the UI update code.
        """
        self.ui_queue.put(func)

    def get_ui_state(self, key):
        """
        Callback method passed to AutomationEngine to retrieve current UI values safely.
        
        Args:
            key (str): The identifier for the requested state (e.g., 'vib_desk').
            
        Returns:
            The value of the requested UI element, or a default value if failed.
        """
        try:
            if key == 'vib_desk': return int(self.slider_vib_desk.get())
            if key == 'vib_game': return int(self.slider_vib_game.get())
            if key == 'murqin': return bool(self.chk_murqin.get())
            if key == 'status': return self.update_status_ui
        except: return 50 if 'vib' in key else None

    def update_status_ui(self, text, is_game):
        def _update():
            color = THEME["SUCCESS_TEXT"] if is_game else THEME["TEXT_SEC"]
            self.lbl_status_dot.configure(text_color=THEME["ACCENT"] if is_game else THEME["TEXT_SEC"])
            self.lbl_status_text.configure(text=text, text_color=THEME["TEXT_PRI"] if is_game else THEME["TEXT_SEC"])
        self.enqueue_ui_update(_update)

    # ==========================
    # LAYOUT CONSTRUCTION
    # ==========================
    def setup_window(self):
        self.title(APP_NAME)
        self.geometry("450x750")
        self.resizable(False, False)
        self.configure(fg_color=THEME["BG"])
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("dark-blue")

    def setup_layout(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # 1. HEADER
        self.header = ctk.CTkFrame(self, fg_color="transparent", height=60)
        self.header.grid(row=0, column=0, sticky="ew", padx=25, pady=(25, 10))
        
        ctk.CTkLabel(self.header, text="Specific Tool", font=FONT_HEADER, text_color=THEME["TEXT_PRI"]).pack(side="left")
        ctk.CTkLabel(self.header, text="v2.0", font=FONT_SMALL, text_color=THEME["TEXT_PRI"]).pack(side="left", padx=5, pady=(0,15))

        # 2. TABS
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

        # 3. CONTENT
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=2, column=0, sticky="nsew", padx=25, pady=(0, 25))
        self.content.grid_columnconfigure(0, weight=1); self.content.grid_rowconfigure(0, weight=1)

        self.views = {}
        for v in ["Dashboard", "Profiles", "Settings"]:
            f = ctk.CTkFrame(self.content, fg_color="transparent")
            f.grid(row=0, column=0, sticky="nsew")
            self.views[v] = f
            getattr(self, f"build_{v.lower()}")(f)
        
        self.switch_tab("Dashboard")

    # --- Component Builders ---
    def create_status_row(self, parent, label, status, active):
        """Creates a full-width status row with visible border."""
        # Container
        row = ctk.CTkFrame(parent, fg_color="transparent", border_width=1, border_color=THEME["BORDER"], corner_radius=8)
        row.pack(fill="x", pady=(0, 10)) # Alt alta boşluklu

        # Inner Layout
        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(fill="x", padx=15, pady=12)

        # Label (Left) e.g. "MOUSE"
        ctk.CTkLabel(inner, text=label, font=("Arial", 11, "bold"), text_color=THEME["TEXT_SEC"]).pack(side="left")

        # Dot (Right)
        col = THEME["SUCCESS"] if active else THEME["CRITICAL"] # Green or Red
        c = ctk.CTkCanvas(inner, width=8, height=8, bg=THEME["BG"], highlightthickness=0)
        c.pack(side="right", padx=(10, 0))
        c.create_oval(1, 1, 7, 7, fill=col, outline="")

        # Status Text (Right of Dot) e.g. "ONLINE"
        stat_txt = status.upper()
        ctk.CTkLabel(inner, text=stat_txt, font=("Arial", 11, "bold"), text_color=THEME["TEXT_PRI"]).pack(side="right")

    def switch_tab(self, name):
        self.views[name].tkraise()
        for n, btn in self.tab_btns.items():
            btn.configure(text_color=THEME["TEXT_PRI"] if n == name else THEME["TEXT_SEC"])

    def create_vercel_switch(self, parent, text, subtext, cmd=None):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        lbl_f = ctk.CTkFrame(f, fg_color="transparent")
        lbl_f.pack(side="left")
        ctk.CTkLabel(lbl_f, text=text, font=FONT_BODY, text_color=THEME["TEXT_PRI"]).pack(anchor="w")
        ctk.CTkLabel(lbl_f, text=subtext, font=FONT_SMALL, text_color=THEME["TEXT_SEC"]).pack(anchor="w")
        s = ctk.CTkSwitch(f, text="", progress_color=THEME["ACCENT"], fg_color=THEME["BORDER"], 
                          button_color="#555555", button_hover_color="#777777", width=40, command=cmd)
        s.pack(side="right")
        return s, f

    # --- View Content ---
    def build_dashboard(self, p):
        # 1. Status Card
        card = ctk.CTkFrame(p, fg_color="transparent", border_width=1, border_color=THEME["BORDER"], corner_radius=8)
        card.pack(fill="x", pady=(0, 15))
        
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=20)
        
        is_running = self.engine.running
        
        self.lbl_status_dot = ctk.CTkLabel(top, text="●", font=("Arial", 12), text_color=THEME["ACCENT"] if is_running else THEME["TEXT_SEC"])
        self.lbl_status_dot.pack(side="left", padx=(0, 5))
        self.lbl_status_text = ctk.CTkLabel(top, text="Monitoring Process..." if is_running else "System Idle", font=FONT_SUBHEAD, text_color=THEME["TEXT_SEC"])
        self.lbl_status_text.pack(side="left")

        self.btn_toggle = ctk.CTkButton(
            card, 
            text="STOP AUTOMATION" if is_running else "Start Automation", 
            font=FONT_SUBHEAD, height=45,
            fg_color=THEME["CRITICAL"] if is_running else THEME["ACCENT"], 
            text_color="#FFFFFF" if is_running else "#000000", 
            hover_color="#CCCCCC", corner_radius=6,
            command=self.toggle_engine
        )
        self.btn_toggle.pack(fill="x", padx=20, pady=(0, 20))

        # 2. Config Card
        conf_card = ctk.CTkFrame(p, fg_color="transparent", border_width=1, border_color=THEME["BORDER"], corner_radius=8)
        conf_card.pack(fill="x", pady=(0, 20))
        self.chk_murqin, f = self.create_vercel_switch(conf_card, "Murqin Mode", "Input Normalization", self.toggle_murqin)
        f.pack(fill="x", padx=20, pady=20)

        # 3. Hardware Status Area (Visible Rows)
        footer_label = ctk.CTkLabel(p, text="HARDWARE STATUS", font=("Arial", 10, "bold"), text_color=THEME["BORDER"])
        footer_label.pack(fill="x", anchor="w", padx=5, pady=(10, 10))

        # Container for rows
        status_container = ctk.CTkFrame(p, fg_color="transparent")
        status_container.pack(fill="x")

        m_status = "ONLINE" if self.hw_mouse_connected else "OFFLINE"
        g_status = "READY" if self.hw_gpu.available else "NOT FOUND"
        
        self.create_status_row(status_container, "MOUSE", m_status, self.hw_mouse_connected)
        self.create_status_row(status_container, "NVIDIA", g_status, self.hw_gpu.available)

    def build_profiles(self, p):
        # Unified Input Bar
        inp_card = ctk.CTkFrame(p, fg_color="transparent", border_width=1, border_color=THEME["BORDER"], corner_radius=8)
        inp_card.pack(fill="x", pady=(0, 15))
        
        ctk.CTkButton(inp_card, text="+", width=40, height=32, fg_color=THEME["ACCENT"], text_color="#000000", hover_color="#CCCCCC", corner_radius=6, command=self.add_game).pack(side="right", padx=(5, 8), pady=4)
        ctk.CTkButton(inp_card, text="Scan", width=40, height=32, fg_color=THEME["ACCENT"], text_color="#000000", hover_color="#CCCCCC", corner_radius=6, border_width=0, command=self.scan_process).pack(side="right", padx=(0, 5))

        self.entry_game = ctk.CTkEntry(inp_card, placeholder_text="executable_name.exe", border_width=0, fg_color="transparent", text_color=THEME["TEXT_PRI"], placeholder_text_color=THEME["TEXT_SEC"], height=32, font=FONT_BODY)
        self.entry_game.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=0)

        # List
        self.scroll_list = ctk.CTkScrollableFrame(p, fg_color="transparent", border_width=1, border_color=THEME["BORDER"], corner_radius=8)
        self.scroll_list.pack(fill="both", expand=True, pady=(0, 15))
        self.update_game_list()

        # Slider
        vib_card = ctk.CTkFrame(p, fg_color="transparent", border_width=1, border_color=THEME["BORDER"], corner_radius=8)
        vib_card.pack(fill="x")
        top = ctk.CTkFrame(vib_card, fg_color="transparent")
        top.pack(fill="x", padx=15, pady=(15, 5))
        ctk.CTkLabel(top, text="In-Game Vibrance", font=FONT_BODY, text_color=THEME["TEXT_PRI"]).pack(side="left")
        self.lbl_vib_game = ctk.CTkLabel(top, text="100%", font=FONT_BODY, text_color=THEME["TEXT_SEC"])
        self.lbl_vib_game.pack(side="right")
        self.slider_vib_game = ctk.CTkSlider(vib_card, from_=0, to=100, number_of_steps=100, button_color=THEME["ACCENT"], progress_color=THEME["ACCENT"], button_hover_color="#FFFFFF", command=lambda v: self.on_vib_change(v, True))
        self.slider_vib_game.set(100)
        self.slider_vib_game.pack(fill="x", padx=15, pady=(0, 15))

    def build_settings(self, p):
        card = ctk.CTkFrame(p, fg_color="transparent", border_width=1, border_color=THEME["BORDER"], corner_radius=8)
        card.pack(fill="x", pady=(0, 15))

        self.chk_startup, f1 = self.create_vercel_switch(card, "Windows Startup", "Launch on boot", self.toggle_startup)
        f1.pack(fill="x", padx=20, pady=(20, 10))
        if self.mgr.is_startup_enabled(): self.chk_startup.select()

        self.chk_tray, f2 = self.create_vercel_switch(card, "Start Minimized", "Boot to tray icon", self.save_settings)
        f2.pack(fill="x", padx=20, pady=10)
        if self.cfg.settings.get("start_in_tray", True): self.chk_tray.select()

        self.chk_single, f3 = self.create_vercel_switch(card, "Single Monitor", "Primary display only", self.save_settings)
        f3.pack(fill="x", padx=20, pady=(10, 20))
        if self.cfg.settings.get("single_monitor", True): self.chk_single.select()

        d_card = ctk.CTkFrame(p, fg_color="transparent", border_width=1, border_color=THEME["BORDER"], corner_radius=8)
        d_card.pack(fill="x", pady=(0, 15))
        
        top = ctk.CTkFrame(d_card, fg_color="transparent")
        top.pack(fill="x", padx=15, pady=(15, 5))
        ctk.CTkLabel(top, text="Desktop Vibrance", font=FONT_BODY, text_color=THEME["TEXT_PRI"]).pack(side="left")
        self.lbl_vib_desk = ctk.CTkLabel(top, text="50%", font=FONT_BODY, text_color=THEME["TEXT_SEC"])
        self.lbl_vib_desk.pack(side="right")
        
        self.slider_vib_desk = ctk.CTkSlider(d_card, from_=0, to=100, number_of_steps=100, button_color=THEME["ACCENT"], progress_color=THEME["ACCENT"], button_hover_color="#FFFFFF", command=lambda v: self.on_vib_change(v, False))
        self.slider_vib_desk.set(50)
        self.slider_vib_desk.pack(fill="x", padx=15, pady=(0, 15))

        ctk.CTkButton(p, text="Open Config Folder", fg_color="transparent", text_color=THEME["TEXT_SEC"], font=FONT_SMALL, hover_color=THEME["HOVER"], command=lambda: os.startfile(self.mgr.appdata_dir)).pack()

    # --- Actions ---
    def toggle_engine(self):
        self.engine.running = not self.engine.running
        if self.engine.running:
            self.btn_toggle.configure(text="STOP AUTOMATION", fg_color=THEME["CRITICAL"], text_color="#FFFFFF")
            self.lbl_status_text.configure(text="Monitoring Process...")
            self.lbl_status_dot.configure(text_color=THEME["ACCENT"])
        else:
            self.btn_toggle.configure(text="START AUTOMATION", fg_color=THEME["ACCENT"], text_color="#000000")
            self.safety.execute()
            self.lbl_status_text.configure(text="System Idle")
            self.lbl_status_dot.configure(text_color=THEME["TEXT_SEC"])
            self.engine.current_state = "unknown"

    def on_vib_change(self, value, is_game):
        val = int(value)
        lbl = self.lbl_vib_game if is_game else self.lbl_vib_desk
        lbl.configure(text=f"{val}%")
        
        mode = "game" if is_game else "desktop"
        if self.engine.running and self.engine.current_state == mode:
            try: p = bool(self.chk_single.get())
            except: p = False
            self.hw_gpu.set_vibrance(val, primary_only=p)

    def toggle_murqin(self): self.murqin_mode = bool(self.chk_murqin.get())
    def toggle_startup(self): self.mgr.set_startup(bool(self.chk_startup.get()))
    
    def save_settings(self):
        try: self.cfg.settings["start_in_tray"] = bool(self.chk_tray.get())
        except: pass
        try: self.cfg.settings["single_monitor"] = bool(self.chk_single.get())
        except: pass
        self.cfg.save()

    def add_game(self):
        g = self.entry_game.get().lower().strip()
        if g and g not in self.cfg.games:
            self.cfg.games.append(g); self.cfg.save(); self.update_game_list(); self.entry_game.delete(0, "end")

    def remove_game(self, g):
        if g in self.cfg.games:
            self.cfg.games.remove(g); self.cfg.save(); self.update_game_list()

    def update_game_list(self):
        for w in self.scroll_list.winfo_children(): w.destroy()
        for g in self.cfg.games:
            r = ctk.CTkFrame(self.scroll_list, fg_color="transparent", height=40)
            r.pack(fill="x", pady=2)
            ctk.CTkLabel(r, text=g, font=FONT_BODY, text_color=THEME["TEXT_PRI"]).pack(side="left", padx=10)
            ctk.CTkButton(r, text="Delete", width=50, height=25, fg_color="transparent", border_width=1, border_color=THEME["BORDER"], text_color=THEME["TEXT_SEC"], hover_color=THEME["CRITICAL"], command=lambda n=g: self.remove_game(n)).pack(side="right", padx=10)

    def scan_process(self):
        top = ctk.CTkToplevel(self)
        top.title("Specific Tool - Scanner")
        top.geometry("400x500")
        top.configure(fg_color=THEME["BG"])
        if self.icon_path and os.path.exists(self.icon_path):
            top.after(200, lambda: top.iconbitmap(self.icon_path))
        
        head = ctk.CTkFrame(top, fg_color="transparent")
        head.pack(fill="x", padx=20, pady=(20, 10))
        ctk.CTkLabel(head, text="SPECIFIC TOOL", font=FONT_HEADER, text_color=THEME["ACCENT"]).pack(side="left", padx=5, pady=(0,5))
        ctk.CTkLabel(head, text="PROCESS SCANNER", font=FONT_SMALL, text_color=THEME["BORDER"]).pack(side="left", padx=5, pady=(5,0))

        f = ctk.CTkFrame(top, fg_color=THEME["SURFACE"])
        f.pack(fill="x", padx=15, pady=10)
        e = ctk.CTkEntry(f, placeholder_text="Search processes...", border_width=0, fg_color="#2B2B2B", text_color=THEME["TEXT_PRI"])
        e.pack(fill="x", padx=10, pady=10)
        
        s = ctk.CTkScrollableFrame(top, fg_color="transparent")
        s.pack(fill="both", expand=True, padx=15, pady=10)
        
        def load(filter_txt=""):
            for w in s.winfo_children(): w.destroy()
            procs = sorted(list(set([p.info['name'].lower() for p in psutil.process_iter(['name']) if p.info['name']])))
            for p in procs:
                if filter_txt.lower() in p: 
                    ctk.CTkButton(s, text=p, anchor="w", fg_color="transparent", text_color=THEME["TEXT_SEC"], hover_color=THEME["HOVER"], command=lambda n=p: sel(n)).pack(fill="x")
        def sel(n): 
            self.entry_game.delete(0, "end")
            self.entry_game.insert(0, n)
            self.add_game()
            top.destroy()
        
        e.bind("<KeyRelease>", lambda ev: load(e.get()))
        load()

    # --- Tray Helpers ---
    def show_safe(self, i=None, it=None): self.after(0, self._show)
    def _show(self): self.deiconify(); self.lift(); self.focus_force()
    def quit_safe(self, i=None, it=None): self.after(0, self._quit)
    def _quit(self):
        if self.tray_icon: self.tray_icon.stop()
        self.safety.execute()
        self.destroy()
        sys.exit()
    def on_minimize(self, e):
        if self.state() == 'iconic': self.withdraw()
    def init_tray(self):
        def loop():
            try:
                if not self.icon_path: return
                menu = (pystray.MenuItem('Show', self.show_safe, default=True), pystray.MenuItem('Quit', self.quit_safe))
                self.tray_icon = pystray.Icon(APP_NAME, Image.open(self.icon_path), APP_NAME, menu)
                self.tray_icon.run()
            except: pass
        threading.Thread(target=loop, daemon=True).start()