import ctypes
import win32api
import win32gui
import win32con
from ctypes import wintypes
from windows_capture import WindowsCapture, Frame

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

import time
import threading
import cv2
import random
import math
import numpy as np
from PIL import ImageGrab

# ---------- 「终止」信号（GUI 的停止按钮用） ----------
# 置位后 human_delay 会在下一片睡眠（最多 0.1s）内抛 TaskTerminated，把当前任务
# 从任意调用深度立即打断；命令行从不置位，行为与原来完全一致。
terminate_event = threading.Event()


class TaskTerminated(BaseException):
    """用户请求立即终止。

    继承 BaseException 而不是 Exception，是为了绕过业务代码里
    「except Exception」的逐窗口兜底，把终止信号一路传回任务线程。
    """


def request_terminate():
    terminate_event.set()


def clear_terminate():
    terminate_event.clear()


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

def rand_secs(base_seconds: float, sigma: float = 0.3) -> float:
    """生成一条人类化的随机等待秒数，base_seconds 为中位数"""
    return max(0.05, random.lognormvariate(math.log(base_seconds), sigma))

def human_delay(base_seconds: float, sigma: float = 0.3) -> None:
    """睡眠一段人类化的随机时间；需要拿到秒数本身时用 rand_secs。

    睡眠按最多 0.1s 一片切分，每片之间检查终止信号 —— 收到「终止」立即抛
    TaskTerminated，让 wait_until / 业务循环当场退出，而不是睡完这一觉。
    """
    deadline = time.monotonic() + rand_secs(base_seconds, sigma)
    while True:
        if terminate_event.is_set():
            raise TaskTerminated("用户请求终止")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.1, remaining))

# 仅 legacy/ 使用
# 根据hwnd获和尺寸取窗口的image
def get_hwnd_image(hwnd):
    left, top, right, bottom = get_client_rect(hwnd)
    game_image = ImageGrab.grab(bbox=(left, top, right, bottom))
    return game_image

def set_current_top(hwnd):
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except: 
        pass

# 仅 legacy/ 使用
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

# ---------- 键盘输入（真实注入，作用于前台窗口） ----------
# 游戏判定组合键（如 Ctrl+A 重置回合）依赖系统键盘状态表，PostMessage
# 不更新该状态表（修饰键按下了游戏也看不见），因此游戏热键必须真实注入；
# hwnd 参数用于先把目标窗口带到前台，保证按键落入目标窗口。

def _send_key(vk, up=False):
    scan = win32api.MapVirtualKey(vk, 0)
    flags = win32con.KEYEVENTF_KEYUP if up else 0
    win32api.keybd_event(vk, scan, flags, 0)

def press_key(key, delay=0.1, hwnd=None):
    """按一下单个键（真实键盘注入）

    :param key: 按键名，见 _vk_code
    :param hwnd: 给了就先把这个窗口带到前台，保证按键落入目标窗口
    :param delay: 注入前的等待秒数；按下与抬起之间固定间隔 0.05s
    """
    vk = _vk_code(key)
    if hwnd is not None:
        _check_hwnd(hwnd)
        set_current_top(hwnd)
    if delay:
        human_delay(delay)
    _send_key(vk)
    human_delay(0.05)
    _send_key(vk, up=True)

def hotkey(*keys, delay=0.1, hwnd=None):
    """组合键（真实键盘注入），修饰键在前、普通键在后，如 hotkey('ctrl', 'a')

    游戏按系统键盘状态识别修饰键，必须真实注入；hwnd 给了就先带到前台。

    :param keys: 修饰键在前、普通键在后
    :param hwnd: 先带到前台的目标窗口
    :param delay: 组合键前的等待秒数
    """
    if not keys:
        raise ValueError("组合键至少需要一个按键")
    vks = [_vk_code(k) for k in keys]
    if hwnd is not None:
        _check_hwnd(hwnd)
        set_current_top(hwnd)
    if delay:
        human_delay(delay)
    for vk in vks:
        _send_key(vk)
        human_delay(0.05)
    for vk in reversed(vks):
        _send_key(vk, up=True)
        human_delay(0.05)

# 仅 legacy/ 使用
def get_abs_x_y(best_bbox,left,top):
    bbox = np.array(best_bbox)
    center_x = np.mean(bbox[:, 0])
    center_y = np.mean(bbox[:, 1])
    abs_x = left + center_x
    abs_y = top + center_y
    return abs_x,abs_y

def get_abs_x_y_cv(best_bbox,left,top):
    x, y, w, h = best_bbox
    center_x = int(x + w / 2)
    center_y = int(y + h / 2)

    abs_x = left + center_x
    abs_y = top + center_y
    return abs_x,abs_y

def get_abs_x_y_cv_windows(best_bbox):
    x, y, w, h = best_bbox
    center_x = int(x + w / 2)
    center_y = int(y + h / 2)

    return center_x,center_y

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

# 仅 legacy/ 使用
def check_is_frozen(
    hwnd,
    pixel_diff_thresh=25,
    frozen_ratio_thresh=0.2,
):
    """通过对比两张截图判断画面是否静止

    :param img_before: PIL Image 或 numpy 数组（前一帧）
    :param img_after:  PIL Image 或 numpy 数组（后一帧）
    :param pixel_diff_thresh: 灰度变化阈值（0-255），用于过滤微小杂色与压缩噪点
    :param frozen_ratio_thresh: 变化像素占比下限（0.001 即 0.1%），低于此值视作静止
    :return: True (卡住/静止), False (画面在动)
    """
    left, top, right, bottom = get_client_rect(hwnd)
    time.sleep(10)

    img_before = ImageGrab.grab(bbox=(left,top , right, bottom))

    # 2. 保持业务执行或等待检测窗口
    time.sleep(10.0)
    img_after = ImageGrab.grab(bbox=(left,top , right, bottom))

    # 统一转换为 numpy 灰度图
    arr1 = (
        np.array(img_before)
        if not isinstance(img_before, np.ndarray)
        else img_before
    )
    arr2 = (
        np.array(img_after)
        if not isinstance(img_after, np.ndarray)
        else img_after
    )

    gray1 = (
        cv2.cvtColor(arr1, cv2.COLOR_RGB2GRAY)
        if len(arr1.shape) == 3
        else arr1
    )
    gray2 = (
        cv2.cvtColor(arr2, cv2.COLOR_RGB2GRAY)
        if len(arr2.shape) == 3
        else arr2
    )

    # 1. 计算两帧像素绝对差分
    diff = cv2.absdiff(gray1, gray2)

    # 2. 阈值化：只有像素亮度变化超过阈值才算有效运动
    _, thresh = cv2.threshold(
        diff, pixel_diff_thresh, 255, cv2.THRESH_BINARY
    )

    # 3. 计算发生变动的像素比例
    changed_pixels = np.count_nonzero(thresh)
    total_pixels = thresh.size
    change_ratio = changed_pixels / total_pixels

    # 若变化像素比例极小，判定为画面冻结
    return change_ratio < frozen_ratio_thresh, change_ratio

def make_region(hwnd):
    """构造截图/坐标换算用的 region：窗口客户区在屏幕上的位置 + hwnd

    region["left"]/["top"] 是客户区左上角的屏幕坐标（帧内 bbox 加上它们
    即得屏幕绝对坐标，供真实鼠标点击用）；region["hwnd"] 供 WGC 截图用。
    """
    left, top, right, bottom = get_client_rect(hwnd)
    if right - left <= 0 or bottom - top <= 0:
        raise ValueError("窗口客户区大小异常，可能窗口最小化或不可见")
    return {"hwnd": hwnd, "left": int(left), "top": int(top)}

def find_best_match(image, templ, threshold, scale=None):
    """
    在 image 中模板匹配。

    返回:
        {
            "bbox": (x, y, w, h),
            "score": 匹配分数,
            "scale": 缩放比例
        }

    或 None
    """
    if scale is None:
        scale = 1.0

    best = None

    scale = float(scale)

    h = int(round(templ.shape[0] * scale))
    w = int(round(templ.shape[1] * scale))

    if h <= 0 or w <= 0:
        return None

    if h > image.shape[0] or w > image.shape[1]:
        return None

    if abs(scale - 1.0) < 1e-6:
        resized_templ = templ
    else:
        interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        resized_templ = cv2.resize(templ, (w, h), interpolation=interp)

    result = cv2.matchTemplate(
        image,
        resized_templ,
        cv2.TM_CCOEFF_NORMED
    )

    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val >= threshold:
        if best is None or max_val > best["score"]:
            best = {
                "bbox": (
                    int(max_loc[0]),
                    int(max_loc[1]),
                    w,
                    h
                ),
                "score": float(max_val),
                "scale": scale
            }

    return best

def find_all_match(image, templ, threshold, scale=None, nms_iou=0.3):
    """
    在 image 中模板匹配，返回所有命中阈值的结果（同 find_best_match，但不止最佳一个）。

    同一目标周围会有一片相邻像素都超过阈值，用简单 NMS 去重，
    只保留每个目标的局部峰值。

    返回:
        [{"bbox": (x, y, w, h), "score": 匹配分数, "scale": 缩放比例}, ...]

    无匹配时返回空列表 []
    """
    if scale is None:
        scale = 1.0

    scale = float(scale)

    h = int(round(templ.shape[0] * scale))
    w = int(round(templ.shape[1] * scale))

    if h <= 0 or w <= 0:
        return []

    if h > image.shape[0] or w > image.shape[1]:
        return []

    if abs(scale - 1.0) < 1e-6:
        resized_templ = templ
    else:
        interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        resized_templ = cv2.resize(templ, (w, h), interpolation=interp)

    result = cv2.matchTemplate(
        image,
        resized_templ,
        cv2.TM_CCOEFF_NORMED
    )

    # 所有超过阈值的像素位置作为候选
    ys, xs = np.where(result >= threshold)
    if len(xs) == 0:
        return []

    # 按分数从高到低排序，做 NMS 去掉同一目标的相邻重复命中
    order = np.argsort(result[ys, xs])[::-1]
    kept = []
    for idx in order:
        x, y = int(xs[idx]), int(ys[idx])
        candidate = {"bbox": (x, y, w, h), "score": float(result[y, x]), "scale": scale}
        # 与已保留的框算 IoU，重叠大说明是同一个目标的相邻像素
        duplicate = False
        for item in kept:
            ix1, iy1 = max(x, item["bbox"][0]), max(y, item["bbox"][1])
            ix2 = min(x + w, item["bbox"][0] + w)
            iy2 = min(y + h, item["bbox"][1] + h)
            inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            iou = inter / (2 * w * h - inter) if inter > 0 else 0.0
            if iou > nms_iou:
                duplicate = True
                break
        if not duplicate:
            kept.append(candidate)

    return kept

def restore_window(hwnd):
    """恢复最小化的窗口（不抢前台）。WGC 截图要求窗口非最小化"""
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    except Exception:
        pass

def keep_largest_component(mask: np.ndarray) -> np.ndarray:
    """
    只保留二值mask中面积最大的连通域
    :param mask: uint8 二值图 (0/255)
    :return: 仅含最大连通域的 uint8 二值图
    """
    # 确保输入是二值图
    if mask.dtype != np.uint8:
        mask = (mask > 0).astype(np.uint8) * 255

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return np.zeros_like(mask)

    # 找面积最大的轮廓
    largest = max(contours, key=cv2.contourArea)

    # 创建纯黑mask，仅绘制最大轮廓（填充）
    result = np.zeros_like(mask)
    cv2.drawContours(result, [largest], -1, 255, thickness=cv2.FILLED)

    return result

def get_color(frame,color=None,radio=1):
    game_image_array = np.array(frame)
    h,w = game_image_array.shape[:2]

    x1, y1 = int(w * 0.66), int(h * 0.27)
    x2, y2 = int(w * 0.95), int(h * 0.38)
    frame = game_image_array[y1:y2,x1:x2]

    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
    
    if color == "blue":
        lower = np.array([85,  100, 150])
        upper = np.array([130, 255, 255])
        mask  = cv2.inRange(hsv, lower, upper)
    elif color == "yellow":
        lower = np.array([20, 100, 150])
        upper = np.array([45, 255, 255])
        mask = cv2.inRange(hsv, lower, upper)
    elif color == "red":
        lower_red1 = np.array([0,   120, 150])   # 红色段1: H=0~10
        upper_red1 = np.array([10,  255, 255])

        lower_red2 = np.array([170, 120, 150])   # 红色段2: H=170~180
        upper_red2 = np.array([180, 255, 255])

        mask_red1 = cv2.inRange(hsv, lower_red1, upper_red1)
        mask_red2 = cv2.inRange(hsv, lower_red2, upper_red2)
        mask  = cv2.bitwise_or(mask_red1, mask_red2)  # 两段合并
    else:
        raise ValueError(f"不支持的颜色: {color}")

    mask = keep_largest_component(mask)

    # 先闭运算：连接相近的文字像素
    kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5))
    mask_closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close)

    # 再开运算：去除细小噪点
    kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask_clean = cv2.morphologyEx(mask_closed, cv2.MORPH_OPEN, kernel_open)    

    contours, _ = cv2.findContours(
        mask_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    if not contours:
        return None

    x, y, cw, ch = cv2.boundingRect(contours[0])
    return x + x1, y + y1, cw, ch

# 获取提交任务的物品格子坐标
def generate_grid_mask(img,radio, template_path=None):
    h, w = img.shape[:2]

    # 2. 获取 40 个格子的矩形坐标 (x1, y1, x2, y2)
    if template_path:
        # 【方式 A：模板匹配动态定位】适合窗口位置可能发生移动的情况
        template = cv2.imread(template_path)
        res = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        
        anchor_x, anchor_y = max_loc
        # 根据“给予物品”按钮左上角的相对偏移量（根据截图分辨率微调）
        x1 = anchor_x - 32
        y1 = anchor_y + 35
        x2 = x1 + 203   # 40格区域整体宽度
        y2 = y1 + 324   # 40格区域整体高度
    else:
        # 【方式 B：直接基于原图比例/坐标切片】适合固定分辨率截图
        # 下述比例匹配你提供的游戏截图分辨率
        x1 = int(w * 0.48)
        y1 = int(h * 0.191)
        x2 = int(w * 0.778)
        y2 = int(h * 0.830)

    mask = np.zeros((h, w), dtype=np.uint8)
    mask[y1:y2, x1:x2] = 255
    masked_img = cv2.bitwise_and(img, img, mask=mask)

    # 3. 将遮罩后的图像转为 HSV 格式进行色彩和亮度提取
    hsv = cv2.cvtColor(masked_img, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)

    # 4. 提取高亮区域的条件
    # - 高亮：由于未置灰，原本的高光和浅色能够达到 V > 210
    # - 饱和度：S > 70（过滤掉 F3、数字等黄白/单色噪点）
    _, thresh_v = cv2.threshold(v, 140, 255, cv2.THRESH_BINARY)
    _, thresh_s = cv2.threshold(s, 0, 255, cv2.THRESH_BINARY)
    high_light_mask = cv2.bitwise_and(thresh_v, thresh_s)

    # 5. 形态学膨胀 (Dilation) 使碎片高光连成整体的道具块
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (11, 11))
    processed_mask = cv2.dilate(high_light_mask, kernel, iterations=1)

    # 6. 查找轮廓，定位所有高亮物品
    contours, _ = cv2.findContours(processed_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    detected_targets = []

    for cnt in contours:
        area = cv2.contourArea(cnt)
        # 过滤掉过小或过大的噪点轮廓（正常一格内高亮面积为 300 ~ 2500 像素）
        if 300*radio < area < 3000*radio:
            x, y, w, h = cv2.boundingRect(cnt)
            
            # 计算点击中心点
            cx = x + w // 2
            cy = y + h // 2
            
            # 保存定位数据
            target_info = {
                "x1": x, "y1": y, "x2": x + w, "y2": y + h,
                "center": (cx, cy)
            }
            detected_targets.append(target_info)

    # 8. 打印坐标，并保存结果
    print(f"检测到 {len(detected_targets)} 个高亮物品：")
    return detected_targets


# ---------- Windows 消息级输入（后台操作，不需要把窗口置顶） ----------
# 通过 PostMessage 直接向目标窗口投递鼠标消息，窗口在后台也能收到；
# 坐标一律是窗口客户区坐标（左上角为原点），与模板匹配得到的坐标同坐标系。

def MAKELPARAM(x, y):
    """把客户区坐标打包成消息 lParam（低 16 位 = x，高 16 位 = y）"""
    return win32api.MAKELONG(x, y)

def _check_message_target(hwnd, x, y):
    """校验 hwnd 有效性与客户区坐标范围，非法参数尽早抛错"""
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

def move_cursor_to(hwnd, x, y, steps=None, interval=0.01):
    """把真实系统光标渐进移动到窗口客户区 (x, y) 对应的屏幕位置

    适用于游戏轮询 GetCursorPos()/原始输入（而非消息队列）的情况：
    只有真实光标变化才能触发这类游戏的悬停判定。不改变窗口焦点。
    注意：会占用真实鼠标，多窗口并行时同一时刻只能对一个窗口生效。

    :param steps: 中间点数，缺省按距离每 20px 一点，最多 30 点
    :param interval: 相邻两点的间隔秒数
    """
    _check_message_target(hwnd, x, y)
    ex, ey = win32gui.ClientToScreen(hwnd, (x, y))
    sx, sy = win32api.GetCursorPos()
    if steps is None:
        dist = max(abs(ex - sx), abs(ey - sy))
        steps = min(30, max(1, dist // 20))
    _interpolate_move(
        lambda px, py: win32api.SetCursorPos((px, py)),
        sx, sy, ex, ey, steps, interval,
    )

def windows_click(hwnd, x, y):
    _post_mouse_move(hwnd, x, y)
    human_delay(0.02)
    lparam = MAKELPARAM(x, y)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    human_delay(0.05)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)

def windows_right_click(hwnd, x, y):
    """向窗口投递一次鼠标右键点击，不用置顶窗口"""
    _check_message_target(hwnd, x, y)
    # _post_mouse_move(hwnd, x, y)
    human_delay(0.02)
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

dwmapi = ctypes.windll.dwmapi
DWMWA_EXTENDED_FRAME_BOUNDS = 9   # 可见边界（不含透明调整边框/阴影）

class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

def get_offsets(hwnd):
    # 1. 可见边界
    r = RECT()
    dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS,ctypes.byref(r), ctypes.sizeof(r))
    # 2. 客户区左上角的屏幕坐标
    cx, cy = win32gui.ClientToScreen(hwnd, (0, 0))
    # 3. 客户区尺寸
    cl, ct, cr, cb = win32gui.GetClientRect(hwnd)
    client_w, client_h = cr - cl, cb - ct
    # 4. 客户区相对"可见边界"的偏移（这才是 WGC 帧里的真实偏移）
    return client_w, client_h, cx - r.left, cy - r.top

def capture_client_only(hwnd, save_path=None):
    """用 Windows Graphics Capture 抓取窗口客户区，返回 BGR numpy 数组
    （shape=(client_h, client_w, 3)）。窗口无需置顶、可被遮挡，不受
    其他窗口覆盖影响。save_path 给了才顺手存一张，不给就全程不落盘。
    """
    client_w, client_h, offset_x, offset_y = get_offsets(hwnd)

    capture = WindowsCapture(cursor_capture=False, draw_border=False,
                             window_hwnd=hwnd)
    result = {}          # 用字典把数组带出回调（闭包写外层变量需要可变容器）

    @capture.event
    def on_frame_arrived(frame: Frame, ctrl):
        w, h = frame.width, frame.height
        # Frame -> numpy：convert_to_bgr() 返回的是 Frame，必须再取 .frame_buffer
        bgr_full = frame.convert_to_bgr().frame_buffer   # ndarray (h, w, 3)

        # 裁掉标题栏与边框（切片越界会静默变短，先夹取）
        y0 = max(0, min(offset_y, h))
        x0 = max(0, min(offset_x, w))
        bgr = bgr_full[y0:y0 + client_h, x0:x0 + client_w]

        result["bgr"] = bgr.copy()          # copy 一份，脱离内部缓冲区
        if save_path:
            cv2.imwrite(save_path, bgr)

        ctrl.stop()

    @capture.event
    def on_closed():
        pass

    capture.start()      # 阻塞，直到 ctrl.stop() 被调用

    if "bgr" not in result:
        raise RuntimeError("未收到任何帧：窗口可能已关闭或捕获异常终止")
    return result["bgr"]