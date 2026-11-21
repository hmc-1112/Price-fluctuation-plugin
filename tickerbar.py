# -*- coding: utf-8 -*-
"""
TickerBar - 任务栏行情条
================================
在 Windows 任务栏上显示 黄金现货(元/克) / 上证指数 / 深证成指，
贴任务栏自适应定位，收盘或断网自动变灰，悬停可看当日分时。

MIT License
"""
__version__ = "1.2.0"
import os
import re
import sys
import json
import time
import ctypes
import threading
import urllib.request
from ctypes import wintypes
from datetime import datetime, timedelta

import tkinter as tk
from PIL import Image, ImageDraw, ImageFont, ImageTk

# ---------------------------------------------------------------- 路径
FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    BASE_DIR = os.path.dirname(sys.executable)
    DATA_DIR = os.path.join(os.environ.get("APPDATA", BASE_DIR), "TickerBar")
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = BASE_DIR
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    pass

CONF_PATH = os.path.join(DATA_DIR, "config.json")
LOG_PATH = os.path.join(DATA_DIR, "ticker.log")

STARTUP_DIR = os.path.join(os.environ.get("APPDATA", ""),
                           r"Microsoft\Windows\Start Menu\Programs\Startup")
LNK_PATH = os.path.join(STARTUP_DIR, "任务栏行情条.lnk")
OLD_LNK = os.path.join(STARTUP_DIR, "黄金上证行情挂件.lnk")   # 旧版，清理用

H = 40                      # 逻辑高度（96dpi 基准），渲染时按 DPI 放大
PAD_L, PAD_R = 13, 12
GAP_GROUP = 22
S = 3                       # 超采样倍数
SCALE = 1.0                 # 当前 DPI 缩放比（1.0 = 96dpi）


def sc(v):
    """逻辑像素 -> 当前 DPI 下的物理像素"""
    return int(round(v * SCALE))


def apply_dpi(scale):
    global SCALE
    SCALE = max(1.0, min(2.5, float(scale or 1.0)))


def init_dpi():
    """启用 Per-Monitor V2 DPI 感知，返回缩放比。必须先于任何窗口创建调用"""
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                user32.SetProcessDPIAware()
            except Exception:
                pass
    try:
        return user32.GetDpiForSystem() / 96.0
    except Exception:
        pass
    try:
        hdc = user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
        user32.ReleaseDC(0, hdc)
        return dpi / 96.0 if dpi else 1.0
    except Exception:
        return 1.0
STALE_SEC = 600
GUARD_MS = 150

user32 = ctypes.windll.user32
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetForegroundWindow.restype = wintypes.HWND
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.IsZoomed.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
user32.SetParent.restype = wintypes.HWND
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.BOOL]
user32.MoveWindow.restype = wintypes.BOOL
user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.ScreenToClient.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = wintypes.LONG
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
user32.SetWindowLongW.restype = wintypes.LONG
user32.GetDpiForWindow.argtypes = [wintypes.HWND]
user32.GetDpiForWindow.restype = wintypes.UINT
user32.GetDpiForSystem.restype = wintypes.UINT

T_LIGHT = {
    "pill": (232, 233, 235),
    "border": (205, 207, 210),
    "price": (25, 27, 31),
    "label": (108, 114, 122),
    "unit": (140, 146, 154),
    "up": (203, 44, 38),
    "down": (10, 138, 78),
    "gray": (150, 155, 162),
    "time": (120, 126, 134),
}
T_DARK = {
    "pill": (45, 47, 52),
    "border": (64, 67, 73),
    "price": (238, 240, 244),
    "label": (158, 164, 172),
    "unit": (128, 134, 142),
    "up": (245, 96, 88),
    "down": (56, 196, 138),
    "gray": (112, 118, 126),
    "time": (132, 138, 146),
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

GROUPS = [
    ("gold", "黄金", "元/克"),
    ("sh", "上证", None),
    ("sz", "深证", None),
]

SECID = {"gold": "118.AUTD", "sh": "1.000001", "sz": "0.399001"}
TITLE = {"gold": "黄金 Au(T+D)", "sh": "上证指数", "sz": "深证成指"}
PANEL_W, PANEL_H = 340, 142
TREND_TTL = 30

DEFAULT_CFG = {
    "interval": 2,
    "gold_source": "sge",
    "show": {"gold": True, "sh": True, "sz": True},
    "features": {"hover": True},
    "x": None,
    "autostart": True,
}


# ---------------------------------------------------------------- 系统
def theme_is_light():
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return bool(winreg.QueryValueEx(k, "SystemUsesLightTheme")[0])
    except Exception:
        return True


def taskbar_rect():
    try:
        h = user32.FindWindowW("Shell_TrayWnd", None)
        if h:
            r = wintypes.RECT()
            user32.GetWindowRect(wintypes.HWND(h), ctypes.byref(r))
            if r.bottom > r.top:
                return r.left, r.top, r.right, r.bottom
    except Exception:
        pass
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    return 0, sh - 48, sw, sh


def sample_taskbar_color(default):
    try:
        from PIL import ImageGrab
        l, t, r, b = taskbar_rect()
        y = t + (b - t) // 2
        xs = list(range(620, min(r - 20, 1900), 60))
        if len(xs) < 2:
            return default
        box = (xs[0], y, xs[-1] + 1, y + 1)
        im = ImageGrab.grab(bbox=box)
        cols = [im.getpixel((x - box[0], 0)) for x in xs]
        return tuple(sorted(c[i] for c in cols)[len(cols) // 2] for i in range(3))
    except Exception:
        return default


def _busy_columns(row, width, thr=16):
    """以局部均值为背景做差，标记图标所在列；可抗半透明任务栏透出的壁纸纹理"""
    win = max(25, width // 32)
    if win % 2 == 0:
        win += 1
    pre = [[0] * (width + 1) for _ in range(3)]
    for i, p in enumerate(row):
        pre[0][i + 1] = pre[0][i] + p[0]
        pre[1][i + 1] = pre[1][i] + p[1]
        pre[2][i + 1] = pre[2][i] + p[2]
    half = win // 2
    busy = bytearray(width)
    for x in range(width):
        lo = max(0, x - half)
        hi = min(width, x + half + 1)
        n = float(hi - lo)
        r = row[x]
        d = max(abs(r[c] - (pre[c][hi] - pre[c][lo]) / n) for c in range(3))
        if d > thr:
            busy[x] = 1
    return busy


SHELL_PROCS = ("explorer.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe",
               "searchhost.exe", "shellhost.exe", "textinputhost.exe")


def _proc_name(pid):
    """取进程可执行文件名（小写），失败返回空串"""
    try:
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if not h:
            return ""
        buf = ctypes.create_unicode_buffer(260)
        size = wintypes.DWORD(260)
        ctypes.windll.kernel32.QueryFullProcessImageNameW(
            h, 0, buf, ctypes.byref(size))
        ctypes.windll.kernel32.CloseHandle(h)
        return os.path.basename(buf.value).lower()
    except Exception:
        return ""


def scan_free_slot(need_w):
    """
    返回任务栏上最左侧、能放下 need_w 且不压住图标的屏幕 x。
    采样多行合并占用区，避免单个图标只占部分高度时漏检。
    """
    l, t, r, b = taskbar_rect()
    width = max(0, r - l)
    if width < 40:
        return l + sc(8)
    try:
        from PIL import ImageGrab
        hgt = max(4, b - t)
        ys = [t + max(1, min(hgt - 2, int(hgt * f))) for f in (0.35, 0.5, 0.65)]
        im = ImageGrab.grab(bbox=(l, ys[0], r, ys[-1] + 1))
        busy = bytearray(width)
        for y in ys:
            row = [im.getpixel((x, y - ys[0])) for x in range(width)]
            for x, v in enumerate(_busy_columns(row, width)):
                if v:
                    busy[x] = 1
        need = int(need_w) + sc(16)
        best_start, best_len, run = 0, 0, 0
        for x in range(width):
            run = 0 if busy[x] else run + 1
            if run > best_len:
                best_len, best_start = run, x - run + 1
            if run >= need:
                return l + (x - run + 1) + sc(8)
        if best_len >= need_w:                      # 够宽就用最长空档
            return l + best_start + sc(8)
        return l + sc(8)
    except Exception:
        return l + sc(8)


# ---------------------------------------------------------------- 配置
def load_conf():
    cfg = json.loads(json.dumps(DEFAULT_CFG))
    try:
        with open(CONF_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        allowed = ("interval", "gold_source", "show", "features", "x", "autostart")
        for k, v in data.items():
            if k not in allowed:
                continue
            if k in ("show", "features") and isinstance(v, dict):
                cfg[k].update({kk: bool(vv) for kk, vv in v.items()})
            else:
                cfg[k] = v
    except Exception:
        pass
    if not any(cfg["show"].get(g[0]) for g in GROUPS):
        cfg["show"] = {"gold": True, "sh": True, "sz": True}
    # 只保留悬停开关，其余历史字段丢弃
    feats = cfg.get("features") or {}
    cfg["features"] = {"hover": bool(feats.get("hover", True))}
    return cfg


def save_conf(cfg):
    try:
        with open(CONF_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


# ---------------------------------------------------------------- 行情
_MODE = [None]      # None=未定, False=直连, True=系统代理


def _open(url, headers, use_proxy, timeout, enc):
    handler = urllib.request.ProxyHandler() if use_proxy else urllib.request.ProxyHandler({})
    op = urllib.request.build_opener(handler)
    req = urllib.request.Request(url, headers=headers)
    with op.open(req, timeout=timeout) as r:
        return r.read().decode(enc, errors="replace")


def http_get(url, referer=None, timeout=3, enc="gbk"):
    """直连优先，失败回退系统代理；记住上次成功的通道，避免每次多等一轮超时"""
    headers = {"User-Agent": UA, "Cache-Control": "no-cache"}
    if referer:
        headers["Referer"] = referer
    modes = [False, True] if _MODE[0] is None else [_MODE[0], not _MODE[0]]
    last = None
    for use_proxy in modes:
        try:
            data = _open(url, headers, use_proxy, timeout, enc)
            _MODE[0] = use_proxy
            return data
        except Exception as e:
            last = e
    raise last


def sina_quote(symbol):
    txt = http_get("https://hq.sinajs.cn/list=" + symbol,
                   referer="https://finance.sina.com.cn")
    m = re.search(r'"(.*?)"', txt)
    if not m or not m.group(1).strip():
        raise ValueError("empty quote: " + symbol)
    return m.group(1).split(",")


def parse_qtime(date_s, time_s):
    try:
        return datetime.strptime("%s %s" % (date_s.strip(), time_s.strip()),
                                 "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def fetch_gold_sge():
    p = sina_quote("gds_AUTD")
    last = float(p[0])
    prev = float(p[7]) if len(p) > 7 else 0.0
    if not (10 < last < 10000):
        raise ValueError("bad gold")
    if not (10 < prev < 10000) or abs(prev - last) / last > 0.3:
        prev = 0.0
    qt = parse_qtime(p[12], p[6]) if len(p) > 12 else None
    return last, prev, qt


def fetch_usdcny():
    p = sina_quote("USDCNY")
    for i in (8, 9, 3, 1):
        try:
            v = float(p[i])
            if 4 < v < 12:
                return v
        except Exception:
            pass
    raise ValueError("usdcny")


def fetch_gold_xau():
    p = sina_quote("hf_XAU")
    last = float(p[0])
    prev = float(p[7]) if len(p) > 7 else 0.0
    if not (500 < last < 20000):
        raise ValueError("bad xau")
    k = fetch_usdcny() / 31.1034768
    prev = prev * k if 500 < prev < 20000 else 0.0
    qt = parse_qtime(p[12], p[6]) if len(p) > 12 else None
    return last * k, prev, qt


def fetch_indexes():
    """一次请求取上证 + 深证"""
    txt = http_get("https://qt.gtimg.cn/q=sh000001,sz399001")
    out = {}
    for chunk in txt.split(";"):
        if "=" not in chunk or '"' not in chunk:
            continue
        body = chunk.split('"')[1]
        if not body:
            continue
        p = body.split("~")
        if len(p) < 5:
            continue
        code = p[2]
        try:
            cur = float(p[3])
            prev = float(p[4])
        except Exception:
            continue
        if not (100 < cur < 100000):
            continue
        qt = None
        for f in p[:40]:
            if re.fullmatch(r"\d{14}", f.strip()):
                try:
                    qt = datetime.strptime(f.strip(), "%Y%m%d%H%M%S")
                except Exception:
                    pass
                break
        key = "sh" if code.startswith("000001") else ("sz" if code.startswith("399") else None)
        if key:
            out[key] = (cur, prev, qt)
    return out


def _trend_tencent(key):
    code = {"sh": "sh000001", "sz": "sz399001"}.get(key)
    if not code:
        return []
    url = "https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=" + code
    js = json.loads(http_get(url, enc="utf-8"))
    d = (js.get("data") or {}).get(code) or {}
    rows = ((d.get("data") or {}).get("data")) or []
    out = []
    for r in rows:
        f = r.split(" ")
        if len(f) >= 2:
            try:
                out.append(("%s:%s" % (f[0][:2], f[0][2:4]), float(f[1])))
            except Exception:
                pass
    return out


def _trend_sina_au0():
    """新浪 沪金连续（AU0）分时，作为 Au(T+D) 的兜底"""
    url = ("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/"
           "var%20t=/InnerFuturesNewService.getMinLine?symbol=AU0")
    txt = http_get(url, referer="https://finance.sina.com.cn")
    m = re.search(r"\((\[.*\])\)", txt, re.S)
    if not m:
        return []
    out = []
    for row in json.loads(m.group(1)):
        try:
            out.append((row[0], float(row[1])))
        except Exception:
            pass
    return out


def _trend_eastmoney(secid):
    url = ("https://push2.eastmoney.com/api/qt/stock/trends2/get?secid=%s"
           "&fields1=f1,f2,f3,f4,f5&fields2=f51,f53&ndays=1&iscr=0" % secid)
    js = json.loads(http_get(url, enc="utf-8"))
    data = js.get("data") or {}
    out = []
    for row in data.get("trends") or []:
        try:
            ts, px = row.split(",")[:2]
            out.append((ts.split(" ")[-1], float(px)))
        except Exception:
            pass
    return out


def fetch_trend(key):
    """返回 (分时点列表, 数据来源标签)。多源兜底，任一可用即可。"""
    if key == "gold":
        for secid, tag in (("118.AUTD", ""),):
            try:
                pts = _trend_eastmoney(secid)
                if len(pts) > 5:
                    return pts, tag
            except Exception as e:
                log("trend em gold: %s" % e)
        try:
            pts = _trend_sina_au0()
            if len(pts) > 5:
                return pts, "沪金连续"
        except Exception as e:
            log("trend sina gold: %s" % e)
        return [], ""

    try:
        pts = _trend_tencent(key)
        if len(pts) > 5:
            return pts, ""
    except Exception as e:
        log("trend tx %s: %s" % (key, e))
    secid = "1.000001" if key == "sh" else "0.399001"
    try:
        pts = _trend_eastmoney(secid)
        if len(pts) > 5:
            return pts, ""
    except Exception as e:
        log("trend em %s: %s" % (key, e))
    return [], ""


def in_session(kind, dt):
    m = dt.hour * 60 + dt.minute
    wd = dt.weekday()
    if kind in ("sh", "sz"):
        if wd >= 5:
            return False
        return (9 * 60 + 30 <= m < 11 * 60 + 30) or (13 * 60 <= m < 15 * 60)
    if m < 150:
        return wd in (1, 2, 3, 4, 5)
    if wd >= 5:
        return False
    return (9 * 60 <= m < 11 * 60 + 30) or (13 * 60 + 30 <= m < 15 * 60 + 30) \
        or (20 * 60 <= m)


def next_open(keys, now):
    """从当前时刻起，逐分钟找到任一标的进入交易时段的时间"""
    t = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(7 * 24 * 60):
        if any(in_session(k, t) for k in keys):
            return t
        t += timedelta(minutes=1)
    return None


def fetch_all(cfg):
    now = datetime.now()
    st = {"gold": None, "sh": None, "sz": None, "err": ""}
    errs = []

    order = ["sge", "xau"] if cfg.get("gold_source") == "sge" else ["xau", "sge"]
    for src in order:
        try:
            cur, prev, qt = fetch_gold_sge() if src == "sge" else fetch_gold_xau()
            live = in_session("gold", now)
            if qt and (now - qt).total_seconds() > STALE_SEC:
                live = False
            st["gold"] = {"price": cur, "prev": prev, "qtime": qt, "live": live}
            break
        except Exception as e:
            errs.append("gold: %s" % e)

    try:
        for key, (cur, prev, qt) in fetch_indexes().items():
            live = in_session(key, now)
            if qt and (now - qt).total_seconds() > STALE_SEC:
                live = False
            st[key] = {"price": cur, "prev": prev, "qtime": qt, "live": live}
    except Exception as e:
        errs.append("index: %s" % e)

    st["err"] = "; ".join(errs)
    st["ts"] = time.time()
    return st


# ---------------------------------------------------------------- 绘制
def load_font(path, size, fallback="C:/Windows/Fonts/msyh.ttc"):
    for p in (path, fallback):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


F_REG = "C:/Windows/Fonts/msyh.ttc"
F_NUM = "C:/Windows/Fonts/seguisb.ttf"


def color_of(pct):
    if pct is None:
        return "gray"
    if pct > 0.0005:
        return "up"
    if pct < -0.0005:
        return "down"
    return "gray"


def fmt(v, nd=2):
    return ("{:,.%df}" % nd).format(v)


class Painter:
    def __init__(self, theme, key):
        self.t = theme
        self.key = key
        self.f_lbl = load_font(F_REG, 10 * S)
        self.f_price = load_font(F_NUM, 15 * S)
        self.f_unit = load_font(F_REG, 9 * S)
        self.f_pct = load_font(F_NUM, 10 * S)
        self.f_idx = load_font(F_NUM, 14 * S)
        self.f_time = load_font(F_NUM, 9 * S)
        self.f_cn_sm = load_font(F_REG, 9 * S)
        self._probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        self._buf = None        # 复用主条画布，避免每帧重新分配
        self._pbuf = None       # 复用时序面板画布
        self.ranges = []        # [(key, x0, x1), ...] 供点击/悬停命中判定

    def tw(self, s, font):
        return self._probe.textlength(s, font=font) / S

    def group_parts(self, key, label, unit, item, fresh=True):
        live = bool(item and item.get("live") and fresh)
        pct = None
        price_s = "--"
        if item:
            price_s = fmt(item["price"])
            if item.get("prev"):
                pct = (item["price"] - item["prev"]) / item["prev"] * 100
        if pct is None:
            pct_s, arrow = "--", ""
        else:
            arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "—")
            pct_s = "%.2f%%" % abs(pct)
        price_font = self.f_price if key == "gold" else self.f_idx
        w = self.tw(label, self.f_lbl) + 5 + self.tw(price_s, price_font) + 3
        if unit:
            w += self.tw(unit, self.f_unit) + 7
        if arrow:
            w += self.tw(arrow, self.f_pct) + 2
        w += self.tw(pct_s, self.f_pct)
        return {"w": w, "price_s": price_s, "pct_s": pct_s, "arrow": arrow,
                "pct": pct, "live": live, "price_font": price_font}

    def measure(self, st, cfg, closed=False):
        shown = [g for g in GROUPS if cfg["show"].get(g[0])]
        try:
            lim = max(10, int(cfg.get("interval", 2)) * 4)
        except Exception:
            lim = 10
        age = time.time() - (st.get("ts") or 0)
        fresh = age <= lim
        parts = [(g, self.group_parts(g[0], g[1], g[2], st.get(g[0]), fresh))
                 for g in shown]
        body = sum(p["w"] for _, p in parts) + GAP_GROUP * max(0, len(parts) - 1)
        if closed:
            time_s = "已收盘"
        else:
            time_s = time.strftime("%H:%M:%S",
                                   time.localtime(st.get("ts") or time.time()))
        tfont = self.f_cn_sm if closed else self.f_time
        total = PAD_L + body + 14 + self.tw(time_s, tfont) + PAD_R + 3
        return total, parts, time_s

    def render(self, st, cfg, closed=False):
        t = self.t
        total, parts, time_s = self.measure(st, cfg, closed)
        W = int(round(total))
        size = (W * S, H * S)
        if self._buf is None or self._buf.size != size:
            self._buf = Image.new("RGB", size, self.key)
        else:
            self._buf.paste(self.key, (0, 0, size[0], size[1]))
        img = self._buf
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, W * S - 1, H * S - 1], radius=9 * S,
                            fill=t["pill"], outline=t["border"], width=max(1, S // 2))
        self.ranges = []
        cy = 20

        def txt(x, s, font, fill, anchor="lm"):
            d.text((x * S, cy * S), s, font=font, fill=fill, anchor=anchor)
            return d.textlength(s, font=font) / S

        x = PAD_L
        for i, (g, p) in enumerate(parts):
            if i:
                sep_x = x + GAP_GROUP // 2
                d.line([(sep_x * S, 9 * S), (sep_x * S, 31 * S)],
                       fill=t["border"], width=max(1, S // 2))
                x += GAP_GROUP
            gx = x
            live = p["live"]
            x += txt(x, g[1], self.f_lbl, t["label"]) + 5
            x += txt(x, p["price_s"], p["price_font"],
                     t["price"] if live else t["gray"]) + 3
            if g[2]:
                x += txt(x, g[2], self.f_unit,
                         t["unit"] if live else t["gray"]) + 7
            c = t[color_of(p["pct"])] if p["pct"] is not None else t["gray"]
            if p["arrow"]:
                x += txt(x, p["arrow"], self.f_pct, c) + 2
            txt(x, p["pct_s"], self.f_pct, c)
            x = gx + p["w"]
            self.ranges.append((g[0], gx * SCALE, (gx + p["w"]) * SCALE))

        if closed:
            txt(W - PAD_R, time_s, self.f_cn_sm, t["gray"], anchor="rm")
        else:
            txt(W - PAD_R, time_s, self.f_time, t["time"], anchor="rm")
        return img.resize((max(1, sc(W)), max(1, sc(H))), Image.LANCZOS)


    # ---------------------------------------------------------- 分时面板
    def render_panel(self, key, item, pts, src=""):
        t = self.t
        PS = 2
        W, Hh = PANEL_W, PANEL_H
        size = (W * PS, Hh * PS)
        if self._pbuf is None or self._pbuf.size != size:
            self._pbuf = Image.new("RGB", size, self.key)
        else:
            self._pbuf.paste(self.key, (0, 0, size[0], size[1]))
        img = self._pbuf
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, W * PS - 1, Hh * PS - 1], radius=10 * PS,
                            fill=t["pill"], outline=t["border"], width=max(1, PS // 2))

        f_title = load_font(F_REG, 11 * PS)
        f_price = load_font(F_NUM, 17 * PS)
        f_mid = load_font(F_NUM, 12 * PS)
        f_sm = load_font(F_NUM, 9 * PS)
        f_cn = load_font(F_REG, 9 * PS)

        title = TITLE.get(key, key)
        if src:
            title = "%s · %s" % (title.split(" ")[0], src)
        d.text((14 * PS, 17 * PS), title, font=f_title, fill=t["label"], anchor="lm")
        tw = d.textlength(title, font=f_title) / PS

        price_s = fmt(item["price"]) if item else "--"
        d.text(((14 + tw + 8) * PS, 17 * PS), price_s, font=f_price,
               fill=t["price"] if item else t["gray"], anchor="lm")

        pct = None
        if item and item.get("prev"):
            pct = (item["price"] - item["prev"]) / item["prev"] * 100
            arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "—")
            d.text(((W - 14) * PS, 18 * PS), "%s %.2f%%" % (arrow, abs(pct)),
                   font=f_mid, fill=t[color_of(pct)], anchor="rm")

        x0, x1 = 14, W - 16
        y0, y1 = 38, Hh - 24
        for gy in (y0, (y0 + y1) // 2, y1):
            d.line([(x0 * PS, gy * PS), (x1 * PS, gy * PS)], fill=t["border"], width=1)

        if not pts:
            d.text(((W // 2) * PS, ((y0 + y1) // 2) * PS), "分时加载中…",
                   font=f_cn, fill=t["gray"], anchor="mm")
        else:
            vals = [v for _, v in pts]
            prev = (item or {}).get("prev") or 0
            lo, hi = min(vals), max(vals)
            if prev:
                lo, hi = min(lo, prev), max(hi, prev)
            if hi - lo < 1e-9:
                hi = lo + 1
            pad = (hi - lo) * 0.12
            lo -= pad
            hi += pad

            def fy(v):
                return y1 - (v - lo) / (hi - lo) * (y1 - y0)

            def fx(i):
                return x0 + i / max(1, len(pts) - 1) * (x1 - x0)

            line_c = t["price"]
            if prev:
                line_c = t["up"] if vals[-1] >= prev else t["down"]
                py = fy(prev)
                gx = x0
                while gx < x1:
                    d.line([(gx * PS, py * PS),
                            (min(gx + 4, x1) * PS, py * PS)],
                           fill=t["gray"], width=1)
                    gx += 8

            poly = [(fx(i) * PS, fy(v) * PS) for i, (_, v) in enumerate(pts)]
            if len(poly) > 1:
                d.line(poly, fill=line_c, width=2 * PS, joint="curve")
            px_, py_ = poly[-1]
            d.ellipse([px_ - 3 * PS, py_ - 3 * PS, px_ + 3 * PS, py_ + 3 * PS],
                      fill=line_c)

            d.text((x0 * PS, (Hh - 11) * PS), pts[0][0], font=f_sm,
                   fill=t["time"], anchor="lm")
            d.text((x1 * PS, (Hh - 11) * PS), pts[-1][0], font=f_sm,
                   fill=t["time"], anchor="rm")
            if prev:
                d.text(((W // 2) * PS, (Hh - 11) * PS), "昨收 %s" % fmt(prev),
                       font=f_cn, fill=t["time"], anchor="mm")

        return img.resize((max(1, sc(W)), max(1, sc(Hh))), Image.LANCZOS)


# ---------------------------------------------------------------- 主窗口
class Widget:
    def __init__(self):
        self.cfg = load_conf()
        self.state = {"ts": 0}
        self._stop = False
        self._photo = None
        self._hidden = False
        self._w = 0
        self._placed = False
        self._last_bar = taskbar_rect()
        self.theme = T_LIGHT if theme_is_light() else T_DARK
        self.key = sample_taskbar_color((218, 219, 220) if theme_is_light() else (32, 33, 36))
        self.painter = Painter(self.theme, self.key)

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("任务栏行情条")
        self.root.overrideredirect(True)
        self.root.configure(bg=self._hex(self.key))
        try:
            self.root.attributes("-transparentcolor", self._hex(self.key))
        except Exception:
            pass
        self.root.attributes("-topmost", True)

        self.canvas = tk.Canvas(self.root, width=200, height=sc(H), highlightthickness=0,
                                bd=0, bg=self._hex(self.key))
        self.canvas.pack()
        self._card = self.canvas.create_image(0, 0, anchor="nw")
        self.canvas.bind("<Button-3>", self.on_menu)
        self.canvas.bind("<Enter>", self.on_enter)
        self.canvas.bind("<Leave>", lambda e: self._schedule_hide())
        self.canvas.bind("<Motion>", self.on_motion)

        # 分时面板 / 走势缓存
        self.panel = None
        self._panel_key = None
        self._hide_job = None
        self._trend = {}
        self._trend_busy = set()
        self._embedded = False        # 是否已挂进任务栏
        self._embed_fail = 0          # 连续失败次数，超过 3 次永久回退
        self._bar_hwnd = 0
        self._cx = self._cy = 0       # 嵌入模式下的客户区坐标
        self._paused = False          # 全部收盘 -> 暂停轮询
        self._resume_at = None        # 下一个开盘时间戳
        self._closed = False
        self._fetch_lock = threading.Lock()


        self.build_menu()
        self._make_panel()

        self.draw()
        self.place(self._w)                   # 先用覆盖层定位（尺寸同理）
        self._placed = True
        self.root.deiconify()
        self.root.update_idletasks()

        self.hwnd = self._top_hwnd()
        self._embedded = self._embed()        # 窗口映射后再挂进任务栏
        if self._embedded:
            self._place_embedded(self._w)
            log("已嵌入任务栏")
        else:
            log("嵌入失败，回退置顶覆盖")

        self._update_session()
        threading.Thread(target=self.loop, daemon=True).start()
        self.root.after(1000, self.tick)
        self.root.after(GUARD_MS, self.guard)
        if self.cfg.get("autostart", True) and not self.autostart_on():
            self.set_autostart(True)

    @staticmethod
    def _hex(c):
        return "#%02x%02x%02x" % c

    def _top_hwnd(self):
        try:
            h = user32.GetAncestor(wintypes.HWND(self.root.winfo_id()), 2)
            return h or self.root.winfo_id()
        except Exception:
            return 0

    # ---------- 分时面板
    def _make_panel(self):
        p = tk.Toplevel(self.root)
        p.withdraw()
        p.overrideredirect(True)
        p.configure(bg=self._hex(self.key))
        try:
            p.attributes("-transparentcolor", self._hex(self.key))
        except Exception:
            pass
        p.attributes("-topmost", True)
        c = tk.Canvas(p, width=sc(PANEL_W), height=sc(PANEL_H), highlightthickness=0,
                      bd=0, bg=self._hex(self.key))
        c.pack()
        self._panel_img = c.create_image(0, 0, anchor="nw")
        c.bind("<Enter>", lambda e: self._cancel_hide())
        c.bind("<Leave>", lambda e: self._schedule_hide())
        self.panel = p
        self.panel_canvas = c
        self._panel_photo = None
        self._panel_sig = None

    def _group_at(self, x):
        for k, x0, x1 in self.painter.ranges:
            if x0 - 5 <= x <= x1 + 5:
                return k
        return None

    def _place_panel(self):
        sw = user32.GetSystemMetrics(0)
        bx, by, _, _ = self._bar_rect()
        x = max(4, min(bx, sw - sc(PANEL_W) - 6))
        y = max(4, by - sc(PANEL_H) - 6)
        self.panel.geometry("%dx%d+%d+%d" % (sc(PANEL_W), sc(PANEL_H), x, y))

    def _render_panel(self, force=False):
        if not self._panel_key or not self.panel:
            return
        k = self._panel_key
        item = self.state.get(k) or {}
        tr = self._trend.get(k) or {}
        pts = tr.get("pts") or []
        sig = (k, item.get("price"), item.get("prev"), len(pts),
               pts[-1][0] if pts else "", tr.get("src", ""))
        if not force and sig == self._panel_sig:
            return
        self._panel_sig = sig
        img = self.painter.render_panel(k, item, pts, tr.get("src", ""))
        if self._panel_photo is not None:
            self._panel_photo.paste(img)
        else:
            self._panel_photo = ImageTk.PhotoImage(img)
            self.panel_canvas.itemconfig(self._panel_img, image=self._panel_photo)

    def _ensure_trend(self, key):
        tr = self._trend.get(key)
        if tr and time.time() - tr["ts"] < TREND_TTL:
            return
        if key in self._trend_busy:
            return
        self._trend_busy.add(key)

        def work():
            pts, src = [], ""
            try:
                pts, src = fetch_trend(key)
            except Exception as e:
                log("trend %s: %s" % (key, e))
            self._trend[key] = {"ts": time.time(), "pts": pts, "src": src}
            self._trend_busy.discard(key)

        threading.Thread(target=work, daemon=True).start()

    def _show_panel(self, key):
        if not self.cfg["features"].get("hover", True):
            return
        self._cancel_hide()
        self._panel_key = key
        self._panel_sig = None
        self._place_panel()
        self._render_panel(force=True)
        self.panel.deiconify()
        self.panel.attributes("-topmost", True)
        self._ensure_trend(key)

    def _hide_panel(self):
        self._panel_key = None
        try:
            if self.panel:
                self.panel.withdraw()
        except Exception:
            pass

    def _cancel_hide(self):
        if self._hide_job:
            try:
                self.root.after_cancel(self._hide_job)
            except Exception:
                pass
            self._hide_job = None

    def _schedule_hide(self):
        self._cancel_hide()
        self._hide_job = self.root.after(380, self._maybe_hide)

    def _maybe_hide(self):
        self._hide_job = None
        try:
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            if self.panel and self.panel.winfo_viewable():
                px, py = self.panel.winfo_x(), self.panel.winfo_y()
                if px <= pt.x <= px + sc(PANEL_W) and py <= pt.y <= py + sc(PANEL_H):
                    return
            bx, by, br, bb = self._bar_rect()
            bw, bh = br - bx, bb - by
            if bx <= pt.x <= bx + bw and by <= pt.y <= by + bh:
                return
        except Exception:
            pass
        self._hide_panel()

    # ---------- 鼠标
    def on_enter(self, e):
        self._cancel_hide()
        k = self._group_at(e.x)
        if k:
            self._show_panel(k)

    def on_motion(self, e):
        k = self._group_at(e.x)
        if k and k != self._panel_key:
            self._show_panel(k)

    # ---------- 嵌入任务栏
    def _bar_rect(self):
        r = wintypes.RECT()
        user32.GetWindowRect(wintypes.HWND(self.hwnd), ctypes.byref(r))
        return r.left, r.top, r.right, r.bottom

    def _embed(self):
        """把窗口设成任务栏的子窗口；失败返回 False"""
        try:
            bar = user32.FindWindowW("Shell_TrayWnd", None)
            hwnd = self.hwnd or self._top_hwnd()
            if not bar or not hwnd:
                return False
            GWL_STYLE, WS_CHILD, WS_POPUP = -16, 0x40000000, 0x80000000
            style = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE) & 0xFFFFFFFF
            user32.SetParent(wintypes.HWND(hwnd), wintypes.HWND(bar))
            user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE,
                                  (style & ~WS_POPUP) | WS_CHILD)
            user32.SetWindowPos(wintypes.HWND(hwnd), None, 0, 0, 0, 0,
                                0x0001 | 0x0002 | 0x0004 | 0x0020 | 0x0040)
            if user32.GetParent(wintypes.HWND(hwnd)) != bar:
                user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE,
                                      (style & ~WS_CHILD) | WS_POPUP)
                return False
            self._bar_hwnd = bar
            self.hwnd = hwnd
            return True
        except Exception as e:
            log("embed fail: %s" % e)
            return False

    def _check_embed(self):
        """Explorer 重启后任务栏句柄会变，子窗口被销毁，需要重挂"""
        try:
            bar = user32.FindWindowW("Shell_TrayWnd", None)
            if not bar:
                return
            if user32.GetParent(wintypes.HWND(self.hwnd)) == bar:
                self._embed_fail = 0
                self._embed_resets = 0
                return
            self._embed_resets = getattr(self, "_embed_resets", 0) + 1
            if self._embed_resets > 10:
                self._embedded = False
                self.place(self._w)
                log("多次重挂无效，改为置顶覆盖")
                return
            if self._embed():
                self._place_embedded(self._w)
                user32.ShowWindow(wintypes.HWND(self.hwnd), 5)
                self._embed_fail = 0
                log("任务栏重挂成功")
            else:
                self._embed_fail += 1
                if self._embed_fail >= 3:
                    self._embedded = False
                    self.root.deiconify()
                    self.place(self._w)
                    log("重挂失败，回退置顶覆盖")
        except Exception:
            pass

    def _place_embedded(self, w=None):
        w = w or self._w
        l, t, r, b = taskbar_rect()
        x = scan_free_slot(w)
        if x + w > r - sc(8):
            x = max(l + sc(8), r - w - sc(8))
        y = t + max(0, (b - t - sc(H)) // 2)
        pt = wintypes.POINT(int(x), int(y))
        user32.ScreenToClient(wintypes.HWND(self._bar_hwnd), ctypes.byref(pt))
        self._cx, self._cy = int(pt.x), int(pt.y)
        user32.MoveWindow(wintypes.HWND(self.hwnd), self._cx, self._cy,
                          int(w), sc(H), True)
        self.cfg["x"] = x
        save_conf(self.cfg)

    # ---------- 定位
    def place(self, w=None):
        w = w or self._w
        if self._embedded:
            self._place_embedded(w)
            return
        l, tp, r, b = taskbar_rect()
        y = tp + max(0, (b - tp - sc(H)) // 2)
        x = scan_free_slot(w)
        if x + w > r - sc(8):
            x = max(l + sc(8), r - w - sc(8))
        self.root.geometry("%dx%d+%d+%d" % (w, sc(H), x, y))
        self.cfg["x"] = x
        save_conf(self.cfg)

    def relayout(self):
        """重新定位：先隐藏自身再扫描，避免把自己当成图标"""
        if self._embedded:
            user32.ShowWindow(wintypes.HWND(self.hwnd), 0)
            time.sleep(0.08)
            self._place_embedded(self._w)
            user32.ShowWindow(wintypes.HWND(self.hwnd), 5)
            return
        self.root.withdraw()
        self.root.update_idletasks()
        time.sleep(0.06)
        self.place(self._w)
        self.root.deiconify()
        self.root.attributes("-topmost", True)

    def guard(self):
        if self._stop:
            return
        try:
            if not self._hidden and not self._embedded:
                h = user32.GetAncestor(wintypes.HWND(self.root.winfo_id()), 2)
                if h:
                    self.hwnd = h
                self.raise_over_taskbar()
        except Exception:
            pass
        self.root.after(GUARD_MS, self.guard)

    def raise_over_taskbar(self):
        try:
            if not self.hwnd:
                return
            pt = wintypes.POINT(self.root.winfo_x() + self._w // 2,
                                self.root.winfo_y() + sc(H) // 2)
            h = user32.WindowFromPoint(pt)
            if not h:
                return
            root_h = user32.GetAncestor(wintypes.HWND(h), 2) or h
            buf = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(wintypes.HWND(root_h), buf, 64)
            if buf.value in ("Shell_TrayWnd", "TrayNotifyWnd", "Progman", "WorkerW",
                             "Windows.UI.Composition.DesktopWindowContentBridge"):
                user32.SetWindowPos(wintypes.HWND(self.hwnd), wintypes.HWND(-1),
                                    0, 0, 0, 0, 0x0003)
        except Exception:
            pass

    def fullscreen_foreground(self):
        try:
            h = user32.GetForegroundWindow()
            if not h or h == self.hwnd:
                return False
            if user32.IsZoomed(h):
                return False
            buf = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(h, buf, 64)
            if buf.value in ("Shell_TrayWnd", "Progman", "WorkerW",
                             "Windows.UI.Core.CoreWindow"):
                return False
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if _proc_name(pid.value) in SHELL_PROCS:   # 开始菜单/搜索/操作中心等系统界面
                return False
            r = wintypes.RECT()
            user32.GetWindowRect(h, ctypes.byref(r))
            sw = user32.GetSystemMetrics(0)
            _, _, _, bar_bottom = taskbar_rect()
            return (r.left <= 0 and r.top <= 0 and r.right >= sw
                    and r.bottom >= bar_bottom - 1)
        except Exception:
            return False

    def _check_dpi(self):
        """显示器缩放变化后重新布局"""
        try:
            d = user32.GetDpiForWindow(wintypes.HWND(self.hwnd)) / 96.0
        except Exception:
            return
        if d <= 0.5 or abs(d - SCALE) < 0.01:
            return
        apply_dpi(d)
        self._photo = None
        self.canvas.config(height=sc(H))
        self.canvas.delete("all")
        self._card = self.canvas.create_image(0, 0, anchor="nw")
        self._panel_photo = None
        if self.panel:
            self.panel_canvas.config(width=sc(PANEL_W), height=sc(PANEL_H))
        self.relayout()
        log("DPI 变化 -> %.2f" % SCALE)

    # ---------- 交易时段
    def _update_session(self):
        keys = [g[0] for g in GROUPS if self.cfg["show"].get(g[0])]
        now = datetime.now()
        closed = (not any(in_session(k, now) for k in keys)) if keys else True
        have_data = bool(self.state.get("ts"))   # 启动时先抓一次收盘价，再暂停
        if closed and not self._paused and have_data:
            self._paused = True
            nxt = next_open(keys, now)
            self._resume_at = nxt.timestamp() if nxt else None
            log("全部收盘，暂停刷新；下次开盘 %s"
                % (nxt.strftime("%m-%d %H:%M") if nxt else "未知"))
        elif not closed and self._paused:
            self._paused = False
            self._resume_at = None
            self.refresh_now()
        self._closed = closed

    # ---------- 心跳
    def tick(self):
        if self._stop:
            return
        try:
            bar = taskbar_rect()
            if bar != self._last_bar:
                self._last_bar = bar
                self.relayout()
            if self._embedded:
                self._check_embed()
            fs = self.fullscreen_foreground() if not self._embedded else False
            if fs and not self._hidden:
                self.root.withdraw()
                self._hidden = True
            elif not fs and self._hidden:
                self.root.deiconify()
                self.root.attributes("-topmost", True)
                self._hidden = False
            if self._hidden:
                self._hide_panel()
            elif self._panel_key and self.panel and self.panel.winfo_viewable():
                self._ensure_trend(self._panel_key)
                self._render_panel()
            self._update_session()
            self._check_dpi()
            self.draw()
        except Exception:
            self._log_err("TICK")
        self.root.after(1000, self.tick)

    # ---------- 菜单
    def build_menu(self):
        self.menu = tk.Menu(self.root, tearoff=0, bg="#ffffff", fg="#1b1f24",
                            activebackground="#e8f0fe", activeforeground="#000000",
                            bd=0, font=("Microsoft YaHei", 9))

        m_iv = tk.Menu(self.menu, tearoff=0, bg="#ffffff", fg="#1b1f24",
                       activebackground="#e8f0fe", activeforeground="#000000",
                       bd=0, font=("Microsoft YaHei", 9))
        self.v_iv = tk.IntVar(value=int(self.cfg.get("interval", 2)))
        for sec in (1, 2, 3, 4, 5):
            m_iv.add_radiobutton(label="每 %d 秒" % sec, variable=self.v_iv,
                                 value=sec, command=self.set_interval)
        self.menu.add_cascade(label="刷新频率", menu=m_iv)

        m_show = tk.Menu(self.menu, tearoff=0, bg="#ffffff", fg="#1b1f24",
                         activebackground="#e8f0fe", activeforeground="#000000",
                         bd=0, font=("Microsoft YaHei", 9))
        self.v_show = {g[0]: tk.BooleanVar(value=bool(self.cfg["show"].get(g[0], True)))
                       for g in GROUPS}
        labels = {"gold": "黄金（元/克）", "sh": "上证指数", "sz": "深证成指"}
        for g in GROUPS:
            m_show.add_checkbutton(label=labels[g[0]], variable=self.v_show[g[0]],
                                   command=self.apply_show)
        self.menu.add_cascade(label="显示内容", menu=m_show)

        m_src = tk.Menu(self.menu, tearoff=0, bg="#ffffff", fg="#1b1f24",
                        activebackground="#e8f0fe", activeforeground="#000000",
                        bd=0, font=("Microsoft YaHei", 9))
        self.v_src = tk.StringVar(value=self.cfg.get("gold_source", "sge"))
        m_src.add_radiobutton(label="上海金 Au(T+D)", variable=self.v_src,
                              value="sge", command=self.toggle_source)
        m_src.add_radiobutton(label="伦敦金×汇率折算", variable=self.v_src,
                              value="xau", command=self.toggle_source)
        self.menu.add_cascade(label="黄金口径", menu=m_src)

        self.v_hover = tk.BooleanVar(value=bool(self.cfg["features"].get("hover", True)))
        self.menu.add_checkbutton(label="悬停显示分时图", variable=self.v_hover,
                                  command=self.toggle_hover)

        self.menu.add_separator()
        self.menu.add_command(label="立即刷新", command=self.refresh_now)
        self.v_boot = tk.BooleanVar(value=self.autostart_on())
        self.menu.add_checkbutton(label="开机自动启动", variable=self.v_boot,
                                  command=self.toggle_autostart)
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.quit)

    def on_menu(self, e):
        try:
            self.v_boot.set(self.autostart_on())
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def set_interval(self):
        try:
            self.cfg["interval"] = max(1, min(5, int(self.v_iv.get())))
        except Exception:
            self.cfg["interval"] = 2
        save_conf(self.cfg)
        self.refresh_now()

    def toggle_hover(self):
        self.cfg["features"] = {"hover": bool(self.v_hover.get())}
        save_conf(self.cfg)
        if not self.cfg["features"]["hover"]:
            self._hide_panel()

    def apply_show(self):
        show = {k: bool(v.get()) for k, v in self.v_show.items()}
        if not any(show.values()):
            for k in show:
                show[k] = True
            for k, v in self.v_show.items():
                v.set(True)
        self.cfg["show"] = show
        save_conf(self.cfg)
        self.draw()

    def toggle_source(self):
        self.cfg["gold_source"] = self.v_src.get()
        save_conf(self.cfg)
        self.refresh_now()

    def refresh_now(self):
        self._paused = False
        self._resume_at = None
        threading.Thread(target=self._fetch_once, daemon=True).start()

    # ---------- 自启
    def _target(self):
        if FROZEN:
            return sys.executable, ""
        exe = sys.executable
        if exe.lower().endswith("python.exe"):
            pw = exe[:-10] + "pythonw.exe"
            if os.path.exists(pw):
                exe = pw
        return exe, '"%s"' % os.path.abspath(sys.argv[0])

    def autostart_on(self):
        return os.path.exists(LNK_PATH)

    def set_autostart(self, enable):
        try:
            if enable:
                import win32com.client
                exe, args = self._target()
                sh = win32com.client.Dispatch("WScript.Shell")
                sc = sh.CreateShortcut(LNK_PATH)
                sc.TargetPath = exe
                sc.Arguments = args
                sc.WorkingDirectory = os.path.dirname(exe)
                sc.WindowStyle = 7
                sc.Description = "黄金/上证/深证 任务栏行情条"
                sc.Save()
            elif os.path.exists(LNK_PATH):
                os.remove(LNK_PATH)
            return self.autostart_on() == enable
        except Exception as e:
            log("autostart fail: %s" % e)
            return False

    def toggle_autostart(self):
        want = bool(self.v_boot.get())
        self.cfg["autostart"] = want
        save_conf(self.cfg)
        if not self.set_autostart(want):
            self.v_boot.set(not want)

    # ---------- 数据
    def _fetch_once(self):
        if not self._fetch_lock.acquire(False):
            return
        try:
            try:
                st = fetch_all(self.cfg)
            except Exception as e:
                st = {"ts": time.time(), "gold": None, "sh": None,
                      "sz": None, "err": str(e)}
            if st.get("err"):
                log(st["err"])
            self.state = st
        finally:
            self._fetch_lock.release()

    def loop(self):
        while not self._stop:
            if self._paused:
                time.sleep(1)
                if self._resume_at and time.time() >= self._resume_at:
                    self._paused = False
                    self._resume_at = None
                continue
            self._fetch_once()
            try:
                iv = max(1, min(5, int(self.cfg.get("interval", 2))))
            except Exception:
                iv = 2
            for _ in range(iv * 10):
                if self._stop:
                    return
                time.sleep(0.1)

    def draw(self):
        img = self.painter.render(self.state, self.cfg, self._closed)
        w = img.width
        if self._photo is not None and self._photo.width() == w:
            self._photo.paste(img)
        else:
            self._photo = ImageTk.PhotoImage(img)
            self.canvas.itemconfig(self._card, image=self._photo)
        if w != self._w:
            old = self._w
            self._w = w
            self.canvas.config(width=w, height=sc(H))
            if old and self._placed:      # 数据变长/变短时同步窗口宽度
                if self._embedded:
                    user32.MoveWindow(wintypes.HWND(self.hwnd), self._cx,
                                      self._cy, int(w), sc(H), True)
                else:
                    self.root.geometry("%dx%d+%d+%d"
                                       % (w, sc(H), self.root.winfo_x(),
                                          self.root.winfo_y()))
        return w

    def _log_err(self, tag):
        now = time.time()
        if now - getattr(self, "_err_ts", 0) > 60:
            self._err_ts = now
            import traceback
            log("%s %s" % (tag, traceback.format_exc()))

    def quit(self):
        self._stop = True
        try:
            if self._embedded and self.hwnd:
                user32.ShowWindow(wintypes.HWND(self.hwnd), 0)
                user32.SetParent(wintypes.HWND(self.hwnd), None)
        except Exception:
            pass
        try:
            if self.panel:
                self.panel.destroy()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


def single_instance():
    try:
        ctypes.windll.kernel32.CreateMutexW(None, False, "TickerBar_SingleInstance")
        return ctypes.windll.kernel32.GetLastError() != 183
    except Exception:
        return True


def main():
    if sys.platform != "win32":
        return
    if not single_instance():
        return
    apply_dpi(init_dpi())
    if os.path.exists(OLD_LNK):
        try:
            os.remove(OLD_LNK)
        except Exception:
            pass
    w = Widget()
    w.root.mainloop()


if __name__ == "__main__":
    main()
