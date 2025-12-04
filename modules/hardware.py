# modules/hardware.py
import ctypes
import hid
import os
import struct
import time
import logging
from abc import ABC, abstractmethod
from typing import List, Optional
from .constants import CMD_HZ_8000, CMD_HZ_1000, SEQ_DPI_1600, SEQ_DPI_800

logger = logging.getLogger(__name__)

# --- Abstract Interfaces ---
class IMouseBackend(ABC):
    """Abstract base class for Mouse Hardware Backends."""
    @abstractmethod
    def set_game_mode(self): pass
    @abstractmethod
    def set_desktop_mode(self): pass
    @abstractmethod
    def connect(self) -> bool: pass

class IGPUBackend(ABC):
    """Abstract base class for GPU Hardware Backends."""
    @abstractmethod
    def set_vibrance(self, level: int, primary_only: bool): pass
    @property
    @abstractmethod
    def available(self) -> bool: pass

class IOSMouseService(ABC):
    """Abstract base class for OS-level Mouse Settings (Windows Pointer Speed)."""
    @abstractmethod
    def set_speed(self, index: int): pass
    @abstractmethod
    def reset(self): pass
    @abstractmethod
    def optimize(self, base: int, target: int): pass

# --- Implementations ---
class VXEMouseBackend(IMouseBackend):
    """
    Backend for VXE R1 Pro / VGN Dragonfly F1 Series Mice.
    
    Uses HID (Human Interface Device) commands to communicate directly with the mouse receiver.
    The commands (CMD_HZ_*, SEQ_DPI_*) are reverse-engineered byte sequences that trigger
    on-board profile switching.
    """
    VENDOR_ID, PRODUCT_ID = 0x373B, 0x1040
    def __init__(self): self.device = None
    
    def connect(self) -> bool:
        try:
            for d in hid.enumerate(self.VENDOR_ID, self.PRODUCT_ID):
                path = d['path'].decode('utf-8','ignore').lower()
                if "mi_01" in path and "col05" in path:  # Channel & interface
                    self.device = hid.device()
                    self.device.open_path(d['path'])
                    self.device.set_nonblocking(1)
                    return True
            return False
        except Exception as e:
            logger.error(f"VXE Mouse connect error: {e}")
            return False

    def _send(self, data):
        if self.device:
            try: self.device.write(data)
            except Exception as e: logger.error(f"VXE Mouse send error: {e}")

    def set_game_mode(self):
        if not self.device: return
        for p in SEQ_DPI_1600: self._send(p); time.sleep(0.02)
        time.sleep(0.25)
        self._send(CMD_HZ_2000)

    def set_desktop_mode(self):
        if not self.device: return
        for p in SEQ_DPI_800: self._send(p); time.sleep(0.02)
        time.sleep(0.25)
        self._send(CMD_HZ_1000)

class NvidiaService(IGPUBackend):
    """
    Backend for Nvidia GPUs using undocumented NVAPI.
    
    Since Nvidia does not provide an official Python library for Digital Vibrance control,
    this class uses `ctypes` to load `nvapi.dll` and calls functions via their internal IDs.
    
    Magic Numbers (Function IDs):
    - 0x0150E828: nvapi_Initialize (Initializes the API)
    - 0x9ABDD40D: nvapi_EnumDisplayHandle (Enumerates active displays)
    - 0x172409B4: nvapi_SetDVCLevel (Sets Digital Vibrance Control level)
    """
    def __init__(self):
        self._nvapi, self._handles, self._is_avail = None, [], False
        self._init_api()

    def _init_api(self):
        try:
            sys_root = os.environ.get('SystemRoot', 'C:\\Windows')
            bits = struct.calcsize("P") * 8
            dll = 'nvapi.dll' if bits == 32 else 'nvapi64.dll'
            path = os.path.join(sys_root, 'System32', dll)
            if os.path.exists(path):
                self._nvapi = ctypes.windll.LoadLibrary(path)
                ftype = ctypes.WINFUNCTYPE if bits == 32 else ctypes.CFUNCTYPE
                q_int = self._nvapi.nvapi_QueryInterface
                q_int.restype = ctypes.c_void_p
                q_int.argtypes = [ctypes.c_int]
                get = lambda id, args: ftype(ctypes.c_int, *args)(q_int(id))
                
                if get(0x0150E828, [])() == 0: # Init
                    enum = get(0x9ABDD40D, [ctypes.c_int, ctypes.POINTER(ctypes.c_int)])
                    self._set_dvc = get(0x172409B4, [ctypes.c_int, ctypes.c_int, ctypes.c_int])
                    for i in range(10):
                        h = ctypes.c_int(0)
                        if enum(i, ctypes.byref(h)) == 0: self._handles.append(h)
                        else: break
                    self._is_avail = True
        except Exception as e:
            logger.warning(f"Nvidia Service init failed: {e}")

    @property
    def available(self) -> bool: return self._is_avail

    def set_vibrance(self, level: int, primary_only: bool):
        if not self.available: return
        if level is None: level = 50
        try:
            val = max(-63, min(63, int((level - 50) * 1.26)))
            if primary_only and self._handles: self._set_dvc(self._handles[0], 0, val)
            else:
                for h in self._handles: self._set_dvc(h, 0, val)
        except Exception as e:
            logger.error(f"Failed to set vibrance: {e}")

class WindowsMouseService(IOSMouseService):
    _MAP = {1:0.03125, 2:0.0625, 3:0.125, 4:0.25, 5:0.375, 6:0.5, 7:0.625, 8:0.75, 9:0.875, 10:1.0, 11:1.25, 12:1.5, 13:1.75, 14:2.0, 15:2.25, 16:2.5, 17:2.75, 18:3.0, 19:3.25, 20:3.5}
    def __init__(self):
        self._user32 = ctypes.windll.user32
        self._default = self._get_speed()
    def _get_speed(self) -> int:
        s = ctypes.c_int()
        self._user32.SystemParametersInfoW(0x0070, 0, ctypes.byref(s), 0)
        return s.value
    def set_speed(self, index: int):
        self._user32.SystemParametersInfoW(0x0071, 0, ctypes.c_void_p(max(1, min(20, int(index)))), 0x01 | 0x02)
    def reset(self): self.set_speed(self._default)
    def optimize(self, base, target):
        req = (base * self._MAP.get(10, 1.0)) / target
        self.set_speed(min(self._MAP.keys(), key=lambda k: abs(self._MAP[k] - req)))