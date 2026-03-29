@echo off
echo ============================================
echo   MT Tennis Predictor
echo ============================================

cd /d "%~dp0"

:: Sprawdz czy virtualenv istnieje
if not exist ".venv\Scripts\activate.bat" (
    echo Tworzenie virtualenv...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo Instalacja zaleznosci...
pip install -r requirements.txt -q

echo.
echo Uruchamianie serwera na http://localhost:8000
echo Pierwsze uruchomienie pobierze dane ATP (chwile poczekaj)
echo Nacisnij Ctrl+C aby zatrzymac
echo.

python main.py
pause
