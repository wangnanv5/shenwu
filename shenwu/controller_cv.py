import functools
from enum import Enum, auto

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
from shenwu.resource import GameResource
from shenwu.utils import (human_delay,rand_secs,set_current_top,right_click,get_color,
                          auto_reset_round,open_calendar,open_bag_keyboard,
                          make_mss_region,find_best_match,get_abs_x_y_cv,generate_grid_mask,get_physical_client_rect)

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.2

ROI = (0, 0, 800, 600)

THRESHOLD = 0.7

fish_width_start = 380
fish_width_end = 440
fish_height_start = 100
fish_height_end = 180

# 修业任务类型(与 resource 图标列表顺序一一对应)
class XiuYeTaskType(Enum):
    WU_ZI = auto()             # 物资
    CHONG_WU = auto()          # 宠物
    TIAO_ZHAN = auto()         # 挑战(战斗)
    LIE_HEN = auto()           # 裂痕
    TIAO_ZHAN_SHOU_XI = auto() # 挑战收悉(与挑战同样走战斗流程)
    TONG_MEN = auto()          # 援助同门

# 修炼任务类型(与 resource 图标列表顺序一一对应)
class XiuLianTaskType(Enum):
    XUN_WU = auto()       # 寻物
    ZHAO_REN = auto()     # 找人
    FENG_DAO_REN = auto() # 疯道人(封到人)

def press_f9():
    human_delay(0.1)
    pyautogui.press('f9')
    human_delay(0.1)


class GameController:
    def __init__(self):
        self.hwnd_list = []
        self.cv = mss.MSS()

        self.hwnd_status = {}
        win32gui.EnumWindows(self.get_hwnd, None)
        assert self.hwnd_list , "幻唐志窗口未找到"
        print(f"初始化成功,找到{len(self.hwnd_list)}个游戏窗口")
        self.set_radio(self.hwnd_list[0])

        self.mouse = SystemCursor()
        self.resource = GameResource()

    def set_radio(self,hwnd):
        set_current_top(hwnd)
        left, top, right, bottom = get_physical_client_rect(hwnd)
        window_height = bottom - top
        radio = window_height / ROI[3]
        # self.roi = (0, 0, int(right * radio), int(bottom * radio))
        self.roi = (0, 0, int(ROI[2] * radio), int(ROI[3] * radio))
        self.radio = radio
        print(f"缩放比例: {radio}")
    
    @functools.cached_property
    def ocr(self):
        # RapidOCR 构造时要加载 ONNX 模型，放在 __init__ 会拖慢所有命令
        from shenwu.ocr import Ocr
        return Ocr()

    def get_hwnd(self,hwnd, extra):
        status = DefaultMunch.fromDict(
            {
                "is_finish_xun_you": False,
                "is_finish_xiu_ye": False,
                "is_finish_xiu_lian": False,
            }
        )

        title = win32gui.GetWindowText(hwnd)
        if ("幻唐志" in title) and ("RENDER" not in title):
            if hwnd in self.hwnd_list:
                return
            self.hwnd_list.append(hwnd)
            self.hwnd_status[hwnd] = status

    # ---------- 底层：截图 / 匹配 / 轮询 ----------

    def grab_frame(self, region, mode="gray"):
        """截取区域并返回帧。

        mode: gray(默认,配灰度图标) / bgr(配 xiu_lian_finish_icon 这类彩色图标)
              / raw(不转换,get_color 需要原始 BGRA)
        """
        frame = np.array(self.cv.grab(region))
        if mode == "raw":
            return frame
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY if mode == "gray" else cv2.COLOR_BGRA2BGR)

    def find(self, frame, icon):
        """模板匹配，固定使用模块级 THRESHOLD / USE_MULTISCALE / SCALES"""
        return find_best_match(frame, icon, THRESHOLD, self.radio)

    def wait_until(self, region, predicate, want=True, action=None,
                   action_first=False, lead=1, gap=1, mode="gray"):
        """轮询截图直到 predicate(frame) == want，返回命中的那一帧。

        单次循环：[lead 秒] -> (action_first 时先 action) -> 截图 -> 判定
                  -> 命中返回 / 未命中 -> (否则 action) -> [gap 秒]

        action_first=True 用于「目标状态还不存在、必须先操作一次」的场景
        （开背包、点购买、点击进入战斗）；f9 / 日历这类开关键必须保持 False，
        否则第一轮就会把已打开的面板关掉。
        """
        while True:
            if lead:
                human_delay(lead)
            if action_first and action is not None:
                action()
            frame = self.grab_frame(region, mode)
            if predicate(frame) == want:
                return frame
            if not action_first and action is not None:
                action()
            if gap:
                human_delay(gap)

    def close_talk(self, region, lead=1.0, gap=0.0):
        """循环按 esc 直到 npc 对话弹框消失"""
        def press_esc():
            if gap:
                human_delay(gap)
            print("按 esc 关闭对话框")
            pyautogui.press('esc')
        self.wait_until(region, self.is_has_talk, want=False, lead=lead, action=press_esc)

    def wait_shop_buy_button(self, region, shop_predicate, buy_button_icon, gap=0.5):
        """等商店页面出现，返回其购买按钮的 match"""
        frame = self.wait_until(region, shop_predicate, gap=gap)
        return self.find(frame, buy_button_icon)

    def click_match(self, match, left, top, delay=0.0):
        """把 match["bbox"] 换算成屏幕坐标并点击，delay 是点击前的等待"""
        if delay:
            human_delay(delay)
        abs_x, abs_y = get_abs_x_y_cv(match["bbox"], left, top)
        self.mouse.click_on([abs_x, abs_y])

    # ---------- 页面判断 ----------

    def is_in_fight(self,frame):
        return self.find(frame, self.resource.is_in_fight_icon) is not None

    def is_open_pet_shop(self,frame):
        return self.find(frame, self.resource.pet_shop_icon) is not None

    def is_open_item_shop(self,frame):
        return self.find(frame, self.resource.item_shop_icon) is not None

    def is_has_item_xu_qiu(self,frame):
        return self.find(frame, self.resource.item_xu_qiu_icon) is not None

    def is_open_ri_cheng(self,frame):
        return self.find(frame, self.resource.ri_cheng_icon) is not None

    def is_has_talk(self,frame):
        return self.find(frame, self.resource.has_talk_icon) is not None

    def is_has_xun_lu(self,frame):
        return self.find(frame, self.resource.has_xun_lu_icon) is not None

    def is_open_bag(self,frame):
        return self.find(frame, self.resource.bag_icon) is not None

    def is_open_f9(self,frame):
        return self.find(frame, self.resource.f9_icon) is not None

    def is_open_xiu_lian_talk(self,frame):
        return self.find(frame, self.resource.xiu_lian_talk_icon) is not None

    def has_xiu_lian_task(self,frame):
        return self.find(frame, self.resource.xiu_lian_task_icon) is not None

    def is_bao_hu_feng_dao_ren(self,frame):
        return self.find(frame, self.resource.xiu_lian_bao_hu_feng_dao_ren_icon) is not None

    def find_xiu_ye_task(self,frame):
        return self.find(frame, self.resource.has_xiu_ye_task_icon)

    def give_item(self,frame):
        return self.find(frame, self.resource.xiu_ye_give_item_icon) is not None

    def _task_type(self,frame,icons,task_enum,default=None):
        """按 icons 顺序匹配任务类型，命中返回 task_enum 对应成员，全不命中返回 default"""
        for icon, member in zip(icons, task_enum):
            if self.find(frame, icon) is not None:
                return member
        return default

    def get_xiu_ye_task_type(self,frame):
        return self._task_type(frame, [self.resource.xiu_ye_wu_zi_icon,
                                       self.resource.xiu_ye_chong_wu_icon,
                                       self.resource.xiu_ye_tiao_zhan_icon,
                                       self.resource.xiu_ye_lie_hen_icon,
                                       self.resource.xiu_ye_tiao_zhan_shou_xi_icon,
                                       self.resource.xiu_ye_tong_men_icon],
                               XiuYeTaskType)

    def get_xiu_lian_task_type(self,frame):
        return self._task_type(frame, [self.resource.xiu_lian_xun_wu_icon,
                                       self.resource.xiu_lian_zhao_ren_icon,
                                       self.resource.xiu_lian_feng_dao_ren_icon,
                                       ],
                               XiuLianTaskType)

    # ---------- 业务流程 ----------

    def run_auto_reset_round(self,is_hide=False):
        print("开始自动重置")
        while True:
            for hwnd in self.hwnd_list:
                set_current_top(hwnd)
                auto_reset_round()
                if is_hide: 
                    win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
                human_delay(5)

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
                    left, top, right, bottom = get_physical_client_rect(hwnd)

                    region = make_mss_region(hwnd,self.roi)

                    # 点击对话框，进入战斗
                    frame = self.grab_frame(region)

                    if self.is_in_fight(frame):
                        human_delay(5)
                        continue

                    finish_match = self.find(frame, self.resource.xun_you_finish_icon)

                    if finish_match is not None:
                        self.hwnd_status[hwnd].is_finish_xun_you = True
                        self.click_match(finish_match, left, top, delay=1)
                        human_delay(5)

                    else:
                        match = self.find(frame, self.resource.xun_you_start_fight_icon)

                        if match is None:
                            print("模式匹配结果为空")
                            continue

                        self.click_match(match, left, top, delay=1)
                        human_delay(5)
                    continue
                except Exception:
                    print("巡游任务出错:")
                    traceback.print_exc() 
                    human_delay(5)

    def run_fish(self):
        win32gui.EnumWindows(self.get_hwnd, None)
        assert self.hwnd_list , "幻唐志窗口未找到"

        hwnd = self.hwnd_list[0]
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)

        # 抛竿
        pyautogui.press('f1')
        human_delay(2)
        pyautogui.press('f1')

        left, top, right, bottom = get_physical_client_rect(hwnd)
        human_delay(1)

        while True:
            game_image = ImageGrab.grab(bbox=(left+fish_width_start,top + fish_height_start, left+fish_width_end, top+fish_height_end))

            try:
                start_fight_location = pyautogui.locate(str(you_yu_path),game_image, grayscale=True,confidence=0.7)
            except Exception as e:
                print(f"还未钓到鱼 {e}")
                human_delay(1)
                continue

            abs_x = left + start_fight_location.left + start_fight_location.width // 2
            abs_y = top + start_fight_location.top + start_fight_location.height // 2

            pyautogui.moveTo(abs_x,abs_y, duration=rand_secs(0.2))
            self.mouse.perform_click()
            human_delay(1)
            break

    def run_auto_task(self,task_name):
        win32gui.EnumWindows(self.get_hwnd, None)
        assert self.hwnd_list , "幻唐志窗口未找到"

        hwnd = self.hwnd_list[0]

        left, top, right, bottom = get_physical_client_rect(hwnd)
        human_delay(1)

        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)

        # 先看看能不能找到该任务
        human_delay(1)
        game_image = ImageGrab.grab(bbox=(left, top, right, bottom))
        ocr_result = self.ocr.get_ocr_from_image(game_image, task_name)

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

    # 修业任务
    def run_xiu_ye(self):
        while True:
            if all(v.is_finish_xiu_ye for v in self.hwnd_status.values()):
                break

            for hwnd in self.hwnd_list:
                if self.hwnd_status[hwnd].is_finish_xiu_ye:
                    print("所有窗口的修业任务完成")
                    continue

                set_current_top(hwnd)
                human_delay(0.1)
                
                # 检查页面是否有修业任务
                left, top, right, bottom = get_physical_client_rect(hwnd)

                region = make_mss_region(hwnd,self.roi)
                frame = self.grab_frame(region)
                match_result = self.find_xiu_ye_task(frame)

                if match_result is None:
                    # 打开日历
                    def open_calendar_and_wait():
                        open_calendar()
                        human_delay(1)

                    self.wait_until(region, self.is_open_ri_cheng, lead=0.2,
                                    action=open_calendar_and_wait)

                    frame = self.grab_frame(region, "bgr")
                    match = self.find(frame, self.resource.xiu_ye_finish_icon)
                    if match is not None:
                        self.hwnd_status[hwnd].is_finish_xiu_ye = True
                        print(" 当日修业任务已完成")
                        self.wait_until(region, self.is_open_ri_cheng,want=False, lead=0.2,action=open_calendar_and_wait)
                        continue
                    else:
                        # to-do
                        print("界面和日历都未检测到修业任务,失败.")
                        self.hwnd_status[hwnd].is_finish_xiu_ye = True
                        human_delay(0.2)
                        continue
                    # frame = self.grab_frame(region)
                    # match = self.find(frame, self.resource.xiu_lian_no_finish_icon)
                    # self.click_match(match, left, top)
                    # pyautogui.press('esc')
                    # human_delay(0.1)

                    # frame = self.wait_until(region, self.is_open_xiu_lian_talk, gap=2)
                    # match = self.find(frame, self.resource.xiu_lian_talk_icon)
                    # self.click_match(match, left, top)
                    # pyautogui.press('esc')               

                frame = self.wait_until(region, self.is_open_f9, action=press_f9)
                task_type = self.get_xiu_ye_task_type(frame)
                
                if task_type is None:
                    print("❌ 修业任务类型错误")
                    continue

                print(f"✅ 检测到修业任务 {task_type}")
                xiu_ye_abs_x,xiu_ye_abs_y = get_abs_x_y_cv(match_result["bbox"],left, top)
                human_delay(0.2)

                # 物资
                if task_type == XiuYeTaskType.WU_ZI:
                    print("开始修业物资任务")
                    self.mouse.click_on([xiu_ye_abs_x,xiu_ye_abs_y])
                    human_delay(1)

                    item_buy_button_match = self.wait_shop_buy_button(
                        region, self.is_open_item_shop,
                        self.resource.item_shop_buy_button_icon, gap=0.5)

                    while True:
                        self.click_match(item_buy_button_match, left, top)
                        human_delay(1)
                        frame = self.grab_frame(region)

                        print("开始购买")
                        # 如果弹出价格确认
                        item_que_ren_match = self.find(frame, self.resource.item_xu_que_ren_icon)
                        if item_que_ren_match is not None:
                            self.click_match(item_que_ren_match, left, top, delay=0.1)
                            human_delay(1)
                            frame = self.grab_frame(region)

                        if not self.is_open_item_shop(frame):
                            print("修业任务购买物品成功")
                            human_delay(0.1)
                            break

                    # 确保开始自动寻路
                    def click_task():
                        self.mouse.click_on([xiu_ye_abs_x, xiu_ye_abs_y])
                        human_delay(0.1)

                    self.wait_until(region, self.is_has_xun_lu, want=False,action=click_task, action_first=True)

                    while True:
                        frame = self.grab_frame(region, "raw")
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB)

                        if self.give_item(frame):
                            print("给予物品")
                            item_location = generate_grid_mask(frame)
                            for item in item_location:
                                center = item["center"]
                                self.mouse.click_on([center[0]+left,center[1]+top])
                                human_delay(0.1)
                            item_que_ding_match = self.find(frame,self.resource.xiu_ye_item_que_ding_icon)                        
                            self.click_match(item_que_ding_match, left, top,delay=0.1)
                        else:
                            break
                    print("给予物品成功")
                    # 确保关闭了对话
                    self.close_talk(region, lead=1)

                # 宠物
                elif task_type == XiuYeTaskType.CHONG_WU:
                    print("开始修业宠物任务")
                    self.mouse.click_on([xiu_ye_abs_x,xiu_ye_abs_y])
                    human_delay(1) 

                    # 检测是否打开了宠物购买页面
                    pet_buy_button_match = self.wait_shop_buy_button(
                        region, self.is_open_pet_shop,
                        self.resource.pet_shop_button_icon, gap=1)
                    print("✅ 检测到宠物页面")

                    def click_buy():
                        self.click_match(pet_buy_button_match, left, top)
                        human_delay(1)

                    self.wait_until(region, self.is_open_pet_shop, want=False,
                                    action=click_buy, action_first=True)
                    print("宠物购买成功")
                    # 确保开始自动寻路
                    self.wait_until(region, self.is_has_xun_lu, want=False, lead=2,
                                    action=lambda: self.mouse.click_on([xiu_ye_abs_x, xiu_ye_abs_y]))

                    # 确保关闭了对话
                    self.close_talk(region, lead=1, gap=1)

                # 战斗
                elif task_type in (XiuYeTaskType.TIAO_ZHAN, XiuYeTaskType.TIAO_ZHAN_SHOU_XI,XiuYeTaskType.TONG_MEN):
                    auto_reset_round()
                    print("开始修业战斗任务")

                    # 确保进入战斗中
                    def click_task_and_wait():
                        human_delay(1)
                        self.mouse.click_on([xiu_ye_abs_x, xiu_ye_abs_y])
                        human_delay(3)

                    self.wait_until(region, self.is_in_fight,action=click_task_and_wait, action_first=True)
                    human_delay(0.2)

                    self.wait_until(region, self.is_in_fight, want=False, lead=2)
                    human_delay(0.2)

                    self.close_talk(region, lead=1, gap=1)
                    
                elif task_type == XiuYeTaskType.LIE_HEN:
                    auto_reset_round()
                    print("开始修业裂痕任务")

                    def click_task_and_wait():
                        human_delay(1)
                        self.mouse.click_on([xiu_ye_abs_x, xiu_ye_abs_y])
                        human_delay(3)

                    # 第一次封印,封印结束出现对话框
                    self.wait_until(region, self.is_in_fight,action=click_task_and_wait, action_first=True)
                    human_delay(0.2)

                    self.wait_until(region, self.is_in_fight, want=False, lead=2)
                    human_delay(0.2)
                    
                    self.close_talk(region, lead=1, gap=1)
                    # auto_reset_round()

                    # # 取第二段封印
                    # self.mouse.click_on([xiu_ye_abs_x, xiu_ye_abs_y])

                    # self.wait_until(region, self.is_in_fight, want=False, lead=2)
                    # self.close_talk(region, lead=0.2, gap=0.2)
                    
                else:
                    print("❌ 未知任务类型")

    # 检测是否在驱魔状态,如果没有,使用驱魔香
    def check_qu_mo(self):
        for hwnd in self.hwnd_list:
            set_current_top(hwnd)
            human_delay(0.1)

            left, top, right, bottom = get_physical_client_rect(hwnd)

            region = make_mss_region(hwnd,self.roi)
            frame = self.grab_frame(region)
            match = self.find(frame, self.resource.qu_mo_small_icon)

            if match is None:
                print("当前不在驱魔状态,使用驱魔香")

                def open_bag():
                    open_bag_keyboard()
                    human_delay(0.1)

                frame = self.wait_until(region, self.is_open_bag, action=open_bag, action_first=True)
                match = self.find(frame, self.resource.qu_mo_icon)
                abs_x,abs_y = get_abs_x_y_cv(match["bbox"],left, top)
                right_click(self.mouse,[abs_x, abs_y])
                human_delay(0.1)
                open_bag_keyboard()
                self.mouse.move_to([right, bottom]) 
            else:
                print("当前在驱魔状态")

    def run_xiu_lian(self):
        while True:
            if all(v.is_finish_xiu_lian for v in self.hwnd_status.values()):
                print("所有窗口的修炼任务完成")
                break

            for hwnd in self.hwnd_list:
                if self.hwnd_status[hwnd].is_finish_xiu_lian:
                    continue
                set_current_top(hwnd)
                human_delay(0.1)

                left, top, right, bottom = get_physical_client_rect(hwnd)

                region = make_mss_region(hwnd,self.roi)
                frame = self.wait_until(region, self.is_open_f9, action=press_f9)
                # 判断有没有修炼任务,如果没有,就认为没开始接任务,就从日历开始寻路
                if not self.has_xiu_lian_task(frame):

                    # 打开日历
                    def open_calendar_and_wait():
                        open_calendar()
                        human_delay(1)

                    self.wait_until(region, self.is_open_ri_cheng, lead=0.2,
                                    action=open_calendar_and_wait)

                    frame = self.grab_frame(region, "bgr")
                    match = self.find(frame, self.resource.xiu_lian_finish_icon)
                    if match is not None:
                        self.hwnd_status[hwnd].is_finish_xiu_lian = True
                        print(" 当日修炼任务已完成")
                        continue

                    frame = self.grab_frame(region)
                    match = self.find(frame, self.resource.xiu_lian_no_finish_icon)
                    self.click_match(match, left, top)
                    pyautogui.press('esc')
                    human_delay(0.1)

                    frame = self.wait_until(region, self.is_open_xiu_lian_talk, gap=2)
                    match = self.find(frame, self.resource.xiu_lian_talk_icon)
                    self.click_match(match, left, top)
                    pyautogui.press('esc')
            
                frame = self.grab_frame(region, "raw")
                color_result = get_color(frame,'blue',self.radio)

                if not color_result:
                    print("❌ 未找到蓝色图标")
                    return
                
                frame = self.grab_frame(region)
                task_type = self.get_xiu_lian_task_type(frame)

                xiu_lian_task_abs_x,xiu_lian_task_abs_y = get_abs_x_y_cv(color_result,left, top)
                if task_type == XiuLianTaskType.XUN_WU:
                    print("开始修练寻物任务")
                    self.mouse.click_on([xiu_lian_task_abs_x, xiu_lian_task_abs_y]) 
                    human_delay(2)

                    item_buy_button_match = self.wait_shop_buy_button(
                        region, self.is_open_item_shop,
                        self.resource.item_shop_buy_button_icon, gap=0.5)

                    # 确保购买成功
                    while True:
                        print("开始购买")
                        self.click_match(item_buy_button_match, left, top)
                        human_delay(1)
                        frame = self.grab_frame(region)

                        # 如果弹出价格确认
                        item_que_ren_match = self.find(frame, self.resource.item_xu_que_ren_icon)
                        if item_que_ren_match is not None:
                            self.click_match(item_que_ren_match, left, top, delay=0.1)
                            human_delay(1)
                            frame = self.grab_frame(region)

                        if not self.is_open_item_shop(frame):
                            print("修炼任务购买物品成功")
                            human_delay(0.1)
                            break

                    self.wait_until(region, self.is_has_xun_lu, want=False, lead=0.1)
                    print("修炼任务自动寻路结束")
                    human_delay(1)

                    while True:
                        frame = self.grab_frame(region, "raw")
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB)

                        if self.give_item(frame):
                            print("给予物品")
                            item_location = generate_grid_mask(frame)
                            for item in item_location:
                                center = item["center"]
                                self.mouse.click_on([center[0]+left,center[1]+top])
                                human_delay(0.1)
                            item_que_ding_match = self.find(frame,self.resource.xiu_ye_item_que_ding_icon)                        
                            self.click_match(item_que_ding_match, left, top,delay=0.1)
                        else:
                            break

                    print("修炼任务给予物品成功")

                    # 确保关闭了对话
                    self.close_talk(region, lead=1)

                # 找人
                if task_type == XiuLianTaskType.ZHAO_REN:
                    print("开始修练找人任务")
                    self.mouse.click_on([xiu_lian_task_abs_x, xiu_lian_task_abs_y]) 
                    human_delay(2)

                    # 确保开始自动寻路
                    self.wait_until(region, self.is_has_xun_lu, want=False, lead=0.1)

                    # 确保关闭了对话
                    self.close_talk(region, lead=1)
                    print("✅ 修炼任务关闭对话框成功")

                # 打架
                if task_type == XiuLianTaskType.FENG_DAO_REN:
                    print("开始修练疯道人任务")
                    auto_reset_round()

                    def click_task_and_wait():
                        self.mouse.click_on([xiu_lian_task_abs_x, xiu_lian_task_abs_y])
                        human_delay(4)

                    # 确保开始自动寻路
                    self.wait_until(region, self.is_in_fight,action=click_task_and_wait, action_first=True)
                    print("开始进入修炼战斗")

                    self.wait_until(region, self.is_in_fight, want=False, lead=2)
                    print("修炼任务结束战斗")

                    self.close_talk(region, lead=1, gap=1)
                    print("修炼任务关闭对话框成功")
                    self.hwnd_status[hwnd].is_finish_xiu_lian = True

    # 诊断用：实时可视化 get_color 的检测结果
    def test_get_color(self, color="blue", hwnd_index=0):
        """实时可视化 utils.get_color 的检测结果。

        预览窗口标注两部分：
        - 黄色细框：get_color 内部的裁剪搜索区域(比例与 utils.get_color 保持一致)
        - 绿色粗框：get_color 返回的 bbox，未命中时只有黄框
        控制台在结果变化时打印检测状态，按 q 退出。
        """
        hwnd = self.hwnd_list[hwnd_index]
        set_current_top(hwnd)
        human_delay(1)

        last_result = None
        while True:
            # 每帧重新生成区域，窗口移动也能跟上
            region = make_mss_region(hwnd, self.roi)
            # get_color 内部走 BGRA2RGB，必须喂原始 raw 帧
            raw = self.grab_frame(region, "raw")
            display = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)

            # 画裁剪搜索区域(0.66, 0.27) ~ (0.95, 0.38)
            h, w = raw.shape[:2]
            x1, y1 = int(w * 0.66), int(h * 0.27)
            x2, y2 = int(w * 0.95), int(h * 0.38)
            cv2.rectangle(display, (x1, y1), (x2, y2), (0, 255, 255), 1)

            result = get_color(raw, color)
            if result:
                x, y, bw, bh = result
                cv2.rectangle(display, (x, y), (x + bw, y + bh), (0, 255, 0), 2)
                cv2.putText(display, f"{color} bbox=({x},{y},{bw},{bh})",
                            (x, max(y - 6, 14)), cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, (0, 255, 0), 1)

            if result != last_result:
                last_result = result
                if result:
                    print(f"✅ 检测到 {color}: bbox={result}")
                else:
                    print(f"❌ 未检测到 {color}")

            cv2.imshow(f"get_color 检测({color}) - 按 q 退出", display)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

        cv2.destroyAllWindows()

    # 诊断用：检测 resource 中所有图标是否出现在当前游戏窗口
    def test_resources(self, hwnd_index=0):
        """测试 resource 中的全部图标能否在当前游戏窗口检测到。

        实时截图，命中的图标用绿框 + 匹配分数标注在预览窗口，
        控制台在结果变化时打印「检测到 / 未检测到」清单，按 q 退出。
        """
        hwnd = self.hwnd_list[hwnd_index]
        set_current_top(hwnd)
        human_delay(1)

        # 取出 resource 里全部图标(属性名以 _icon 结尾)
        # icons = {name: icon for name, icon in vars(self.resource).items()
        #          if name.endswith("_icon")}
        icons = {'test': self.resource.xiu_ye_finish_icon }

        if not icons:
            print("❌ resource 中没有可测试的图标")
            return

        last_found = None
        while True:
            # 每帧重新生成区域，窗口移动也能跟上
            region = make_mss_region(hwnd, self.roi)
            gray = self.grab_frame(region, "gray")
            bgr = self.grab_frame(region, "bgr")
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

            display = bgr.copy()
            found, missing = [], []
            for name, icon in icons.items():
                if icon.ndim == 2:
                    # 灰度图标配灰度帧
                    match = self.find(gray, icon)
                else:
                    # 彩色图标存储时可能是 BGR 或 RGB，两种顺序都试，取分高的
                    candidates = [m for m in (self.find(bgr, icon), self.find(rgb, icon)) if m]
                    match = max(candidates, key=lambda m: m["score"]) if candidates else None

                if match is None:
                    missing.append(name)
                    continue

                x, y, w, h = match["bbox"]
                cv2.rectangle(display, (x, y), (x + w, y + h), (0, 255, 0), 2)
                cv2.putText(display, f"{name} {match['score']:.2f}",
                            (x, max(y - 6, 14)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                found.append(name)

            if found != last_found:
                last_found = found
                print(f"\n✅ 检测到 {len(found)}/{len(icons)}: {', '.join(found) or '无'}")
                print(f"❌ 未检测到 {len(missing)}/{len(icons)}: {', '.join(missing) or '无'}")

            cv2.imshow("resource 图标检测 - 按 q 退出", display)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

        cv2.destroyAllWindows()

