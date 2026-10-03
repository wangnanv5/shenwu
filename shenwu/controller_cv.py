import mss
import traceback
import pyautogui
import win32gui
import win32con
import cv2
import numpy as np
from PIL import ImageGrab
from munch import DefaultMunch
from humancursor import SystemCursor

from shenwu.config import *
from shenwu.utils import (human_delay,get_hwnd_image,set_current_top,open_item_shop_keyboard,
                          auto_reset_round,open_calendar,get_client_rect,get_abs_x_y,check_is_frozen,
                          make_mss_region,find_best_match,get_abs_x_y_cv)

import ctypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.2
# 1200 800
# 900  600
window_width = 1200
window_height = 900
# ROI = (0, 0, 800, 600)
ROI = (0, 0, 1200, 900)

# 匹配阈值，0.75~0.9 之间调
THRESHOLD = 0.80
USE_MULTISCALE = False

# 如果 USE_MULTISCALE = True，会使用这些缩放比例尝试匹配
SCALES = [1.5]

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
        self.cv = mss.MSS()

        self.hwnd_status = {}
        self.has_item_transaction = False
        win32gui.EnumWindows(self.get_hwnd, None)
        assert self.hwnd_list , "幻唐志窗口未找到"
        print(f"初始化成功,找到{len(self.hwnd_list)}个游戏窗口")
        self.mouse = SystemCursor()

        self.xun_you_start_fight_icon = cv2.imread(xun_you_start_fight_path)
        self.xun_you_start_fight_icon = cv2.cvtColor(self.xun_you_start_fight_icon,cv2.COLOR_BGR2GRAY)
        self.xun_you_finish_icon = cv2.imread(xun_you_finish_path)
        self.xun_you_finish_icon = cv2.cvtColor(self.xun_you_finish_icon,cv2.COLOR_BGR2GRAY)
        self.is_in_fight_icon = cv2.imread(is_in_fight_path)
        self.is_in_fight_icon = cv2.cvtColor(self.is_in_fight_icon,cv2.COLOR_BGR2GRAY)

        # 通用
        self.pet_shop_icon = cv2.imread(pet_shop_path)
        self.pet_shop_icon = cv2.cvtColor(self.pet_shop_icon,cv2.COLOR_BGR2GRAY)            
        self.pet_shop_button_icon = cv2.imread(pet_shop_buy_button_path)
        self.pet_shop_button_icon = cv2.cvtColor(self.pet_shop_button_icon,cv2.COLOR_BGR2GRAY)     
        self.item_shop_icon = cv2.imread(item_shop_path)
        self.item_shop_icon = cv2.cvtColor(self.item_shop_icon,cv2.COLOR_BGR2GRAY)              
        self.item_shop_buy_button_icon = cv2.imread(item_buy_button_path)
        self.item_shop_buy_button_icon = cv2.cvtColor(self.item_shop_buy_button_icon,cv2.COLOR_BGR2GRAY)    
        self.item_shop_has_buy_icon = cv2.imread(item_has_buy_path)
        self.item_shop_has_buy_icon = cv2.cvtColor(self.item_shop_has_buy_icon,cv2.COLOR_BGR2GRAY)            
        self.has_talk_icon = cv2.imread(item_has_buy_path)
        self.has_talk_icon = cv2.cvtColor(self.has_talk_icon,cv2.COLOR_BGR2GRAY)      
        self.has_xun_lu_icon = cv2.imread(item_has_buy_path)
        self.has_xun_lu_icon = cv2.cvtColor(self.has_xun_lu_icon,cv2.COLOR_BGR2GRAY) 
        # 修业任务类型,分为捕捉宠物 查找物资 挑战
        self.has_xiu_ye_task_icon = cv2.imread(xiu_ye_path)
        self.has_xiu_ye_task_icon = cv2.cvtColor(self.has_xiu_ye_task_icon,cv2.COLOR_BGR2GRAY)     
        # 修业的任务类型图标,分为宠物 物资 挑战   
        self.xiu_ye_wu_zi_icon = cv2.imread(xiu_ye_wu_zi_path)
        self.xiu_ye_wu_zi_icon = cv2.cvtColor(self.xiu_ye_wu_zi_icon,cv2.COLOR_BGR2GRAY)    
        self.xiu_ye_chong_wu_icon = cv2.imread(xiu_ye_chong_wu_path)
        self.xiu_ye_chong_wu_icon = cv2.cvtColor(self.xiu_ye_chong_wu_icon,cv2.COLOR_BGR2GRAY)            
        self.xiu_ye_tiao_zhan_icon = cv2.imread(xiu_ye_tiao_zhan_path)
        self.xiu_ye_tiao_zhan_icon = cv2.cvtColor(self.xiu_ye_tiao_zhan_icon,cv2.COLOR_BGR2GRAY)          

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

    def run_auto_reset_round(self,is_hide=False):
        print("开始自动重置")
        while True:
            for hwnd in self.hwnd_list:
                set_current_top(hwnd)
                auto_reset_round()
                if is_hide: 
                    win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
                human_delay(5)

    def is_in_fight(self,frame):
        match = find_best_match(frame,self.is_in_fight_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
        if match is None:
            return False
        else:
            return True

    def run_xun_you(self):
        while True:
            if all(v.is_finish_xun_you for v in self.hwnd_status.values()):
                break

            for hwnd in self.hwnd_list:
                if self.hwnd_status[hwnd].is_finish_xun_you:
                    continue

                try:
                    set_current_top(hwnd)
                    auto_reset_round()
                    human_delay(1)
                    left, top, right, bottom = get_client_rect(hwnd)

                    region = make_mss_region(hwnd,ROI)

                    # 点击对话框，进入战斗
                    # try:
                    shot = self.cv.grab(region)
                    frame = np.array(shot)
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)

                    if self.is_in_fight(frame):
                        human_delay(5)
                        continue

                    finish_match = find_best_match(frame,self.xun_you_finish_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
                    
                    if finish_match is not None:
                        self.hwnd_status[hwnd].is_finish_xun_you = True
                        abs_x,abs_y = get_abs_x_y_cv(finish_match["bbox"],left, top)
                        human_delay(1)

                        self.mouse.click_on([abs_x, abs_y])
                        human_delay(5)        

                    else:
                        match = find_best_match(frame,self.xun_you_start_fight_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)

                        if match is None:
                            print ("模式匹配结果为空")
                            continue
                        
                        abs_x,abs_y = get_abs_x_y_cv(match["bbox"],left, top)
                        human_delay(1)

                        self.mouse.click_on([abs_x, abs_y])
                        human_delay(5)
                    continue
                except Exception:
                    print(f"巡游任务出错:")
                    traceback.print_exc() 
                    human_delay(5)
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
        left, top, right, bottom = get_client_rect(hwnd)
        human_delay(1)

        while has_fish:
            game_image = ImageGrab.grab(bbox=(left+fish_width_start,top + fish_height_start, left+fish_width_end, top+fish_height_end))

            try:
                start_fight_location = pyautogui.locate(str(you_yu_path),game_image, grayscale=True,confidence=0.7)
                abs_x = left + start_fight_location.left + start_fight_location.width // 2
                abs_y = top + start_fight_location.top + start_fight_location.height // 2

                pyautogui.moveTo(abs_x,abs_y, duration=human_delay(0.2))
                self.mouse.perform_click()
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
        self.mouse.click_on([abs_x, abs_y])
        human_delay(1)

    def is_open_calendar(self,hwnd):
        game_image = get_hwnd_image(hwnd)
        region = make_mss_region(hwnd,ROI)
        shot = self.cv.grab(region)
        frame = np.array(shot)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
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

    def is_open_pet_shop(self,frame):
        match = find_best_match(frame,self.pet_shop_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
        if match is None:
            return False
        else:
            return True
        
    def is_open_item_shop(self,frame):
        match = find_best_match(frame,self.item_shop_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
        if match is None:
            return False
        else:
            return True

    def is_item_has_buy(self,frame):
        match = find_best_match(frame,self.item_shop_has_buy_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
        if match is None:
            return False
        else:
            return True

    def is_has_talk(self,frame):
        match = find_best_match(frame,self.has_talk_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
        if match is None:
            return False
        else:
            return True

    def is_has_xun_lu(self,frame):
        match = find_best_match(frame,self.has_xiu_ye_task_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
        if match is None:
            return False
        else:
            return True

    def has_xiu_ye_task(self,frame,return_match=False):
        match = find_best_match(frame,self.has_xiu_ye_task_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
        if match is None:
            if return_match:
                return False,None
            else:
                return False
        else:
            if return_match:
                return True,match
            else:
                return True

    def get_task_type(self,frame):
        for index,task_type_icon in zip([1,2,3],[self.xiu_ye_wu_zi_icon,self.xiu_ye_chong_wu_icon,self.xiu_ye_tiao_zhan_icon]):
            match = find_best_match(frame,task_type_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
            if match is not None:
                return index
        return -1

    # 修业任务
    def run_xiu_ye(self):
        while True:
            if all(v.is_finish_xiu_ye for v in self.hwnd_status.values()):
                break

            for hwnd in self.hwnd_list:

                if self.hwnd_status[hwnd].is_finish_xiu_ye:
                    continue

                set_current_top(hwnd)
                human_delay(1)
                
                # 检查页面是否有修业任务
                left, top, right, bottom = get_client_rect(hwnd)

                region = make_mss_region(hwnd,ROI)
                shot = self.cv.grab(region)
                frame = np.array(shot)
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                has_match,match_result = self.has_xiu_ye_task(frame,True)

                if not has_match:
                    print("❌ 未检测到修业任务")
                    self.hwnd_status[hwnd].is_finish_xiu_ye = True
                    human_delay(1)
                    continue

                task_type = self.get_task_type(frame)

                if task_type == -1:
                    print("❌ 修业任务类型错误")
                    continue

                xiu_ye_abs_x,xiu_ye_abs_y = get_abs_x_y_cv(match_result["bbox"],left, top)
                human_delay(1)
                # 物资
                if task_type == 1:

                    # 确保打开了物品寄售界面
                    while True:
                        open_item_shop_keyboard()
                        human_delay(1) 
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                        if self.is_open_item_shop(frame):
                            break
                        human_delay(1)                    

                    # 确保购买成功
                    while True:
                        wu_zi_match = find_best_match(frame,self.item_shop_buy_button_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
                        abs_x,abs_y = get_abs_x_y_cv(wu_zi_match["bbox"],left, top)
                        human_delay(1)
                        self.mouse.click_on([abs_x, abs_y])
                        if self.is_item_has_buy(frame):
                            print("✅ 购买物资成功")
                            pyautogui.press('esc')
                            break
                    
                    # 确保开始自动寻路
                    while True:
                        human_delay(1)       
                        self.mouse.click_on([xiu_ye_abs_x, xiu_ye_abs_y])
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)                        
                        if not self.is_has_xun_lu(frame):
                            break

                    # 确保关闭了对话
                    while True:
                        human_delay(1)
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)                                
                        if not self.is_has_talk(frame):
                            break
                        pyautogui.press('esc')

                # 宠物
                elif task_type == 2:
                    self.mouse.click_on([xiu_ye_abs_x,xiu_ye_abs_y])
                    human_delay(1) 

                    # 检测是否打开了宠物购买页面
                    while True:
                        if self.is_open_pet_shop(frame):
                            pet_buy_button_match = find_best_match(frame,self.pet_shop_button_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
                            print("✅ 打开了宠物购买页面")
                            break
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                        human_delay(1)

                    # 确保购买成功
                    while True:
                        abs_x,abs_y = get_abs_x_y_cv(pet_buy_button_match["bbox"],left, top)
                        self.mouse.click_on([abs_x, abs_y])
                        human_delay(1)
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                        if not self.is_open_pet_shop(frame):
                            print("✅ 购买宠物成功")
                            break

                    # 确保开始自动寻路
                    while True:
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)                        
                        if not self.is_has_xun_lu(frame):
                            print("✅ 自动寻路结束")
                            break
                        self.mouse.click_on([xiu_ye_abs_x, xiu_ye_abs_y])
                        human_delay(1)       
                    
                    # 确保关闭了对话
                    while True:
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)                        
                        if not self.is_has_talk(frame):
                            print("✅ 取消对话框")
                            break
                        human_delay(1)
                        pyautogui.press('esc')

                # 战斗
                elif task_type == 3:
                    auto_reset_round()

                    # 确保进入战斗中
                    while True:
                        self.mouse.click_on([xiu_ye_abs_x,xiu_ye_abs_y])
                        human_delay(20) 
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                        if self.is_in_fight(frame):
                            print("✅ 进入战斗中")
                            human_delay(0.5)
                            break

                    while True:
                        human_delay(5) 
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                        if not self.is_in_fight(frame):
                            print("✅ 战斗结束")
                            human_delay(0.5)
                            break
                    
                    while True:
                        human_delay(2) 
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)                        
                        if not self.is_has_talk(frame):
                            print("✅ 取消对话框")
                            break                 
                        human_delay(1)
                        pyautogui.press('esc')
                    
