"""兼容层 + 通用杂项。

底层能力已按职责拆分：
- shenwu.timing      —— 终止信号、human_delay / rand_secs
- shenwu.game_window —— 窗口识别（标题解析）、客户区几何、region
- shenwu.vision      —— 模板匹配、颜色/格子识别（纯计算）
- shenwu.win_input   —— 键鼠输入（消息级 + 真实注入）
- shenwu.capture     —— WGC 客户区截图

本模块保留历史入口（`from shenwu.utils import X` 仍然可用）以及尚未归类的
通用函数（坐标换算、legacy 截图/冻结检测）。新增代码请直接引用上面的模块，
不要再往这里堆逻辑。
"""

import time

import cv2
import numpy as np
from PIL import ImageGrab

from shenwu.timing import (  # noqa: F401  (兼容导出)
    TaskTerminated, terminate_event, request_terminate, clear_terminate,
    bind_thread_terminate, rand_secs, human_delay,
)
from shenwu.game_window import (  # noqa: F401  (兼容导出)
    GAME_TITLE_PATTERN, SHELL_WINDOW_CLASSES, SHELL_TITLE_BLACKLIST, parse_game_title,
    get_client_rect, get_physical_client_rect, make_region, restore_window, set_current_top,
)
from shenwu.vision import (  # noqa: F401  (兼容导出)
    FIND_ALL_MAX_CANDIDATES, find_best_match, find_all_match,
    keep_largest_component, get_color, generate_grid_mask,
)
from shenwu.win_input import (  # noqa: F401  (兼容导出)
    windows_key, windows_hotkey, press_key, hotkey,
    windows_move_to, move_cursor_to, windows_click, windows_right_click, windows_scroll,
)
from shenwu.capture import get_offsets, capture_client_only  # noqa: F401  (兼容导出)


# ---------- 通用杂项 ----------

# 仅 legacy/ 使用
# 根据hwnd获和尺寸取窗口的image
def get_hwnd_image(hwnd):
    left, top, right, bottom = get_client_rect(hwnd)
    game_image = ImageGrab.grab(bbox=(left, top, right, bottom))
    return game_image


# 仅 legacy/ 使用
def get_abs_x_y(best_bbox, left, top):
    bbox = np.array(best_bbox)
    center_x = np.mean(bbox[:, 0])
    center_y = np.mean(bbox[:, 1])
    abs_x = left + center_x
    abs_y = top + center_y
    return abs_x, abs_y


def get_abs_x_y_cv(best_bbox, left, top):
    """bbox(帧内) -> 屏幕绝对坐标（真实鼠标点击用）"""
    x, y, w, h = best_bbox
    center_x = int(x + w / 2)
    center_y = int(y + h / 2)

    abs_x = left + center_x
    abs_y = top + center_y
    return abs_x, abs_y


def get_abs_x_y_cv_windows(best_bbox):
    """bbox(帧内) -> 客户区坐标（消息级点击用，不再加屏幕偏移）"""
    x, y, w, h = best_bbox
    center_x = int(x + w / 2)
    center_y = int(y + h / 2)

    return center_x, center_y


# 仅 legacy/ 使用
def check_is_frozen(
    hwnd,
    pixel_diff_thresh=25,
    frozen_ratio_thresh=0.2,
):
    """通过对比两张截图判断画面是否静止

    :param pixel_diff_thresh: 灰度变化阈值（0-255），用于过滤微小杂色与压缩噪点
    :param frozen_ratio_thresh: 变化像素占比下限（0.001 即 0.1%），低于此值视作静止
    :return: True (卡住/静止), False (画面在动)
    """
    left, top, right, bottom = get_client_rect(hwnd)
    time.sleep(10)

    img_before = ImageGrab.grab(bbox=(left, top, right, bottom))

    # 2. 保持业务执行或等待检测窗口
    time.sleep(10.0)
    img_after = ImageGrab.grab(bbox=(left, top, right, bottom))

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
