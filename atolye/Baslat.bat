@echo off
cd /d "%~dp0"
if not exist ayarlar.json copy ayarlar.example.json ayarlar.json >nul
start "" pythonw atolye_app.py
