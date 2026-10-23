"""窗口截图：用 Windows Graphics Capture 抓客户区，返回 BGR numpy 数组。

职责边界：只负责「窗口 -> 一帧图像」，不裁剪业务 ROI、不做识别。
WGC 的优势：窗口无需置顶、被其他窗口遮挡也能抓到；最小化窗口无效。
"""

import ctypes
import win32gui
from ctypes import wintypes

import cv2
from windows_capture import WindowsCapture, Frame

dwmapi = ctypes.windll.dwmapi
DWMWA_EXTENDED_FRAME_BOUNDS = 9   # 可见边界（不含透明调整边框/阴影）


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


def get_offsets(hwnd):
    # 1. 可见边界
    r = RECT()
    dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r))
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
