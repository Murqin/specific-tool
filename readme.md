# Critical Note ⚠️

This tool currently overwrites your DPI profiles. I may fix it in the future if I get around to it.

# Specific Tool 🎯

Specific Tool is a high-performance input optimization and peripheral management tool designed for competitive gaming. It automates DPI switching, polling rate adjustments, and digital vibrance settings based on the active process.

## 🚀 Key Features

- **Murqin Mode (Input Normalization):** Implements a mathematical transfer function to allow **High Hardware DPI (e.g., 1600)** paired with **Low Software Sensitivity**. This reduces sensor noise and jitter while maintaining the user's preferred cursor speed (e.g., 800 eDPI feel).

- **Bus Contention Safety:** Features a robust packet queue system with debounce logic to prevent USB HID write collisions during rapid state changes (Alt-Tab).

- **Emergency Exit Protocol:** Global `atexit` hooks ensure hardware (Mouse MCU) and OS settings (Windows Pointer Speed) always revert to safe defaults upon crash or closure.

- **Process-Aware Automation:** Automatically detects games to apply:
  - 1600 DPI / 8000Hz Polling Rate (Game Mode)
  - 100% Digital Vibrance (Nvidia)
  - Reverts to 800 DPI / 1000Hz / 50% Vibrance on Desktop.

## 🛠️ Technology Stack

- **Python 3.9**
- **Win32 API (ctypes, pywin32):** Direct Kernel-level mouse sensitivity manipulation.
- **HIDAPI:** Raw USB communication for mouse MCU configuration.
- **CustomTkinter:** Modern, high-DPI aware UI.

## ⚖️ Disclaimer

This project is based on **reverse engineering** of the original hardware protocols and is not official software distributed by ATK/VXE.

⚠️ **Critical Warning:** The manufacturer (ATK/VXE) may alter the USB communication protocol and Hex command sequences with a future **Firmware Update**.

* Using this software after a firmware update may result in unexpected hardware behavior due to protocol mismatches.
* The user assumes full responsibility for any potential damage (including device bricking, malfunction, or data loss).

The developer accepts no liability for any technical issues arising from the use of this tool. **Use at your own risk.**

## 📦 Installation
1. git clone https://github.com/Murqin/specific-tool.git
2. cd specific-tool
3. python -m pip install -r requirements.txt
4. python -m PyInstaller --noconsole --onefile --name="Specific Tool" --clean --uac-admin --icon="assets/specific-tool.ico" main.py

## 📦 Alternative Installation (I recommend this.)
1. git clone https://github.com/Murqin/specific-tool.git
2. cd specific-tool
3. py -3.9 -m venv env
4. env\Scripts\Activate.ps1
5. python -m pip install -r requirements.txt
6. .\build.bat



## 🧪 For Developers: Porting to Other Mice

Currently, the `MouseBackend` class is hardcoded with **VXE MAD R** specific USB HID reports. However, the architecture is modular and can be adapted for any mouse that accepts HID commands.

If you want to port this tool to your own mouse (e.g., Logitech, Razer, Lamzu), follow these steps:

1. **Sniff USB Traffic:** Use tools like **Wireshark** (with USBPcap) to capture packets while changing DPI and Polling Rate in your mouse's official software.
2. **Analyze Hex Dumps:** Identify the specific `SET_REPORT` sequences sent to the device during these changes.
3. **Update Constants:** Modify the following variables in `modules/constants.py`:

```python
# In class MouseBackend:
self.VENDOR_ID = 0xYOUR_VID
self.PRODUCT_ID = 0xYOUR_PID

# Update Command Arrays (Example)
CMD_HZ_8000 = [0xDE, 0xAD, 0xBE, 0xEF, ...] # Your 8KHz Hex Sequence
SEQ_DPI_1600 = [[0x01, ...], [0x02, ...]]    # Your DPI Switch Sequence
````

4. **Interface Selection (CRITICAL) ⚠️**

Modern gaming mice are "Composite Devices" that expose multiple **HID Interfaces** when connected. You must target the specific interface used for configuration (Vendor Specific), not the standard mouse input interface.

* **Interface 0:** Standard Mouse Input (Movement/Clicks) - *Do not touch.*
* **Interface 1 or 2:** Keyboard/Media Keys or **Configuration (Vendor Specific)** <--- **Target**

In `modules/hardware.py` (Line ~57), the code filters for the specific configuration interface. **You must modify this condition to match your mouse's HID path:**

```python
            for d in hid.enumerate(self.VENDOR_ID, self.PRODUCT_ID):
                path = d['path'].decode('utf-8','ignore').lower()
                if "mi_01" in path and "col05" in path:  # Channel & interface
                    self.device = hid.device()
                    self.device.open_path(d['path'])
                    self.device.set_nonblocking(1)
                    return True
```
