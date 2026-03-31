@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -m pip install -r ..\app\requirements.txt
py crawler_tipcars.py --seeds seeds.txt --output-csv data\autos_raw.csv --output-json data\autos_raw.json --max-pages-per-seed 15
pause
