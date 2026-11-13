@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Avito watch — вход
python avito_watch.py --login
pause
