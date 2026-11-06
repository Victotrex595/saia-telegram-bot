@echo off
chcp 65001 > nul
title Bot Interactivo SAIA - Telegram
cls
echo ========================================================
echo         BOT INTERACTIVO DE SAIA PARA TELEGRAM
echo ========================================================
echo.
echo Escuchando comandos (/materia, /calificaciones, /pendientes...)
echo Presiona Ctrl+C en esta ventana para detener el bot.
echo.
python "%~dp0interactive_bot.py"
pause
