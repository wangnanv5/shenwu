"""键盘与鼠标输入：消息级投递（后台、多窗口并行）与真实注入（前台）。

职责边界：只负责「把一次按键/点击送到窗口」，不关心业务含义；
坐标一律是窗口客户区坐标（左上角为原点），与模板匹配得到的坐标同坐标系。

两条通道的取舍：
- PostMessage 消息级：窗口可在后台、可被遮挡，多窗口并行互不干扰；
  但游戏若通过 GetKeyState / 原始输入判定，则收不到修饰键状态。
- 真实注入（keybd_event / SetCursorPos）：作用于前台窗口，能通过键盘状态表判定，
  但会抢占系统键盘与光标，多窗口并行时不可同时使用。
"""

import time

import win32api
import win32con
import win32gui

from shenwu.game_window import set_current_top
from shenwu.timing import human_delay

# ---------- 键盘输入（Windows 消息级，后台操作，不需要窗口前台） ----------
# 通过 PostMessage 向目标窗口投递 WM_KEYDOWN / WM_KEYUP，窗口在后台也能收到。
# 按键名约定：'a'-'z'、'0'-'9'、'f1'-'f24'、'enter'/'esc'/'tab'/'space'/'up' 等
# 方向编辑键，以及 'ctrl'/'alt'/'shift' 修饰键。


def _check_hwnd(hwnd):
    if not win32gui.IsWindow(hwnd):
        raise ValueError(f"无效的窗口句柄: {hwnd!r}")


_WIN_VK = {
    "enter": win32con.VK_RETURN, "esc": win32con.VK_ESCAPE,
    "space": win32con.VK_SPACE, "tab": win32con.VK_TAB,
    "backspace": win32con.VK_BACK, "delete": win32con.VK_DELETE,
    "insert": win32con.VK_INSERT, "home": win32con.VK_HOME,
    "end": win32con.VK_END, "pageup": win32con.VK_PRIOR,
    "pagedown": win32con.VK_NEXT,
    "up": win32con.VK_UP, "down": win32con.VK_DOWN,
    "left": win32con.VK_LEFT, "right": win32con.VK_RIGHT,
    "ctrl": win32con.VK_CONTROL, "alt": win32con.VK_MENU,
    "shift": win32con.VK_SHIFT,
}


def _vk_code(key):
    """按键名 -> Windows 虚拟键码"""
    if not isinstance(key, str) or not key:
        raise ValueError(f"按键名必须是非空字符串，收到 {key!r}")
    k = key.strip().lower()
    if k in _WIN_VK:
        return _WIN_VK[k]
    if len(k) == 1 and k.isalnum():
        return ord(k.upper())
    if k[0] == "f" and k[1:].isdigit():          # f1 ~ f24
        return win32con.VK_F1 + int(k[1:]) - 1
    res = win32api.VkKeyScan(k)                  # 其他单个字符（符号等）
    if res != -1:
        return res & 0xFF
    raise ValueError(f"不支持的按键名: {key!r}")


def _key_lparam(vk, up=False):
    """构造键盘消息 lParam：重复次数 1 + 扫描码；抬起时补过渡/释放标志位"""
    scan = win32api.MapVirtualKey(vk, 0)
    lparam = 1 | (scan << 16)
    if up:
        lparam |= (1 << 30) | (1 << 31)
    return lparam & 0xFFFFFFFF


def _post_key(hwnd, vk, up=False):
    msg = win32con.WM_KEYUP if up else win32con.WM_KEYDOWN
    win32gui.PostMessage(hwnd, msg, vk, _key_lparam(vk, up))


def windows_key(hwnd, key, delay=0.05):
    """向窗口投递一次按键（按下并抬起），不用置顶窗口

    ⚠️ 局限：PostMessage 不更新系统键盘状态表（GetKeyState /
    GetAsyncKeyState），依赖修饰键状态的游戏热键（如 Ctrl+A）识别不到，
    会退化成普通字符。带修饰键的组合键请用 hotkey（真实注入）。

    :param key: 按键名，如 'f9'、'esc'、'a'
    :param delay: 按下与抬起之间的间隔秒数（走 human_delay，可被终止信号打断）
    """
    _check_hwnd(hwnd)
    vk = _vk_code(key)
    _post_key(hwnd, vk)
    if delay:
        human_delay(delay)
    _post_key(hwnd, vk, up=True)


def windows_hotkey(hwnd, *keys, delay=0.1):
    """向窗口投递组合键（按下并抬起），不用置顶窗口

    ⚠️ 同 windows_key 的局限：只对「处理窗口消息且不查键盘状态表」的
    控件可靠；游戏热键请用 hotkey。

    :param keys: 修饰键在前、普通键在后，如 windows_hotkey(hwnd, 'alt', 'e')
    :param delay: 组合键前的等待秒数
    """
    _check_hwnd(hwnd)
    if not keys:
        raise ValueError("组合键至少需要一个按键")
    vks = [_vk_code(k) for k in keys]
    if delay:
        human_delay(delay)
    for vk in vks:
        _post_key(hwnd, vk)
        human_delay(0.05)
    for vk in reversed(vks):
        _post_key(hwnd, vk, up=True)
        human_delay(0.05)

# ---------- Windows 消息级输入（后台操作，不需要把窗口置顶） ----------
# 通过 PostMessage 直接向目标窗口投递鼠标消息，窗口在后台也能收到；
# 坐标一律是窗口客户区坐标（左上角为原点），与模板匹配得到的坐标同坐标系。


def MAKELPARAM(x, y):
    """把客户区坐标打包成消息 lParam（低 16 位 = x，高 16 位 = y）"""
    return win32api.MAKELONG(x, y)


def _check_message_target(hwnd, x, y):
    """校验 hwnd 有效性与坐标 16 位范围，非法参数尽早抛错

    点击类函数（windows_click / windows_right_click）还会用 _check_click_target
    再校验客户区范围；windows_move_to 允许移到窗口外（"把光标挪开"场景）。
    """
    _check_hwnd(hwnd)
    if not (isinstance(x, int) and isinstance(y, int)):
        raise TypeError(f"坐标必须是整数，收到 x={x!r}, y={y!r}")
    # lParam 只有 16 位/轴，负数会被错误回绕
    if not (0 <= x <= 0xFFFF and 0 <= y <= 0xFFFF):
        raise ValueError(f"坐标超出 16 位范围: x={x}, y={y}")


# 记录每个窗口上次消息移动的终点，作为下次渐进移动的起点（粗略模拟光标状态）
_last_msg_pos = {}


def _post_mouse_move(hwnd, x, y):
    win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, MAKELPARAM(x, y))


def _interpolate_move(post_fn, sx, sy, ex, ey, steps, interval):
    """从 (sx, sy) 到 (ex, ey) 逐点投递，模拟渐进移动；steps<=1 或原地时直接跳"""
    if steps <= 1 or (sx == ex and sy == ey):
        post_fn(ex, ey)
        return
    for i in range(1, steps + 1):
        t = i / steps
        px = int(round(sx + (ex - sx) * t))
        py = int(round(sy + (ey - sy) * t))
        post_fn(px, py)
        time.sleep(interval)


def windows_move_to(hwnd, x, y, steps=None, interval=0.01):
    """把光标消息渐进移动到窗口客户区 (x, y)，不实际挪动系统鼠标

    直接跳变的单个 WM_MOUSEMOVE 不足以触发某些 UI 的悬停/离开过渡
    （如消除鼠标提示框），这里按 steps 个中间点渐进移动。
    起点=该窗口上次消息移动的终点；首次无记录时退化为直接跳转。

    :param steps: 中间点数，缺省按距离每 20px 一点，最多 30 点
    :param interval: 相邻两点的间隔秒数
    """
    _check_message_target(hwnd, x, y)
    sx, sy = _last_msg_pos.get(hwnd, (x, y))
    if steps is None:
        dist = max(abs(x - sx), abs(y - sy))
        steps = min(30, max(1, dist // 20))
    _interpolate_move(
        lambda px, py: (_post_mouse_move(hwnd, px, py), _last_msg_pos.__setitem__(hwnd, (px, py))),
        sx, sy, x, y, steps, interval,
    )


def _check_click_target(hwnd, x, y):
    """点击专用校验：在 16 位范围之外再校验客户区，越界点击会静默落空，必须尽早报错。

    只用于点击；windows_move_to 允许移动到窗口外（"把光标挪开"的场景）。
    """
    _check_message_target(hwnd, x, y)
    _, _, w, h = win32gui.GetClientRect(hwnd)
    if not (0 <= x < w and 0 <= y < h):
        raise ValueError(f"点击坐标超出客户区: ({x}, {y})，客户区 {w}x{h}")


def windows_click(hwnd, x, y):
    _check_click_target(hwnd, x, y)
    _post_mouse_move(hwnd, x, y)
    human_delay(0.02)
    lparam = MAKELPARAM(x, y)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    human_delay(0.05)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)


def windows_right_click(hwnd, x, y, hover_delay=0.05):
    """向窗口投递一次鼠标右键点击，不用置顶窗口。

    顺序是硬性要求：必须先用 windows_move_to 把光标消息移到 (x, y)，
    再投递 WM_RBUTTONDOWN/UP。右键消息的 lParam 只带坐标，游戏判定
    「这一下右键作用在哪个目标」时看的是悬停状态——它由 WM_MOUSEMOVE
    更新出来的格子/对象决定。省掉移动这一步，游戏侧没有悬停目标，
    右键会被静默丢弃（背包开着却用不了物品、右键司南没反应），
    日志里看不出任何错误。

    :param hover_delay: 移动到目标后、按下右键前的停顿，给悬停状态更新的时间
    """
    _check_click_target(hwnd, x, y)
    windows_move_to(hwnd, x, y)
    if hover_delay:
        human_delay(hover_delay)
    lparam = MAKELPARAM(x, y)
    win32gui.PostMessage(hwnd, win32con.WM_RBUTTONDOWN, win32con.MK_RBUTTON, lparam)
    human_delay(0.05)
    win32gui.PostMessage(hwnd, win32con.WM_RBUTTONUP, 0, lparam)


def windows_scroll(hwnd, x, y, delta):
    """在窗口客户区 (x, y) 处滚动滚轮

    :param delta: 正数向上滚、负数向下滚，通常用 ±120（一个标准齿格）
    """
    if not isinstance(delta, int) or delta == 0:
        raise ValueError(f"delta 必须是非 0 整数，收到 {delta!r}")
    # WM_MOUSEWHEEL 的 lParam 用屏幕坐标，需先从客户区换算
    sx, sy = win32gui.ClientToScreen(hwnd, (x, y))
    wparam = (delta & 0xFFFF) << 16
    win32gui.PostMessage(hwnd, win32con.WM_MOUSEWHEEL, wparam, MAKELPARAM(sx, sy))
