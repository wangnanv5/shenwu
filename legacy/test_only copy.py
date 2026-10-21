import ctypes
from ctypes import wintypes
import win32gui
from PIL import Image
from windows_capture import WindowsCapture, Frame

ctypes.windll.user32.SetProcessDPIAware()

WINDOW_TITLE = "幻唐志"

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


def capture_client_only(window_title, save_path="client_only.png"):
    hwnd = 990966
    if not hwnd:
        raise ValueError(f"未找到窗口: {window_title}")

    client_w, client_h, offset_x, offset_y = get_offsets(hwnd)
    print(f"客户区: {client_w}x{client_h}  offset=({offset_x},{offset_y})")

    capture = WindowsCapture(cursor_capture=False, draw_border=False,window_name=window_title)
    done = {"ok": False}

    @capture.event
    def on_frame_arrived(frame: Frame, ctrl):
        w, h = frame.width, frame.height
        print(f"WGC 帧: {w}x{h}  多余宽={w-client_w} 多余高={h-client_h}")

        frame.save_as_image("raw_temp.png")
        img = Image.open("raw_temp.png")

        if (w, h) != (client_w, client_h):
            img = img.crop((offset_x, offset_y,
                            offset_x + client_w, offset_y + client_h))

        img.save(save_path)
        done["ok"] = True
        ctrl.stop()

    @capture.event
    def on_closed():
        pass

    capture.start()
    print(f"已保存: {save_path}")


capture_client_only(WINDOW_TITLE)