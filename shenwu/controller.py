import pyautogui
import win32gui
import win32con
import schedule
import time
import random
import math
from PIL import ImageGrab

from shenwu.config import *

import ctypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.2
window_width = 800
window_height = 600

fish_width_start = 350
fish_width_end = 430
fish_height_start = 100
fish_height_end = 180

class GameController:
    def __init__(self):
        self.hwnd = None
        self.window_width = 800
        self.window_height = 600
        self.hwnd_list = []

    def get_hwnd(self,hwnd, extra):
        title = win32gui.GetWindowText(hwnd)
        if ("幻唐志" in title) and ("RENDER" not in title):
            self.hwnd_list.append(hwnd)

    def get_window_rect(self,hwnd):
        """
        获取整个窗口的桌面坐标，包括标题栏和边框
        返回: (left, top, right, bottom)
        """
        return win32gui.GetWindowRect(hwnd)

    def get_client_rect(self,hwnd):
        """
        获取窗口客户区的桌面坐标，不包括标题栏和边框
        返回: (left, top, right, bottom)
        """
        left, top = win32gui.ClientToScreen(hwnd, (0, 0))
        rect = win32gui.GetClientRect(hwnd)
        right = left + rect[2]
        bottom = top + rect[3]
        return left, top, right, bottom

    def human_delay(self,base_seconds: float, sigma: float = 0.3) -> float:
        """模拟人类操作延迟，base_seconds 为中位数"""
        return max(0.05, random.lognormvariate(math.log(base_seconds), sigma))

    # 自动设置回合数
    def auto_reset_round(self):
        time.sleep(self.human_delay(0.4))

        pyautogui.keyDown('ctrl')
        time.sleep(self.human_delay(0.08))    

        pyautogui.keyDown('a')
        time.sleep(self.human_delay(0.05))

        pyautogui.keyUp('a')
        time.sleep(self.human_delay(0.06))    

        pyautogui.keyUp('ctrl')

    def run_xun_you(self):
        win32gui.EnumWindows(self.get_hwnd, None)
        assert self.hwnd_list , "幻唐志窗口未找到"

        for hwnd in self.hwnd_list:
            # 检测战斗
            # is_in_fight_flag = True
            find_dialogue_flag = True

            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)

            self.auto_reset_round()

            left, top, right, bottom = self.get_client_rect(hwnd)
            time.sleep(self.human_delay(1))

            ### 下面的代码不用，因为只要不是第一次打巡游，都可以只识别对话框就行
            # loop_count = 0
            # while is_in_fight_flag:
            #     loop_count += 1
            #     print(f"🔄 巡游是否在战斗中检测中... 第{loop_count}次")
            #     game_image = ImageGrab.grab(bbox=(left + window_width // 2, top, left + window_width, top + window_height // 2))

            #     try:
            #         in_fight_location = pyautogui.locate(str(hui_he_path),game_image, grayscale=True,confidence=0.5)
            #         time.sleep(self.human_delay(10))

            #     except Exception as e:
            #         print("✅ 回合标志消失，退出战斗循环")
            #         pyautogui.press('esc')
            #         self.auto_reset_round()

            #         is_in_fight_flag = False

            # 检测战斗结束,开始寻找任务栏
            # game_image = ImageGrab.grab(bbox=(left, top, left + window_width, top + window_height))

            # try:
            #     task_location = pyautogui.locate(str(xun_you_npc_path),game_image, grayscale=True,confidence=0.5)
            #     abs_x = left + task_location.left + task_location.width // 2 + 20
            #     abs_y = top + task_location.top + task_location.height // 2

            #     pyautogui.moveTo(abs_x,abs_y, duration=self.human_delay(0.2))
            #     pyautogui.click()

            #     time.sleep(self.human_delay(1))
            # except Exception as e:
            #     print(f"未找到任务的巡游任务 {e}")

            # 点击对话框，进入战斗

            while find_dialogue_flag:
                game_image = ImageGrab.grab(bbox=(left, top, left + window_width, top + window_height))

                try:
                    start_fight_location = pyautogui.locate(str(xun_you_start_fight_path),game_image, grayscale=True,confidence=0.5)
                    abs_x = left + start_fight_location.left + start_fight_location.width // 2
                    abs_y = top + start_fight_location.top + start_fight_location.height // 2

                    pyautogui.moveTo(abs_x,abs_y, duration=self.human_delay(0.2))
                    pyautogui.click()
                    time.sleep(self.human_delay(5))
                    find_dialogue_flag = False

                except Exception as e:
                    print(f"未找到巡游任务的开始战斗对话框 {e}")
                    find_dialogue_flag = False
                    time.sleep(self.human_delay(1))

    def run_fish(self):
        win32gui.EnumWindows(self.get_hwnd, None)
        assert len(self.hwnd_list) , "钓鱼只支持1个窗口"

        hwnd = self.hwnd_list[0]
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)

        # 抛竿
        pyautogui.press('f1')
        pyautogui.PAUSE = self.human_delay(4)
        pyautogui.press('f1')

        has_fish = True
        left, top, right, bottom = self.get_client_rect(hwnd)
        time.sleep(self.human_delay(1))

        while has_fish:
            game_image = ImageGrab.grab(bbox=(left+fish_width_start,top+ fish_height_start, left+fish_width_end, top+fish_height_end))
            game_image.save("game_screenshot.png")

            try:
                start_fight_location = pyautogui.locate(str(you_yu_path),game_image, grayscale=True,confidence=0.7)
                abs_x = left + start_fight_location.left + start_fight_location.width // 2
                abs_y = top + start_fight_location.top + start_fight_location.height // 2

                pyautogui.moveTo(abs_x,abs_y, duration=self.human_delay(0.2))
                pyautogui.click()
                time.sleep(self.human_delay(1))
                has_fish = False

            except Exception as e:
                print(f"还未钓到鱼 {e}")
                has_fish = False
                time.sleep(self.human_delay(1))

# pyautogui.rightClick()
# pyautogui.doubleClick()

# # 移动一段距离：向右 100，向下 50
# pyautogui.moveRel(100, 50, duration=0.2)

# # 按住左键拖动
# pyautogui.moveTo(700, 400)
# pyautogui.dragTo(900, 600, duration=0.5)

# # 滚轮
# pyautogui.scroll(3)   