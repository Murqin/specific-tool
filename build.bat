@echo off
echo Building Specific Tool...
call env\Scripts\activate.bat
echo.
python -m PyInstaller --noconsole --onefile --name="Specific Tool" --clean --uac-admin --icon="assets\specific-tool.ico" main.py
echo Build Complete.
pause