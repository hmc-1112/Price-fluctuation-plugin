@echo off
chcp 65001 >nul
echo === TickerBar 打包 ===
pip install -r requirements.txt
pip install pyinstaller

set EX=--exclude-module unittest --exclude-module pydoc --exclude-module doctest ^
 --exclude-module distutils --exclude-module lib2to3 --exclude-module sqlite3 ^
 --exclude-module multiprocessing --exclude-module concurrent --exclude-module asyncio ^
 --exclude-module xmlrpc --exclude-module setuptools --exclude-module pkg_resources ^
 --exclude-module numpy --exclude-module pandas --exclude-module matplotlib ^
 --exclude-module PIL.ImageQt --exclude-module test

python -m PyInstaller --noconfirm --clean --onefile --noconsole --name TickerBar --icon app.ico %EX% tickerbar.py
echo.
echo 完成： dist\TickerBar.exe
pause
