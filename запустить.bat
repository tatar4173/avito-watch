@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Avito watch
python avito_watch.py --interval 45
pause
