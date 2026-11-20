@echo off
chcp 65001 >nul
echo === TickerBar 打包 ===
pip install -r requirements.txt
pip install pyinstaller

rem 已裁剪未使用的标准库（见 TickerBar.spec 的 excludes），产物约 14MB
python -m PyInstaller TickerBar.spec --noconfirm --clean

echo.
echo 完成： dist\TickerBar.exe
pause
