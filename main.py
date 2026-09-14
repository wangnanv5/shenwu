import pyautogui
import win32gui
import win32con
import schedule
import time
import random
import math

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.2

huan_hwnd_list = []

def get_huan_hwnd(hwnd, extra):
    global huan_hwnd_list

    if win32gui.IsWindowVisible(hwnd):
        title = win32gui.GetWindowText(hwnd)
        if "幻唐志" in title:
            huan_hwnd_list.append(hwnd)
win32gui.EnumWindows(get_huan_hwnd, None)

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
    return max(0.05, random.lognormvariate(math.log(base_seconds), sigma))

# 自动设置回合数
def job():
    if huan_hwnd_list:
        for hwnd in huan_hwnd_list:
            print("正在处理窗口")
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(human_delay(0.4))

            pyautogui.keyDown('ctrl')
            time.sleep(human_delay(0.08))    
        
            pyautogui.keyDown('a')
            time.sleep(human_delay(0.05))

            pyautogui.keyUp('a')
            time.sleep(human_delay(0.06))    

            pyautogui.keyUp('ctrl')
    else:
        print("未找到窗口")

# schedule.every(next_run).minutes.do(job)

while True:
    try:
        schedule.run_pending()
        job()
        delay = human_delay(200, sigma=0.15)  # 10分钟 ± ~15%
        print(f"下次执行: {delay:.1f} 秒后")
        time.sleep(delay)
    except Exception as e:
        print(e)
   

# 客户区大小
# rect = win32gui.GetClientRect(huan_hwnd)
# width = rect[2]
# height = rect[3]

# right = left + width
# bottom = top + height

# img = ImageGrab.grab(bbox=(left, top, right, bottom))
# img.save("game_screenshot.png")

# while True:
#     time.sleep(0.1)
#     pyautogui.press('esc')
# pyautogui.moveTo(803, 869, duration=0.2)

# while True:
#     random_number = random.uniform(0.01, 0.11)
#     time.sleep(random_number)
#     pyautogui.click()

# pyautogui.rightClick()
# pyautogui.doubleClick()

# # 移动一段距离：向右 100，向下 50
# pyautogui.moveRel(100, 50, duration=0.2)

# # 按住左键拖动
# pyautogui.moveTo(700, 400)
# pyautogui.dragTo(900, 600, duration=0.5)

# # 滚轮
# pyautogui.scroll(3)