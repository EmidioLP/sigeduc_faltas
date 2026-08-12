@echo off
REM Gera os executaveis em dist\ (requer: pip install -r requirements.txt pyinstaller)
setlocal
cd /d "%~dp0"

set COMUNS=--noconfirm --onefile --paths "%~dp0" --distpath "%~dp0dist" --workpath "%~dp0build" --specpath "%~dp0build" --exclude-module matplotlib --exclude-module pandas --exclude-module scipy --exclude-module numpy --exclude-module IPython --exclude-module notebook --exclude-module pytest

echo.
echo === Compilando "Mapa de Faltas.exe" (interface grafica) ===
python -m PyInstaller %COMUNS% --windowed --name "Mapa de Faltas" gui.py || goto :erro

echo.
echo === Compilando "mapa-faltas-cli.exe" (linha de comando) ===
python -m PyInstaller %COMUNS% --console --exclude-module tkinter --name "mapa-faltas-cli" main.py || goto :erro

echo.
echo Pronto. Executaveis em: %~dp0dist
goto :fim

:erro
echo.
echo FALHA na compilacao.
exit /b 1

:fim
endlocal
