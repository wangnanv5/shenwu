import pyautogui
import win32gui
import win32con
import time
import random
import math
import numpy as np
from PIL import ImageGrab
from munch import DefaultMunch

from shenwu.config import *
from shenwu.ocr import Ocr
from shenwu.utils import (human_delay,get_hwnd_image,set_current_top,open_item_shop_keyboard,
                          auto_reset_round,open_calendar,get_client_rect,get_abs_x_y,check_is_frozen)

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

        self.hwnd_status = {}
        self.has_item_transaction = False
        win32gui.EnumWindows(self.get_hwnd, None)
        assert self.hwnd_list , "幻唐志窗口未找到"
        print(f"初始化成功,找到{len(self.hwnd_list)}个游戏窗口")

    def get_hwnd(self,hwnd, extra):
        status = DefaultMunch.fromDict(
            {
                # 状态部分
                "has_item_transaction": False,
                "is_finish_xun_you": False,
                "is_finish_xiu_ye": False,
                "is_last_xiu_ye": False,

                "is_open_calendar": False,
                "is_open_item_shop": False,
                "is_open_pet_shop": False,

                # 数据部分
                "calendar_data" : None,
                "item_shop_data": None,
                "pet_shop_data": None,
            }
        )

        title = win32gui.GetWindowText(hwnd)
        if ("幻唐志" in title) and ("RENDER" not in title):
            self.hwnd_list.append(hwnd)
            self.hwnd_status[hwnd] = status

    def run_auto_reset_round(self):
        print("开始自动重置")
        while True:
            for hwnd in self.hwnd_list:
                set_current_top(hwnd)
                auto_reset_round()
                human_delay(10)

    # to-do
    def run_xun_you(self):
        for hwnd in self.hwnd_list:
            if self.hwnd_status[hwnd].is_finish_xun_you:
                continue

            find_dialogue_flag = True
            set_current_top(hwnd)
            auto_reset_round()

            left, top, right, bottom = self.get_client_rect(hwnd)
            human_delay(1)

            # 点击对话框，进入战斗
            while find_dialogue_flag:
                game_image = ImageGrab.grab(bbox=(left, top, left + window_width, top + window_height))
                try:
                    print("🔍 检测对话框中...")
                    ocr_result = self.ocr.get_ocr_from_image(game_image, ["开始战斗","离开场景"])

                    if not ocr_result:
                        raise Exception("OCR结果为空")

                    best_bbox, best_text, best_conf = max(ocr_result, key=lambda x: x[2])

                    bbox = np.array(best_bbox)
                    center_x = np.mean(bbox[:, 0])
                    center_y = np.mean(bbox[:, 1])

                    abs_x = left + center_x
                    abs_y = top + center_y

                    pyautogui.click(abs_x,abs_y)
                    human_delay(1)
                    # win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
                    find_dialogue_flag = False

                except Exception as e:
                    print(f"巡游任务报错 {e}")
                    find_dialogue_flag = False
                    human_delay(1)
                    # win32gui.ShowWindow(hwnd, win32con.SW_HIDE)

    # to do
    def run_fish(self):
        win32gui.EnumWindows(self.get_hwnd, None)
        assert len(self.hwnd_list) , "钓鱼只支持1个窗口"

        hwnd = self.hwnd_list[0]
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)

        # 抛竿
        pyautogui.press('f1')
        pyautogui.PAUSE = human_delay(2)
        pyautogui.press('f1')

        has_fish = True
        left, top, right, bottom = self.get_client_rect(hwnd)
        human_delay(1)

        while has_fish:
            game_image = ImageGrab.grab(bbox=(left+fish_width_start,top + fish_height_start, left+fish_width_end, top+fish_height_end))

            try:
                start_fight_location = pyautogui.locate(str(you_yu_path),game_image, grayscale=True,confidence=0.7)
                abs_x = left + start_fight_location.left + start_fight_location.width // 2
                abs_y = top + start_fight_location.top + start_fight_location.height // 2

                pyautogui.moveTo(abs_x,abs_y, duration=human_delay(0.2))
                pyautogui.click()
                human_delay(1)
                has_fish = False

            except Exception as e:
                print(f"还未钓到鱼 {e}")
                has_fish = False
                human_delay(1)

    # to-do
    def run_auto_task(self,task_name):
        win32gui.EnumWindows(self.get_hwnd, None)
        assert self.hwnd_list , "幻唐志窗口未找到"

        hwnd = self.hwnd_list[0]

        left, top, right, bottom = self.get_client_rect(hwnd)
        human_delay(1)

        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)

        # 先看看能不能找到该任务
        human_delay(1)
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
        human_delay(1)

    def is_open_calendar(self,hwnd):
        game_image = get_hwnd_image(hwnd)
        print("🔍 判断页面是否包含日程界面...")
        calendar_ocr_result,all_ocr = self.ocr.get_ocr_from_image(game_image, ["每日活动","组队历练","个人历练","周边休闲"],True)
        if len(calendar_ocr_result) > 2:
            print("✅ 检测到已经打开日程界面")
            self.hwnd_status[hwnd].is_open_calendar = True
            self.hwnd_status[hwnd].calendar_data = all_ocr
        else:
            print("❌ 未检测到日程界面")
            self.hwnd_status[hwnd].is_open_calendar = False
            self.hwnd_status[hwnd].calendar_data = None

    def set_hide_window(self,hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_HIDE)

    # 确保一定打开了日程界面,并把日历信息写入到hwnd_status中
    def get_calendar_information(self,hwnd):
        while True:
            set_current_top(hwnd)
            human_delay(1)
            open_calendar()
            human_delay(1)
            self.is_open_calendar(hwnd)
            human_delay(1)
            if self.hwnd_status[hwnd].calendar_data is not None and self.hwnd_status[hwnd].is_open_calendar:
                break

    def is_open_item_shop(self,hwnd):
        game_image = get_hwnd_image(hwnd)
        print("🔍 判断页面是否包含物品寄售页面...")
        item_ocr_result,all_ocr = self.ocr.get_ocr_from_image(game_image, ["刷新货物","购买","整理"],True)
        if len(item_ocr_result) > 2:
            print("✅ 检测到物品寄售页面")
            self.hwnd_status[hwnd].is_open_item_shop = True
            self.hwnd_status[hwnd].item_shop_data = all_ocr
        else:
            print("未找到物品寄售页面")
            self.hwnd_status[hwnd].is_open_item_shop = False
            self.hwnd_status[hwnd].item_shop_data = None

    # 确保一定打开了寄售界面,并把日历信息写入到hwnd_status中             
    def open_item_shop(self,hwnd):
        while True:
            set_current_top(hwnd)
            human_delay(1)

            open_item_shop_keyboard()
            human_delay(1)

            self.is_open_item_shop(hwnd)
            if self.hwnd_status[hwnd].is_open_item_shop:
                break

    def get_shi_men_in_calendar(self,hwnd):
        if self.hwnd_status[hwnd].calendar_data is None:
            self.get_calendar_information(hwnd)

        target = "/10"
        found = [(box, text, score) for box, text, score in self.hwnd_status[hwnd].calendar_data if target in text]
        assert found, "未在日程中定位到修业任务进度"

        current_count = found[0][1]
        return int(current_count.split("/")[0])

    def is_open_pet_shop(self,hwnd):
        game_image = get_hwnd_image(hwnd)
        print("🔍 判断页面是否包含购买宠物页面...")
        pet_ocr_result,all_ocr = self.ocr.get_ocr_from_image(game_image, ["宠物交易","现金购买","信誉购买"],True)
        if len(pet_ocr_result) > 2:
            print("✅ 检测到宠物交易页面")
            self.hwnd_status[hwnd].is_open_pet_shop = True
            self.hwnd_status[hwnd].pet_shop_data = all_ocr            
        else:
            print("未找到宠物交易页面")
            self.hwnd_status[hwnd].is_open_pet_shop = False
            self.hwnd_status[hwnd].pet_shop_data = None              

    # 确保一定打开了宠物交易界面,并把信息写入到hwnd_status中             
    def open_pet_shop(self,hwnd):
        while True:
            set_current_top(hwnd)
            human_delay(1)

            self.is_open_pet_shop(hwnd)
            if self.hwnd_status[hwnd].is_open_pet_shop:
                break

    # 修业任务
    def run_xiu_ye(self):
        while True:
            if all(v.is_finish_xiu_ye for v in self.hwnd_status.values()):
                break

            for hwnd in self.hwnd_list:

                if self.hwnd_status[hwnd].is_finish_xiu_ye:
                    continue

                set_current_top(hwnd)
                self.hwnd_status[hwnd].is_last_xiu_ye = False

                # 打开日历,开始修业任务 
                human_delay(1)
                current_count = self.get_shi_men_in_calendar(hwnd)

                if current_count == 10:
                    print(f"✅ {hwnd}-检测到师门任务完成")
                    self.hwnd_status[hwnd].is_finish_xiu_ye = True
                    continue

                if self.hwnd_status[hwnd].is_open_calendar:
                    pyautogui.press('esc')

                current_count += 1
                print("开始修业任务")
                print(f"当前修业任务进度: {current_count}/10")
                
                while current_count <= 10:
                    if current_count == 10:
                        self.hwnd_status[hwnd].is_last_xiu_ye = True

                    left, top, right, bottom = get_client_rect(hwnd)

                    human_delay(1)
                    game_image = ImageGrab.grab(bbox=(left, top, right, bottom))

                    print("🔍 检测修业任务中...")
                    xiu_ye_ocr_result = self.ocr.get_ocr_from_image(game_image, "修业")

                    if not xiu_ye_ocr_result:
                        continue

                    task_text = xiu_ye_ocr_result[0][1]
                    print(f"✅ 检测到任务 {task_text}")

                    best_bbox, best_text, best_conf = max(xiu_ye_ocr_result, key=lambda x: x[2])
                    abs_x,abs_y = get_abs_x_y(best_bbox,left,top)

                    if '物资' in task_text:
                        self.open_item_shop(hwnd)
                        found = [
                            (box, text, score) 
                            for box, text, score in self.hwnd_status[hwnd].item_shop_data 
                            if '购买' in text 
                        ]

                        human_delay(1)

                        if not found:                                                    
                            print(" ❌ 修业物资任务找不到购买按钮")
                            pyautogui.press('esc')
                            human_delay(1)
                            self.hwnd_status[hwnd].is_open_item_shop = False
                            continue
                        
                        # 识别到购买按钮，完成购买操作                                                      
                        best_bbox, best_text, best_conf = max(found, key=lambda x: x[2])
                        abs_x,abs_y = get_abs_x_y(best_bbox,left,top)
                        human_delay(1)
                        pyautogui.click(abs_x,abs_y)
                        print('完成购买')

                        self.is_open_item_shop(hwnd)
                        if self.hwnd_status[hwnd].is_open_item_shop:
                            pyautogui.press('esc')
                            human_delay(1)

                        # 点击修业任务 自动回师门交任务
                        best_bbox, best_text, best_conf = max(xiu_ye_ocr_result, key=lambda x: x[2])
                        abs_x,abs_y = get_abs_x_y(best_bbox,left,top)
                        pyautogui.click(abs_x,abs_y)
                        human_delay(10)

                        is_finish = False
                        timeout = 120.0  # 最大等待时间（秒），防止永久卡死
                        start_time = time.time()
                        while time.time() - start_time < timeout:
                            count_image = ImageGrab.grab(bbox=(left, top, right, bottom))
                            if self.hwnd_status[hwnd].is_last_xiu_ye:
                                if not self.ocr.get_ocr_from_image(count_image, "修业"):
                                    print("✅ 修业任务完成")
                                    break

                            elif self.ocr.get_ocr_from_image(count_image, f"第{current_count+1}环"):
                                is_finish = True
                                print(f"第{current_count}环[物资]任务是完成, 进入下一个修业任务")
                                break

                            human_delay(2)
                                
                        if not is_finish:
                            raise Exception(f"等待【第{current_count}环】超时")

                        current_count += 1
                        pyautogui.press('esc')

                    elif '挑战' in task_text:
                        auto_reset_round()
                        human_delay(2)

                        while True:
                            pyautogui.click(abs_x,abs_y)

                            is_frozen, ratio = check_is_frozen(hwnd)
                            if is_frozen:
                                print(f"⚠️ 警告: 修业任务-挑战 疑似卡住 (像素变动率: {ratio:.4%})")
                            else:
                                break

                        is_finish = False

                        timeout = 300
                        start_time = time.time()
                        while time.time() - start_time < timeout:
                            count_image = ImageGrab.grab(bbox=(left, top, right, bottom))
                            if self.hwnd_status[hwnd].is_last_xiu_ye:
                                if not self.ocr.get_ocr_from_image(count_image, "修业"):
                                    print("✅ 修业任务完成")
                                    return

                            elif self.ocr.get_ocr_from_image(count_image, f"第{current_count+1}环"):
                                is_finish = True
                                print(f"第{current_count}环修业任务完成, 进入下一个修业任务")
                                break

                            print(f"第{current_count}环[挑战]任务未完成,继续监控")
                            human_delay(2)

                        if not is_finish:
                            raise Exception(f"等待【第{current_count}环】超时")

                        print(f"修业任务第{current_count}次完成")
                        current_count += 1
                        pyautogui.press('esc')

                    elif '捕捉' in task_text:
                        human_delay(1)
                        while True:
                            pyautogui.click(abs_x,abs_y)
                            human_delay(1)

                            set_current_top(hwnd)
                            human_delay(1)

                            self.is_open_pet_shop(hwnd)
                            if self.hwnd_status[hwnd].is_open_pet_shop:
                                break

                        # while True:
                        #     self.open_pet_shop(hwnd)

                        #     is_frozen, ratio = check_is_frozen(hwnd)
                        #     if is_frozen and :
                        #         print(f"⚠️ 警告: 修业任务-捕捉宠物疑似卡住 (像素变动率: {ratio:.4%})")
                        #     else:
                        #         break

                        # 购买完成后,会自动关闭交易窗口,并自动寻路,如果检测到宠物交易窗口,说明没有点击购买按钮
                        while True:
                            found = [
                                    (box, text, score) 
                                    for box, text, score in self.hwnd_status[hwnd].pet_shop_data 
                                    if '信誉购买' in text 
                                                    ]

                            if not found:
                                print(" ❌ 修业买宠任务找不到信誉购买按钮")
                                pyautogui.press('esc')
                                human_delay(1)
                                self.hwnd_status[hwnd].is_open_item_shop = False

                            best_bbox, best_text, best_conf = max(found, key=lambda x: x[2])
                            abs_x,abs_y = get_abs_x_y(best_bbox,left,top)
                            pyautogui.click(abs_x,abs_y)
                            human_delay(1)  

                            self.is_open_pet_shop(hwnd)
                            if not self.hwnd_status[hwnd].is_open_pet_shop:
                                print('完成宠物购买')   
                                break

                        timeout = 20.0
                        start_time = time.time()
                        while time.time() - start_time < timeout:
                            count_image = ImageGrab.grab(bbox=(left, top, right, bottom))
                            if self.hwnd_status[hwnd].is_last_xiu_ye:
                                if not self.ocr.get_ocr_from_image(count_image, "修业"):
                                    print("✅ 修业任务完成")
                                    return
                                
                            elif self.ocr.get_ocr_from_image(count_image, f"第{current_count+1}环"):
                                is_finish = True
                                print(f"第{current_count}环[捕捉宠物]任务完成, 进入下一个修业任务")
                                break

                            print(f"第{current_count}环修业任务未完成,继续监控")
                            human_delay(2)

                        if not is_finish:
                            raise Exception(f"等待【第{current_count}环】超时")

                        print(f"修业任务第{current_count}次完成")
                        current_count += 1
                        pyautogui.press('esc')
                        