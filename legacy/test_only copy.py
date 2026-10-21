import win32gui
import win32con
import win32api
import time


def press_key(hwnd, vk_code, hold=0.05):
    """后台按下一个键（含完整扫描码参数）"""
    scan = win32api.MapVirtualKey(vk_code, 0)      # 虚拟键码 -> 扫描码
    lparam_down = (scan << 16) | 1                 # 重复次数=1
    lparam_up   = (scan << 16) | 0xC0000001        # 位30=1(曾按下) 位31=1(释放)

    win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, vk_code, lparam_down)
    time.sleep(hold)
    win32gui.PostMessage(hwnd, win32con.WM_KEYUP, vk_code, lparam_up)


hwnd = 4588374
press_key(hwnd, win32con.VK_F9)