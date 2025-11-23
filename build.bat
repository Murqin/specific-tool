@echo off
call .venv\Scripts\activate.bat
python -m PyInstaller --noconsole --onefile --name="Specific Tool" --clean --uac-admin --icon="assets/specific-tool.ico" main.py
echo Build Complete.
pause