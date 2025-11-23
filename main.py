"""
Specific Tool - Main Entry Point
================================

This is the entry point for the Specific Tool application.
It initializes the main UI application and starts the event loop.

Author: Icarus Murqin
License: MIT 
"""
from modules.ui import App

if __name__ == "__main__":
    app = App()
    app.mainloop()