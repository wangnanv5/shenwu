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
from shenwu.utils import (human_delay,get_hwnd_image,set_current_top,right_click,get_color,
                          auto_reset_round,open_calendar,get_client_rect,open_bag_keyboard,
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
        # 日历
        self.ri_cheng_icon = cv2.imread(ri_cheng_path)
        self.ri_cheng_icon = cv2.cvtColor(self.ri_cheng_icon,cv2.COLOR_BGR2GRAY) 
        # 宠物商店
        self.pet_shop_icon = cv2.imread(pet_shop_path)
        self.pet_shop_icon = cv2.cvtColor(self.pet_shop_icon,cv2.COLOR_BGR2GRAY)            
        # 宠物商店购买按钮
        self.pet_shop_button_icon = cv2.imread(pet_shop_buy_button_path)
        self.pet_shop_button_icon = cv2.cvtColor(self.pet_shop_button_icon,cv2.COLOR_BGR2GRAY) 
        # 寄售商店页面    
        self.item_shop_icon = cv2.imread(item_shop_path)
        self.item_shop_icon = cv2.cvtColor(self.item_shop_icon,cv2.COLOR_BGR2GRAY)              
        # 寄售商店购买按钮
        self.item_shop_buy_button_icon = cv2.imread(item_buy_button_path)
        self.item_shop_buy_button_icon = cv2.cvtColor(self.item_shop_buy_button_icon,cv2.COLOR_BGR2GRAY)  
        # 寄售商店已购买弹出来的图标  
        self.item_shop_has_buy_icon = cv2.imread(item_has_buy_path)
        self.item_shop_has_buy_icon = cv2.cvtColor(self.item_shop_has_buy_icon,cv2.COLOR_BGR2GRAY)           
        # 寄售商店的需求物资图标
        self.item_xu_qiu_icon = cv2.imread(item_xu_qiu_path)
        self.item_xu_qiu_icon = cv2.cvtColor(self.item_xu_qiu_icon,cv2.COLOR_BGR2GRAY)          
        # 商品寄售价格确认按钮
        self.item_xu_que_ren_icon = cv2.imread(item_que_ren_path)
        self.item_xu_que_ren_icon = cv2.cvtColor(self.item_xu_que_ren_icon,cv2.COLOR_BGR2GRAY)                      
        # npc对话弹框
        self.has_talk_icon = cv2.imread(close_talk_path)
        self.has_talk_icon = cv2.cvtColor(self.has_talk_icon,cv2.COLOR_BGR2GRAY)      
        # 寻路图标
        self.has_xun_lu_icon = cv2.imread(xun_lu_path)
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
        # 修炼相关
        self.xiu_lian_no_finish_icon = cv2.imread(xiu_lian_no_finish_path)
        self.xiu_lian_no_finish_icon = cv2.cvtColor(self.xiu_lian_no_finish_icon,cv2.COLOR_BGR2GRAY)    
        self.xiu_lian_finish_icon = cv2.imread(xiu_lian_finish_path)
        # self.xiu_lian_finish_icon = cv2.cvtColor(self.xiu_lian_finish_icon,cv2.COLOR_BGR2GRAY)            
        # 修炼对话
        self.xiu_lian_talk_icon = cv2.imread(xiu_lian_talk_path)
        self.xiu_lian_talk_icon = cv2.cvtColor(self.xiu_lian_talk_icon,cv2.COLOR_BGR2GRAY)  
        self.xiu_lian_task_icon = cv2.imread(xiu_lian_task_path)
        self.xiu_lian_task_icon = cv2.cvtColor(self.xiu_lian_task_icon,cv2.COLOR_BGR2GRAY)  
        self.xiu_lian_xun_wu_icon = cv2.imread(xiu_lian_xun_wu_path)
        self.xiu_lian_xun_wu_icon = cv2.cvtColor(self.xiu_lian_xun_wu_icon,cv2.COLOR_BGR2GRAY)          
        self.xiu_lian_zhao_ren_icon = cv2.imread(xiu_lian_zhao_ren_path)
        self.xiu_lian_zhao_ren_icon = cv2.cvtColor(self.xiu_lian_zhao_ren_icon,cv2.COLOR_BGR2GRAY)           
        self.xiu_lian_feng_dao_ren_icon = cv2.imread(xiu_lian_feng_dao_ren_path)
        self.xiu_lian_feng_dao_ren_icon = cv2.cvtColor(self.xiu_lian_feng_dao_ren_icon,cv2.COLOR_BGR2GRAY)                 
        self.xiu_lian_bao_hu_feng_dao_ren_icon = cv2.imread(xiu_lian_bao_hu_feng_dao_ren_path)
        self.xiu_lian_bao_hu_feng_dao_ren_icon = cv2.cvtColor(self.xiu_lian_bao_hu_feng_dao_ren_icon,cv2.COLOR_BGR2GRAY)              
        # 驱魔相关
        self.qu_mo_small_icon = cv2.imread(qu_mo_small_path)
        self.qu_mo_small_icon = cv2.cvtColor(self.qu_mo_small_icon,cv2.COLOR_BGR2GRAY)  
        self.qu_mo_icon = cv2.imread(qu_mo_icon_path)
        self.qu_mo_icon = cv2.cvtColor(self.qu_mo_icon,cv2.COLOR_BGR2GRAY)                  
        # 背包
        self.bag_icon = cv2.imread(bag_icon_path)
        self.bag_icon = cv2.cvtColor(self.bag_icon,cv2.COLOR_BGR2GRAY)               
        # f9
        self.f9_icon = cv2.imread(f9_icon_path)
        self.f9_icon = cv2.cvtColor(self.f9_icon,cv2.COLOR_BGR2GRAY)  

    def get_hwnd(self,hwnd, extra):
        status = DefaultMunch.fromDict(
            {
                # 状态部分
                "has_item_transaction": False,
                "is_finish_xun_you": False,
                "is_finish_xiu_ye": False,
                "is_finish_xiu_lian": False,
                "is_last_xiu_ye": False,

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

    def set_hide_window(self,hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_HIDE)

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

    def is_has_item_xu_qiu(self,frame,region=None):
        match = find_best_match(frame,self.item_xu_qiu_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
        # x, y, w, h = match["bbox"]
        # score = match["score"]
        # scale = match["scale"]

        # # 画 bbox
        # cv2.rectangle(
        #     frame,
        #     (x, y),
        #     (x + w, y + h),
        #     (0, 255, 0),
        #     2
        # )

        # # 画分数标签
        # label = f"{score:.2f}"
        # if USE_MULTISCALE:
        #     label += f" x{scale:.2f}"

        # font = cv2.FONT_HERSHEY_SIMPLEX
        # font_scale = 0.6
        # thickness = 2

        # (tw, th), baseline = cv2.getTextSize(
        #     label,
        #     font,
        #     font_scale,
        #     thickness
        # )

        # label_y = max(y - 10, th + 10)

        # cv2.rectangle(
        #     frame,
        #     (x, label_y - th - 8),
        #     (x + tw + 8, label_y + baseline),
        #     (0, 255, 0),
        #     -1
        # )

        # cv2.putText(
        #     frame,
        #     label,
        #     (x + 4, label_y),
        #     font,
        #     font_scale,
        #     (0, 0, 0),
        #     thickness
        # )

        # # 当前 bbox 是相对于截图区域 region 的坐标
        # # 如果要转换成屏幕绝对坐标，需要加上 region 的 left/top
        # screen_x = region["left"] + x
        # screen_y = region["top"] + y

        # print(
        #     f"\rlocal bbox=(x={x}, y={y}, w={w}, h={h}) | "
        #     f"screen top-left=({screen_x}, {screen_y}) | "
        #     f"score={score:.3f} | scale={scale:.2f}   ",
        #     end="",
        #     flush=True
        # )     

        # cv2.imshow("Window Region Template Match - q to quit", frame)

        # key = cv2.waitKey(1) & 0xFF

        # if key == ord("q"):
        #     return           
        
        if match is None:
            return False
        else:
            return True

    def is_open_ri_cheng(self,frame):
        match = find_best_match(frame,self.ri_cheng_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
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
        match = find_best_match(frame,self.has_xun_lu_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
        if match is None:
            return False
        else:
            return True

    def is_open_bag(self,frame):
        match = find_best_match(frame,self.bag_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
        if match is None:
            return False
        else:
            return True

    def is_open_f9(self,frame):
        match = find_best_match(frame,self.f9_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
        if match is None:
            return False
        else:
            return True

    def is_open_xiu_lian_talk(self,frame):
        match = find_best_match(frame,self.xiu_lian_talk_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
        if match is None:
            return False
        else:
            return True

    def has_xiu_lian_task(self,frame):
        match = find_best_match(frame,self.xiu_lian_task_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
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

    def get_xiu_lian_task_type(self,frame):
        for index,task_type_icon in zip([1,2,3],[self.xiu_lian_xun_wu_icon,self.xiu_lian_zhao_ren_icon,self.xiu_lian_feng_dao_ren_icon]):
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
                human_delay(0.2)
                
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
                    human_delay(0.2)
                    continue

                task_type = self.get_task_type(frame)

                if task_type == -1:
                    print("❌ 修业任务类型错误")
                    continue

                xiu_ye_abs_x,xiu_ye_abs_y = get_abs_x_y_cv(match_result["bbox"],left, top)
                human_delay(0.2)

                while True:
                    shot = self.cv.grab(region)
                    frame = np.array(shot)
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                    if self.is_open_f9(frame):
                        break
                    human_delay(0.1)
                    pyautogui.press('f9')
                    human_delay(0.1)

                # 物资
                if task_type == 1:
                    self.mouse.click_on([xiu_ye_abs_x,xiu_ye_abs_y])
                    human_delay(1)                                  
                    while True:
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                        if self.is_open_item_shop(frame):
                            item_buy_button_match = find_best_match(frame,self.item_shop_buy_button_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
                            break
                        human_delay(0.5)

                    # 确保出现"需要"的标志
                    while True:
                        human_delay(1)
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                        if self.is_has_item_xu_qiu(frame):
                            break
                        human_delay(1)

                    # 确保购买成功
                    while True:
                        abs_x,abs_y = get_abs_x_y_cv(item_buy_button_match["bbox"],left, top)
                        self.mouse.click_on([abs_x, abs_y])
                        human_delay(1)
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                        if not self.is_open_item_shop(frame):
                            break
                    
                    # 确保开始自动寻路
                    while True:
                        self.mouse.click_on([xiu_ye_abs_x, xiu_ye_abs_y])
                        human_delay(0.1)
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
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                        if self.is_open_pet_shop(frame):
                            pet_buy_button_match = find_best_match(frame,self.pet_shop_button_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
                            break
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
                            break

                    # 确保开始自动寻路
                    while True:
                        human_delay(2)       
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)                        

                        if not self.is_has_xun_lu(frame):
                            break
                        self.mouse.click_on([xiu_ye_abs_x, xiu_ye_abs_y])
                    
                    # 确保关闭了对话
                    while True:
                        human_delay(1)       
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)                        
                        if not self.is_has_talk(frame):
                            break
                        human_delay(1)
                        pyautogui.press('esc')

                # 战斗
                elif task_type == 3:
                    auto_reset_round()

                    # 确保进入战斗中
                    while True:
                        human_delay(1)       
                        self.mouse.click_on([xiu_ye_abs_x,xiu_ye_abs_y])
                        human_delay(3) 
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                        if self.is_in_fight(frame):
                            human_delay(0.2)
                            break

                    while True:
                        human_delay(2) 
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                        if not self.is_in_fight(frame):
                            human_delay(0.2)
                            break
                    
                    while True:
                        human_delay(0.2) 
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)                        
                        if not self.is_has_talk(frame):
                            break                 
                        human_delay(0.2)
                        pyautogui.press('esc')
                    
                else:
                    print("❌ 未知任务类型")

    # 检测是否在驱魔状态,如果没有,使用驱魔香
    def check_qu_mo(self):
        for hwnd in self.hwnd_list:
            set_current_top(hwnd)
            human_delay(0.1)

            left, top, right, bottom = get_client_rect(hwnd)

            region = make_mss_region(hwnd,ROI)
            shot = self.cv.grab(region)
            frame = np.array(shot)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
            match = find_best_match(frame,self.qu_mo_small_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
            if match is None:
                print("当前不在驱魔状态,使用驱魔香")
                while True:
                    open_bag_keyboard()
                    human_delay(0.1)
                    shot = self.cv.grab(region)
                    frame = np.array(shot)
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)

                    if self.is_open_bag(frame):
                        break

                match = find_best_match(frame,self.qu_mo_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
                abs_x,abs_y = get_abs_x_y_cv(match["bbox"],left, top)
                right_click(self.mouse,[abs_x, abs_y])
                human_delay(0.1)
                open_bag_keyboard()
                self.mouse.move_to([right, bottom]) 

    def run_xiu_lian(self):
        while True:
            if all(v.is_finish_xiu_lian for v in self.hwnd_status.values()):
                print("所有窗口的修炼完成")
                break

            for hwnd in self.hwnd_list:
                if self.hwnd_status[hwnd].is_finish_xiu_lian:
                    continue
                set_current_top(hwnd)
                human_delay(0.1)

                left, top, right, bottom = get_client_rect(hwnd)

                region = make_mss_region(hwnd,ROI)
                shot = self.cv.grab(region)
                frame = np.array(shot)
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                task_type = self.get_xiu_lian_task_type(frame)

                while True:
                    shot = self.cv.grab(region)
                    frame = np.array(shot)
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                    if self.is_open_f9(frame):
                        break
                    human_delay(0.1)
                    pyautogui.press('f9')
                    human_delay(0.1)

                # 判断有没有修炼任务,如果没有,就认为没开始接任务,就从日历开始寻路
                if not self.has_xiu_lian_task(frame):

                    # 打开日历
                    while True:
                        human_delay(0.2)

                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)                    
                        if self.is_open_ri_cheng(frame):
                            break
                        open_calendar()
                        human_delay(1)

                    shot = self.cv.grab(region)
                    frame = np.array(shot)
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

                    match = find_best_match(frame,self.xiu_lian_finish_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
                    if match is None:
                        self.hwnd_status[hwnd].is_finish_xiu_lian = True
                        print(" 当日修炼任务已完成")
                        continue

                    shot = self.cv.grab(region)
                    frame = np.array(shot)
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                    match = find_best_match(frame,self.xiu_lian_no_finish_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
                    xiu_lian_abs_x,xiu_lian_abs_y = get_abs_x_y_cv(match["bbox"],left, top)
                    self.mouse.click_on([xiu_lian_abs_x, xiu_lian_abs_y]) 

                    pyautogui.press('esc')
                    human_delay(0.1)         

                    while True:
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)    

                        match = find_best_match(frame,self.xiu_lian_talk_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
                        if match is not None:
                            break
                        human_delay(2)
                    xiu_lian_talk_abs_x,xiu_lian_talk_abs_y = get_abs_x_y_cv(match["bbox"],left, top)
                    self.mouse.click_on([xiu_lian_talk_abs_x, xiu_lian_talk_abs_y]) 
                    pyautogui.press('esc')
            
                shot = self.cv.grab(region)
                frame = np.array(shot)
                color_result = get_color(frame,'blue')
                if not color_result:
                    print("❌ 未找到蓝色图标")
                    return
                
                xiu_lian_task_abs_x,xiu_lian_task_abs_y = get_abs_x_y_cv(color_result,left, top)

                if task_type == 1:
                    print("开始修练寻物任务")
                    self.mouse.click_on([xiu_lian_task_abs_x, xiu_lian_task_abs_y]) 
                    human_delay(2)

                    while True:
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                        if self.is_open_item_shop(frame):
                            item_buy_button_match = find_best_match(frame,self.item_shop_buy_button_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
                            break
                        human_delay(0.5)

                    # 确保出现"需要"的标志
                    while True:
                        human_delay(1)
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                        if self.is_has_item_xu_qiu(frame):
                            break
                        human_delay(1)

                    # 确保购买成功
                    while True:
                        print("开始购买")
                        abs_x,abs_y = get_abs_x_y_cv(item_buy_button_match["bbox"],left, top)
                        self.mouse.click_on([abs_x, abs_y])
                        human_delay(1)
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)

                        # 如果弹出价格确认
                        item_que_ren_match = find_best_match(frame,self.item_xu_que_ren_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
                        if item_que_ren_match is not None:
                            item_que_ren_abs_x,item_que_ren__abs_y = get_abs_x_y_cv(item_que_ren_match["bbox"],left, top)
                            human_delay(0.1)
                            self.mouse.click_on([item_que_ren_abs_x, item_que_ren__abs_y]) 
                            human_delay(0.1)

                        if not self.is_open_item_shop(frame):
                            print("✅ 修炼任务购买物品成功")
                            human_delay(0.1)

                            break

                    
                    # 确保开始自动寻路
                    while True:
                        human_delay(0.1)
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)    
                        if not self.is_has_xun_lu(frame):
                            print("✅ 修炼任务自动寻路结束")
                            break

                    
                    # 确保关闭了对话
                    while True:
                        human_delay(1)
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)                                
                        if not self.is_has_talk(frame):
                            print("✅ 修炼任务关闭对话框成功")
                            break
                        pyautogui.press('esc')
                # 找人
                if task_type == 2:
                    print("开始修练找人任务")
                    self.mouse.click_on([xiu_lian_task_abs_x, xiu_lian_task_abs_y]) 
                    human_delay(2)

                    # 确保开始自动寻路
                    while True:
                        human_delay(0.1)
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
                            print("✅ 修炼任务关闭对话框成功")
                            break
                        pyautogui.press('esc')                    
                # 打架
                if task_type == 3:
                    print("开始修练疯道人任务")
                    auto_reset_round()
                    self.mouse.click_on([xiu_lian_task_abs_x, xiu_lian_task_abs_y]) 
                    human_delay(2)

                    # 确保开始自动寻路
                    while True:
                        human_delay(0.1)
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)    
                        if not self.is_has_xun_lu(frame):
                            print("✅ 修炼任务自动寻路结束")
                            break                    

                    # 确保关闭了对话
                    while True:
                        human_delay(1)
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)    

                        feng_dao_ren_match = find_best_match(frame,self.xiu_lian_bao_hu_feng_dao_ren_icon,THRESHOLD,SCALES if USE_MULTISCALE else None)
                        if feng_dao_ren_match is not None:
                            item_que_ren_abs_x,item_que_ren__abs_y = get_abs_x_y_cv(feng_dao_ren_match["bbox"],left, top)
                            human_delay(0.1)
                            self.mouse.click_on([item_que_ren_abs_x, item_que_ren__abs_y]) 
                            human_delay(0.1)
                            break
                        human_delay(5)

                    while True:
                        human_delay(2) 
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                        if not self.is_in_fight(frame):
                            print("✅ 修炼任务结束战斗")
                            human_delay(0.2)
                            break
                    
                    while True:
                        human_delay(0.2) 
                        shot = self.cv.grab(region)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)                        
                        if not self.is_has_talk(frame):
                            print("✅ 修炼任务关闭对话框成功")
                            self.hwnd_status[hwnd].is_finish_xiu_lian = True
                            break                 
                        human_delay(0.2)
                        pyautogui.press('esc')