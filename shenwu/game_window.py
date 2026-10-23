"""游戏窗口的识别与几何计算。

职责边界：只回答「这个窗口是不是幻唐志」「客户区在哪、多大」，
不做窗口枚举策略（那是 GameController 的事），也不碰截图与输入。

识别规则：
- 标题必须严格匹配「幻唐志 - <服务器名>」，服务器名动态、可多开；
- 三重排除：RENDER 渲染窗口、资源管理器等壳窗口（标题可能恰好是
  「幻唐志 - 文件资源管理器」）、以及调用方按 pid 排除的自身窗口。
"""

import ctypes
import re

import win32con
import win32gui
from ctypes import wintypes

user32 = ctypes.windll.user32

# 显式声明 64 位指针参数类型，防止 64 位 Python 发生整型截断
user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL

user32.GetWindowDpiAwarenessContext.argtypes = [wintypes.HWND]
user32.GetWindowDpiAwarenessContext.restype = ctypes.c_void_p

user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


user32.LogicalToPhysicalPointForPerMonitorDPI.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(POINT),
]
user32.LogicalToPhysicalPointForPerMonitorDPI.restype = wintypes.BOOL

# 真正的游戏窗口标题固定为「幻唐志 - <服务器名>」，服务器名动态变化、可同时存在多个。
# 只认这种格式，避免把资源管理器目录（标题恰好叫「幻唐志」）或本 GUI 窗口当成游戏窗口
GAME_TITLE_PATTERN = re.compile(r"^\s*幻唐志\s*[-–—－]\s*(?P<server>\S.*?)\s*$")

# 资源管理器 / 桌面等壳窗口：即使标题碰巧带「-」也不是游戏窗口
SHELL_WINDOW_CLASSES = {"CabinetWClass", "ExploreWClass", "Progman", "WorkerW",
                        "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}

# 打开名为「幻唐志」的文件夹时，资源管理器标题会是「幻唐志 - 文件资源管理器」，
# 格式上与游戏窗口完全一致，只能靠窗口类 + 这个服务器名黑名单双保险排除
SHELL_TITLE_BLACKLIST = {"文件资源管理器", "资源管理器", "File Explorer",
                         "Windows Explorer"}


def parse_game_title(title):
    """严格匹配「幻唐志 - xxx」，返回服务器名；不匹配返回 None"""
    if not title:
        return None
    # 渲染窗口标题带 RENDER，历史逻辑一直是排除的
    if "RENDER" in title.upper():
        return None
    match = GAME_TITLE_PATTERN.match(title)
    if match is None:
        return None
    server = match.group("server").strip()
    if not server or server in SHELL_TITLE_BLACKLIST:
        return None
    return server


def get_client_rect(hwnd):
    """
    获取窗口客户区的桌面坐标，不包括标题栏和边框
    返回: (left, top, right, bottom)
    """
    left, top = win32gui.ClientToScreen(hwnd, (0, 0))
    rect = win32gui.GetClientRect(hwnd)
    right = left + rect[2]
    bottom = top + rect[3]
    return left, top, right, bottom


def get_physical_client_rect(hwnd):
    """获取窗口客户区在屏幕上的真实物理像素坐标（免疫任何第三方库的 DPI 覆盖）"""
    # 1. 获取目标游戏窗口自身的 DPI 上下文（例如游戏所处的 150% 逻辑模式）
    hwnd_dpi_ctx = user32.GetWindowDpiAwarenessContext(hwnd)

    # 2. 将当前 Python 线程临时对齐到与游戏窗口完全一致的 DPI 坐标系
    old_ctx = user32.SetThreadDpiAwarenessContext(hwnd_dpi_ctx)
    try:
        # 此时 GetClientRect 和 ClientToScreen 严格处于同一逻辑坐标系 (1200 x 900)
        _, _, client_w, client_h = win32gui.GetClientRect(hwnd)

        left_log, top_log = win32gui.ClientToScreen(hwnd, (0, 0))
        right_log, bottom_log = win32gui.ClientToScreen(
            hwnd, (client_w, client_h)
        )

        # 强制从游戏窗口的逻辑坐标转换为 4K 屏幕的真实物理像素坐标 (1600 x 1200)
        pt_top_left = POINT(left_log, top_log)
        pt_bottom_right = POINT(right_log, bottom_log)

        user32.LogicalToPhysicalPointForPerMonitorDPI(
            hwnd, ctypes.byref(pt_top_left)
        )
        user32.LogicalToPhysicalPointForPerMonitorDPI(
            hwnd, ctypes.byref(pt_bottom_right)
        )

        return (
            pt_top_left.x,
            pt_top_left.y,
            pt_bottom_right.x,
            pt_bottom_right.y,
        )
    finally:
        # 3. 立即恢复 Python 线程原本的 DPI 模式，确保后续 mss 截图与鼠标点击不受影响
        if old_ctx:
            user32.SetThreadDpiAwarenessContext(old_ctx)


def make_region(hwnd):
    """构造截图/坐标换算用的 region：窗口客户区在屏幕上的位置 + hwnd

    region["left"]/["top"] 是客户区左上角的屏幕坐标（帧内 bbox 加上它们
    即得屏幕绝对坐标，供真实鼠标点击用）；region["hwnd"] 供 WGC 截图用。
    """
    left, top, right, bottom = get_client_rect(hwnd)
    if right - left <= 0 or bottom - top <= 0:
        raise ValueError("窗口客户区大小异常，可能窗口最小化或不可见")
    return {"hwnd": hwnd, "left": int(left), "top": int(top)}


def restore_window(hwnd):
    """恢复最小化的窗口（不抢前台）。WGC 截图要求窗口非最小化"""
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    except Exception:
        pass


def set_current_top(hwnd):
    """把窗口恢复并带到前台（真实键鼠注入前调用）"""
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
