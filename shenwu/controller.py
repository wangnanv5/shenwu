import pyautogui
import win32gui
import win32con
import time
import random
import math
import numpy as np
from PIL import ImageGrab

from shenwu.config import *
from shenwu.ocr import Ocr

import ctypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.2
window_width = 800
window_height = 600

fish_width_start = 380
fish_width_end = 440
fish_height_start = 100
fish_height_end = 180

class GameController:
    def __init__(self):
        self.hwnd = None
        self.window_width = 800
        self.window_height = 600
        self.hwnd_list = []
        self.ocr = Ocr()

        win32gui.EnumWindows(self.get_hwnd, None)
        assert self.hwnd_list , "幻唐志窗口未找到"
        print(f"初始化成功,找到{len(self.hwnd_list)}个游戏窗口")



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

    def run_auto_reset_round(self):
        for hwnd in self.hwnd_list:

            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)

            self.auto_reset_round()
            time.sleep(self.human_delay(1))

    def run_xun_you(self):
        for hwnd in self.hwnd_list:
            # 检测战斗
            find_dialogue_flag = True

            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)

            self.auto_reset_round()

            left, top, right, bottom = self.get_client_rect(hwnd)
            time.sleep(self.human_delay(0.5))

            # 点击对话框，进入战斗
            while find_dialogue_flag:
                game_image = ImageGrab.grab(bbox=(left, top, left + window_width, top + window_height))
                try:
                    print("🔍 检测对话框中...")
                    ocr_result = self.ocr.get_ocr_from_image(game_image, "开始战斗")

                    if not ocr_result:
                        raise Exception("OCR结果为空")

                    best_bbox, best_text, best_conf = max(ocr_result, key=lambda x: x[2])
                    print(f"巡游最高置信度结果: '{best_text}' | 置信度: {best_conf:.4f}")

                    bbox = np.array(best_bbox)
                    center_x = np.mean(bbox[:, 0])
                    center_y = np.mean(bbox[:, 1])

                    abs_x = left + center_x
                    abs_y = top + center_y

                    # pyautogui.moveTo(abs_x,abs_y, duration=self.human_delay(0.2))
                    pyautogui.click(abs_x,abs_y)
                    time.sleep(self.human_delay(1))
                    # win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
                    time.sleep(self.human_delay(5))
                    find_dialogue_flag = False

                except Exception as e:
                    print(f"巡游任务报错 {e}")
                    find_dialogue_flag = False
                    time.sleep(self.human_delay(1))
                    # win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
                    time.sleep(self.human_delay(5))

    # to do
    def run_fish(self):
        win32gui.EnumWindows(self.get_hwnd, None)
        assert len(self.hwnd_list) , "钓鱼只支持1个窗口"

        hwnd = self.hwnd_list[0]
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)

        # 抛竿
        pyautogui.press('f1')
        pyautogui.PAUSE = self.human_delay(2)
        pyautogui.press('f1')

        has_fish = True
        left, top, right, bottom = self.get_client_rect(hwnd)
        time.sleep(self.human_delay(1))

        while has_fish:
            game_image = ImageGrab.grab(bbox=(left+fish_width_start,top + fish_height_start, left+fish_width_end, top+fish_height_end))

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

    # to-do
    def run_auto_task(self,task_name):
        win32gui.EnumWindows(self.get_hwnd, None)
        assert self.hwnd_list , "幻唐志窗口未找到"

        hwnd = self.hwnd_list[0]

        left, top, right, bottom = self.get_client_rect(hwnd)
        time.sleep(self.human_delay(0.5))

        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)

        # 先看看能不能找到该任务
        time.sleep(self.human_delay(1))
        game_image = ImageGrab.grab(bbox=(left, top, right, bottom))
        ocr_result = self.ocr.get_ocr_from_image(game_image, "法宝引导")

        if not ocr_result:
            raise Exception("OCR找不到此任务")

        print(f"✅ 检测到任务 {task_name}")
        best_bbox, best_text, best_conf = max(ocr_result, key=lambda x: x[2])
        bbox = np.array(best_bbox)
        center_x = np.mean(bbox[:, 0])
        center_y = np.mean(bbox[:, 1])
        abs_x = left + center_x
        abs_y = top + center_y
        pyautogui.click(abs_x,abs_y)
        time.sleep(self.human_delay(1))

    def open_calendar(self):
        time.sleep(self.human_delay(0.4))
        pyautogui.keyDown('alt')
        time.sleep(self.human_delay(0.08))    
        pyautogui.keyDown('y')
        time.sleep(self.human_delay(0.05))
        pyautogui.keyUp('y')
        time.sleep(self.human_delay(0.06))    
        pyautogui.keyUp('alt')

    def set_current_top(self,hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)

    def set_hide_window(self,hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_HIDE)

    def run_shi_men(self):
        hwnd = self.hwnd_list[0]
        self.set_current_top(hwnd)

        # 打开日历,开始修业任务
        self.open_calendar()

        
        # shi_men_count = 9
        # while shi_men_count <= 10:
        #     left, top, right, bottom = self.get_client_rect(hwnd)
        #     time.sleep(self.human_delay(0.5))

        #     win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        #     win32gui.SetForegroundWindow(hwnd)

        #     time.sleep(self.human_delay(1))
        #     game_image = ImageGrab.grab(bbox=(left, top, right, bottom))

        #     print("🔍 检测修业任务中...")
        #     xiu_ye_ocr_result = self.ocr.get_ocr_from_image(game_image, "修业")

        #     if not xiu_ye_ocr_result:
        #         raise Exception("OCR找不到修业任务")

        #     task_text = xiu_ye_ocr_result[0][1]
        #     print(f"✅ 检测到任务 {task_text}")

        #     best_bbox, best_text, best_conf = max(xiu_ye_ocr_result, key=lambda x: x[2])
        #     bbox = np.array(best_bbox)
        #     center_x = np.mean(bbox[:, 0])
        #     center_y = np.mean(bbox[:, 1])
        #     abs_x = left + center_x
        #     abs_y = top + center_y
        #     pyautogui.click(abs_x,abs_y)
        #     time.sleep(self.human_delay(1))

        #     if '物资' in task_text:
        #         timeout = 20.0  # 最大等待时间（秒），防止永久卡死
        #         time.sleep(self.human_delay(0.4))

        #         pyautogui.keyDown('ctrl')
        #         time.sleep(self.human_delay(0.08))    

        #         pyautogui.keyDown('j')
        #         time.sleep(self.human_delay(0.05))

        #         pyautogui.keyUp('j')
        #         time.sleep(self.human_delay(0.06))    

        #         pyautogui.keyUp('ctrl')

        #         game_image = ImageGrab.grab(bbox=(left, top, right, bottom))
        #         wu_zi_ocr_result = self.ocr.get_ocr_from_image(game_image, "购买")
        #         time.sleep(self.human_delay(0.5))    

        #         if not wu_zi_ocr_result:
        #             raise Exception("OCR找不到购买按钮")

        #         best_bbox, best_text, best_conf = max(wu_zi_ocr_result, key=lambda x: x[2])
        #         bbox = np.array(best_bbox)
        #         center_x = np.mean(bbox[:, 0])
        #         center_y = np.mean(bbox[:, 1])
        #         abs_x = left + center_x
        #         abs_y = top + center_y
        #         pyautogui.click(abs_x,abs_y)
        #         time.sleep(self.human_delay(1))

        #         best_bbox, best_text, best_conf = max(xiu_ye_ocr_result, key=lambda x: x[2])
        #         bbox = np.array(best_bbox)
        #         center_x = np.mean(bbox[:, 0])
        #         center_y = np.mean(bbox[:, 1])
        #         abs_x = left + center_x
        #         abs_y = top + center_y
        #         pyautogui.click(abs_x,abs_y)
        #         time.sleep(self.human_delay(10))

        #         is_finish = False

        #         start_time = time.time()
        #         while time.time() - start_time < timeout:
        #             count_image = ImageGrab.grab(bbox=(left, top, right, bottom))
        #             if self.ocr.get_ocr_from_image(count_image, f"第{shi_men_count+1}环"):
        #                 is_finish = True
        #                 print(f"第{shi_men_count}环[物资]任务是否完成, 进入下一个修业任务")
        #                 break
        #             time.sleep(self.human_delay(2))
                        
        #         if not is_finish:
        #             raise Exception(f"等待【第{shi_men_count}环】超时")

        #         print(f"修业任务第{shi_men_count}次完成")
        #         shi_men_count += 1
        #         pyautogui.keyDown('esc')

        #     elif '挑战' in task_text:
        #         self.auto_reset_round()

        #         is_finish = False

        #         timeout = 100.0
        #         start_time = time.time()
        #         while time.time() - start_time < timeout:
        #             count_image = ImageGrab.grab(bbox=(left, top, right, bottom))
        #             if self.ocr.get_ocr_from_image(count_image, f"第{shi_men_count+1}环"):
        #                 is_finish = True
        #                 print(f"第{shi_men_count}环修业任务是否完成, 进入下一个修业任务")
        #                 break

        #             print(f"第{shi_men_count}环[挑战]任务未完成,继续监控")
        #             time.sleep(self.human_delay(2))

        #         if not is_finish:
        #             raise Exception(f"等待【第{shi_men_count}环】超时")

        #         print(f"修业任务第{shi_men_count}次完成")
        #         shi_men_count += 1
        #         pyautogui.keyDown('esc')

        #     elif '捕捉' in task_text:
        #         time.sleep(self.human_delay(4))

        #         game_image = ImageGrab.grab(bbox=(left, top, right, bottom))
        #         xin_yu_buy_result = self.ocr.get_ocr_from_image(game_image, "信誉购买")

        #         if not xin_yu_buy_result:
        #             raise Exception("OCR找不到信誉购买按钮")

        #         best_bbox, best_text, best_conf = max(xin_yu_buy_result, key=lambda x: x[2])
        #         bbox = np.array(best_bbox)
        #         center_x = np.mean(bbox[:, 0])
        #         center_y = np.mean(bbox[:, 1])
        #         abs_x = left + center_x
        #         abs_y = top + center_y
        #         pyautogui.click(abs_x,abs_y)
        #         time.sleep(self.human_delay(1))          

        #         timeout = 20.0
        #         start_time = time.time()
        #         while time.time() - start_time < timeout:
        #             count_image = ImageGrab.grab(bbox=(left, top, right, bottom))
        #             if self.ocr.get_ocr_from_image(count_image, f"第{shi_men_count+1}环"):
        #                 is_finish = True
        #                 print(f"第{shi_men_count}环[捕捉宠物]任务完成, 进入下一个修业任务")
        #                 break

        #             print(f"第{shi_men_count}环修业任务未完成,继续监控")
        #             time.sleep(self.human_delay(2))

        #         if not is_finish:
        #             raise Exception(f"等待【第{shi_men_count}环】超时")

        #         print(f"修业任务第{shi_men_count}次完成")
        #         shi_men_count += 1
        #         pyautogui.keyDown('esc')