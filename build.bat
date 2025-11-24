@echo off
env\Scripts\python.exe -m PyInstaller --noconsole --onefile --name="Specific Tool" --clean --icon="assets/specific-tool.ico" main.py 
rem The reason I use it like this: .venv\Scripts\python.exe -m is because I'm a bit lazy and want to run the script and get a quick build.
echo Build Complete.
pause