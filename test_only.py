import random
import math
import time

import win32gui
import win32con

import mss
import cv2
import numpy as np


# Windows 高 DPI 缩放可能导致坐标偏移，建议开启
try:
    import ctypes
    try:
        # Per-Monitor DPI Aware
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass


# =========================
# 配置区
# =========================

# 你的小图标路径
ICON_PATH = r"C:\Users\27321\shenwu\resource\Common\xun_lu.png"

# 匹配阈值，0.75~0.9 之间调
THRESHOLD = 0.85

# 是否开启多尺度匹配
# 如果图标可能因为窗口大小、DPI 缩放而变大变小，可以改成 True
USE_MULTISCALE = False

# 如果 USE_MULTISCALE = True，会使用这些缩放比例尝试匹配
SCALES = [1.5]
# SCALES = np.arange(0.8, 1.21, 0.05)

# 截图区域：
# None：捕获整个游戏窗口客户区
# (x, y, w, h)：只捕获窗口客户区内部指定区域
# 例如只截窗口内部从左上角开始的 800x600：
# ROI = (0, 0, 800, 600)
ROI = None


# =========================
# 窗口查找
# =========================

hwnd_list = []


def get_hwnd(hwnd, extra):
    title = win32gui.GetWindowText(hwnd)
    if ("幻唐志" in title) and ("RENDER" not in title):
        hwnd_list.append(hwnd)


def get_client_rect(hwnd):
    """
    获取窗口客户区在屏幕上的矩形。
    返回:
        left, top, right, bottom
    """
    left, top = win32gui.ClientToScreen(hwnd, (0, 0))
    rect = win32gui.GetClientRect(hwnd)

    right = left + rect[2]
    bottom = top + rect[3]

    return left, top, right, bottom


def human_delay(base_seconds: float, sigma: float = 0.3) -> float:
    return max(0.05, random.lognormvariate(math.log(base_seconds), sigma))

def make_mss_region(hwnd, roi=None):
    """
    根据窗口客户区生成 mss 截图区域。

    参数:
        hwnd: 窗口句柄
        roi: 可选，窗口客户区内部相对区域
             格式: (x, y, w, h)

             例如:
             roi=(0, 0, 800, 600)
             表示从窗口客户区左上角开始截 800x600

             roi=(100, 50, 640, 480)
             表示从窗口客户区内部坐标 (100, 50) 开始截 640x480

    返回:
        mss 可用的 region:
        {
            "left": ...,
            "top": ...,
            "width": ...,
            "height": ...
        }
    """
    left, top, right, bottom = get_client_rect(hwnd)

    win_left = int(left)
    win_top = int(top)
    win_w = int(right - left)
    win_h = int(bottom - top)

    if win_w <= 0 or win_h <= 0:
        raise ValueError("窗口客户区大小异常，可能窗口最小化或不可见")

    if roi is None:
        x = 0
        y = 0
        w = win_w
        h = win_h
    else:
        x, y, w, h = roi
        x = int(x)
        y = int(y)
        w = int(w)
        h = int(h)

        # 防止超出窗口客户区
        x = max(0, min(x, win_w - 1))
        y = max(0, min(y, win_h - 1))
        w = max(0, min(w, win_w - x))
        h = max(0, min(h, win_h - y))

    if w <= 0 or h <= 0:
        raise ValueError("截图区域无效，宽或高为 0")

    region = {
        "left": win_left + x,
        "top": win_top + y,
        "width": w,
        "height": h
    }

    return region


# =========================
# OpenCV 模板匹配
# =========================

def load_icon(path):
    icon = cv2.imread(path, cv2.IMREAD_COLOR)
    if icon is None:
        raise FileNotFoundError(f"无法读取图标: {path}")
    return icon


def find_best_match(image, templ, threshold, scales=None):
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
    if scales is None:
        scales = [1.0]

    best = None

    for scale in scales:
        scale = float(scale)

        h = int(round(templ.shape[0] * scale))
        w = int(round(templ.shape[1] * scale))

        if h <= 0 or w <= 0:
            continue

        if h > image.shape[0] or w > image.shape[1]:
            continue

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


# =========================
# 主流程
# =========================

def main():
    icon = load_icon(ICON_PATH)

    hwnd_list.clear()
    win32gui.EnumWindows(get_hwnd, None)

    if not hwnd_list:
        raise RuntimeError("没有找到目标窗口：幻唐志")

    hwnd = hwnd_list[0]

    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception as e:
        print("置前窗口失败，继续尝试截图：", e)

    time.sleep(human_delay(1))

    with mss.mss() as sct:
        while True:
            try:
                # 每帧重新获取窗口区域，窗口移动也能跟上
                region = make_mss_region(hwnd, ROI)
            except Exception as e:
                print(e)
                time.sleep(1)
                continue

            # 只捕获指定窗口区域
            shot = sct.grab(region)

            frame = np.array(shot)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            icon = cv2.cvtColor(icon, cv2.COLOR_BGRA2BGR)
            icon = cv2.cvtColor(icon, cv2.COLOR_BGR2GRAY)
            # 在这个区域里做模板匹配
            match = find_best_match(
                frame,
                icon,
                THRESHOLD,
                SCALES if USE_MULTISCALE else None
            )

            if match is not None:
                x, y, w, h = match["bbox"]
                score = match["score"]
                scale = match["scale"]

                # 画 bbox
                cv2.rectangle(
                    frame,
                    (x, y),
                    (x + w, y + h),
                    (0, 255, 0),
                    2
                )

                # 画分数标签
                label = f"{score:.2f}"
                if USE_MULTISCALE:
                    label += f" x{scale:.2f}"

                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.6
                thickness = 2

                (tw, th), baseline = cv2.getTextSize(
                    label,
                    font,
                    font_scale,
                    thickness
                )

                label_y = max(y - 10, th + 10)

                cv2.rectangle(
                    frame,
                    (x, label_y - th - 8),
                    (x + tw + 8, label_y + baseline),
                    (0, 255, 0),
                    -1
                )

                cv2.putText(
                    frame,
                    label,
                    (x + 4, label_y),
                    font,
                    font_scale,
                    (0, 0, 0),
                    thickness
                )

                # 当前 bbox 是相对于截图区域 region 的坐标
                # 如果要转换成屏幕绝对坐标，需要加上 region 的 left/top
                screen_x = region["left"] + x
                screen_y = region["top"] + y

                print(
                    f"\rlocal bbox=(x={x}, y={y}, w={w}, h={h}) | "
                    f"screen top-left=({screen_x}, {screen_y}) | "
                    f"score={score:.3f} | scale={scale:.2f}   ",
                    end="",
                    flush=True
                )
            else:
                print(
                    f"\rno match | threshold={THRESHOLD:.2f}              ",
                    end="",
                    flush=True
                )

            cv2.imshow("Window Region Template Match - q to quit", frame)

            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()