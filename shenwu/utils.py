import pyautogui
import win32gui
import win32con
import time
import cv2
import random
import math
import numpy as np
from PIL import ImageGrab

def get_window_rect(hwnd):
        """
        获取整个窗口的桌面坐标，包括标题栏和边框
        返回: (left, top, right, bottom)
        """
        return win32gui.GetWindowRect(hwnd)

def get_window_rect(hwnd):
    """
    获取整个窗口的桌面坐标，包括标题栏和边框
    返回: (left, top, right, bottom)
    """
    return win32gui.GetWindowRect(hwnd)

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


def human_delay(base_seconds: float, sigma: float = 0.3) -> float:
    """模拟人类操作延迟，base_seconds 为中位数"""
    return time.sleep(max(0.05, random.lognormvariate(math.log(base_seconds), sigma)))

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

def open_item_shop_keyboard():
    pyautogui.keyDown('alt')
    human_delay(0.08)    

    pyautogui.keyDown('j')
    human_delay(0.05)

    pyautogui.keyUp('j')
    human_delay(0.06)   

    pyautogui.keyUp('alt')

def auto_reset_round():
    human_delay(0.4)

    pyautogui.keyDown('ctrl')
    human_delay(0.08)  

    pyautogui.keyDown('a')
    human_delay(0.05)

    pyautogui.keyUp('a')
    human_delay(0.06) 

    pyautogui.keyUp('ctrl')

def open_calendar():
    human_delay(0.1)
    pyautogui.keyDown('alt')
    human_delay(0.1)
    pyautogui.keyDown('y')
    human_delay(0.1)
    pyautogui.keyUp('y')
    human_delay(0.1)  
    pyautogui.keyUp('alt')

def get_abs_x_y(best_bbox,left,top):
    bbox = np.array(best_bbox)
    center_x = np.mean(bbox[:, 0])
    center_y = np.mean(bbox[:, 1])
    abs_x = left + center_x
    abs_y = top + center_y
    return abs_x,abs_y

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