import functools
import os
import re
import time
from enum import Enum, auto

import mss
import traceback
import pyautogui
import win32gui
import win32con
import win32process
import cv2
import numpy as np
from PIL import ImageGrab
from munch import DefaultMunch
from humancursor import SystemCursor

from shenwu.config import *
from shenwu.resource import GameResource
from shenwu.yolo_detector import DEFAULT_ONNX_MODEL, YoloDetector
from shenwu.utils import (human_delay,rand_secs,set_current_top,right_click,get_color,
                          auto_reset_round_keyboard,open_calendar_keyboard,open_bag_keyboard,press_f9,find_all_match,
                          make_mss_region,find_best_match,get_abs_x_y_cv,generate_grid_mask,get_physical_client_rect)

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.2

ROI = (0, 0, 800, 600)

THRESHOLD = 0.7

# 单个窗口连续失败达到该次数就跳过它，避免坏窗口把整个任务拖成死循环
MAX_WINDOW_FAILS = 3

fish_width_start = 380
fish_width_end = 440
fish_height_start = 100
fish_height_end = 180

# 宝塔检测（帧间差分找动态目标）参数，来自 legacy/test_only copy.py
bao_ta_diff_interval = 0.12  # 差分时间窗（秒），0.10 ~ 0.15 秒动态最明显
bao_ta_min_area = 100        # 最小运动轮廓面积（过滤噪点）
bao_ta_max_area = 12000      # 最大运动轮廓面积（过滤大面积刷新）
bao_ta_timeout = 30.0        # 检测超时（秒），超时未找到返回 None

# 修业任务类型(与 resource 图标列表顺序一一对应)
class XiuYeTaskType(Enum):
    WU_ZI = auto()             # 物资
    CHONG_WU = auto()          # 宠物
    TIAO_ZHAN = auto()         # 挑战(战斗)
    LIE_HEN = auto()           # 裂痕
    TIAO_ZHAN_SHOU_XI = auto() # 挑战收悉(与挑战同样走战斗流程)
    TONG_MEN = auto()          # 援助同门

# 真正的游戏窗口标题固定为「幻唐志 - <服务器名>」，服务器名动态变化、可同时存在多个。
# 只认这种格式，避免把资源管理器目录（标题恰好叫「幻唐志」）或本 GUI 窗口当成游戏窗口
GAME_TITLE_PATTERN = re.compile(r"^\s*幻唐志\s*[-–—－]\s*(?P<server>\S.*?)\s*$")

# 资源管理器 / 桌面等壳窗口：即使标题碰巧带「-」也不是游戏窗口
SHELL_WINDOW_CLASSES = {"CabinetWClass", "ExploreWClass", "Progman", "WorkerW",
                        "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}

# 打开名为「幻唐志」的文件夹时，资源管理器标题会是「幻唐志 - 文件资源管理器」，
# 格式上与游戏窗口完全一致，只能靠窗口类 + 这个服务器名黑名单双保险排除
SHELL_TITLE_BLACKLIST = {"文件资源管理器", "资源管理器", "File Explorer",
                         "Windows Explorer"}


def parse_game_title(title):
    """严格匹配「幻唐志 - xxx」，返回服务器名；不匹配返回 None"""
    if not title:
        return None
    # 渲染窗口标题带 RENDER，历史逻辑一直是排除的
    if "RENDER" in title.upper():
        return None
    match = GAME_TITLE_PATTERN.match(title)
    if match is None:
        return None
    server = match.group("server").strip()
    if not server or server in SHELL_TITLE_BLACKLIST:
        return None
    return server


# 修炼任务类型(与 resource 图标列表顺序一一对应)
class XiuLianTaskType(Enum):
    XUN_WU = auto()       # 寻物
    ZHAO_REN = auto()     # 找人
    FENG_DAO_REN = auto() # 疯道人(封到人)

def is_stopped(stop_event):
    """GUI 用来中断长循环的标志位；stop_event 为 None 时永不停止（命令行行为不变）"""
    return stop_event is not None and stop_event.is_set()


@functools.lru_cache(maxsize=1)
def get_controller():
    """懒加载单例：__init__ 会枚举窗口并加载图标，放到导入期会导致 --help 也必须开游戏"""
    return GameController()


class GameController:
    def __init__(self):
        self.hwnd_list = []
        self.cv = mss.MSS()

        # connected_hwnds: 枚举到的全部游戏窗口（GUI 的「已连接」列表）
        # selected_hwnds : GUI 在多选里挑出来的运行目标，为空表示全部已连接窗口
        # hwnd_list      : 队列真正操作的窗口 = 选中窗口（去失效）或全部已连接窗口
        self.connected_hwnds = []
        self.selected_hwnds = []
        self.hwnd_status = {}
        # 当前正在处理的窗口（GUI 用它高亮边框）；每个窗口的连续失败次数
        self.current_hwnd = None
        self.window_fail_counts = {}
        win32gui.EnumWindows(self.get_hwnd, None)
        assert self.hwnd_list , "幻唐志窗口未找到"
        self.connected_hwnds = list(self.hwnd_list)
        print(f"初始化成功,找到{len(self.hwnd_list)}个游戏窗口")
        self.set_radio(self.hwnd_list[0])

        self.mouse = SystemCursor()
        self.resource = GameResource()

        # YOLO 检测器：模型文件缺失时只警告不拦截启动（self.yolo = None），
        # 业务方法统一用 self.detect_centers(frame) 取目标中心坐标
        # if os.path.exists(DEFAULT_ONNX_MODEL):
        #     self.yolo = YoloDetector(DEFAULT_ONNX_MODEL)
        # else:
        #     self.yolo = None
        #     print(f"❌ 未找到 YOLO 模型 {DEFAULT_ONNX_MODEL}，YOLO 检测不可用")

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

    def detect_centers(self, frame):
        """YOLO 检测帧内目标，返回中心坐标 [(cx, cy), ...]（帧内像素坐标）。

        frame 传 BGR 3 通道帧（grab_frame(region, "bgr")），别传默认的灰度帧；
        模型未加载时返回 []。需要完整检测框时直接用 self.yolo.detect(frame)。
        """
        if self.yolo is None:
            return []
        return self.yolo.detect_centers(frame)

    def get_hwnd(self,hwnd, extra):
        """EnumWindows 回调：把新出现的游戏窗口加进 hwnd_list"""
        server = self._match_game_window(hwnd)
        if server is None or hwnd in self.hwnd_list:
            return
        self.hwnd_list.append(hwnd)
        self.hwnd_status[hwnd] = self._make_status(hwnd, server)

    def refresh_hwnds(self):
        """重新枚举游戏窗口（GUI 刷新按钮用）。

        与 get_hwnd 的「只增不减」不同，这里会重建列表：已关闭或标题不再匹配的窗口
        会被剔除，避免 GUI 一直显示已经不存在的实例；仍在的窗口保留原完成状态。
        返回当前窗口数量。
        """
        found = {}

        def collect(hwnd, extra):
            if hwnd in found:
                return
            server = self._match_game_window(hwnd)
            if server is not None:
                found[hwnd] = server

        win32gui.EnumWindows(collect, None)

        status_map = {}
        for hwnd, server in found.items():
            status = self.hwnd_status.get(hwnd) or self._make_status(hwnd, server)
            status.title = win32gui.GetWindowText(hwnd)
            status.server = server
            status_map[hwnd] = status

        dropped = [hwnd for hwnd in self.connected_hwnds if hwnd not in status_map]
        self.connected_hwnds = list(found.keys())
        self.hwnd_status = status_map
        if dropped:
            print(f"已移除 {len(dropped)} 个失效的游戏窗口")
        self._sync_hwnd_list()
        return len(self.connected_hwnds)

    def set_selected_hwnds(self, hwnds):
        """把 GUI 多选的窗口设为队列运行目标，写进 self.hwnd_list。

        传空列表表示「不挑，作用于全部已连接窗口」。返回生效后的 hwnd_list。
        """
        hwnds = [int(hwnd) for hwnd in (hwnds or [])]
        for hwnd in hwnds:
            if not win32gui.IsWindow(hwnd):
                raise ValueError(f"窗口 {hwnd} 已失效，不能加入运行目标")
        self.selected_hwnds = hwnds
        return self._sync_hwnd_list()

    def _sync_hwnd_list(self):
        """按选中结果刷新 hwnd_list：选中（去失效）优先，没选就是全部已连接窗口"""
        if self.selected_hwnds:
            alive = [hwnd for hwnd in self.selected_hwnds if win32gui.IsWindow(hwnd)]
            if len(alive) != len(self.selected_hwnds):
                print("⚠️ 部分选中窗口已关闭，自动从运行目标中移除")
                self.selected_hwnds = alive
            self.hwnd_list = list(alive)
        else:
            self.hwnd_list = list(self.connected_hwnds)

        for hwnd in self.hwnd_list:
            if hwnd not in self.hwnd_status:
                self.hwnd_status[hwnd] = self._make_status(hwnd, "")
        return list(self.hwnd_list)

    def window_infos(self):
        """GUI 列表展示用（只含已连接的游戏窗口）：[(序号, hwnd, 完整标题, 服务器名), ...]"""
        return [(index, hwnd, self.hwnd_status[hwnd].title, self.hwnd_status[hwnd].server)
                for index, hwnd in enumerate(self.connected_hwnds)]

    # ---------- 窗口筛选 ----------

    def _make_status(self, hwnd, server):
        status = DefaultMunch.fromDict(
            {
                "is_finish_xun_you": False,
                "is_finish_xiu_ye": False,
                "is_finish_xiu_lian": False,
            }
        )
        status.title = win32gui.GetWindowText(hwnd)
        status.server = server
        return status

    def _match_game_window(self, hwnd):
        """判断 hwnd 是不是真实游戏窗口：是则返回服务器名，否则返回 None"""
        if not win32gui.IsWindow(hwnd):
            return None

        # 排除本进程自己的窗口（GUI 标题里也带「幻唐志」，靠标题排除不可靠）
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid == os.getpid():
                return None
        except Exception:
            pass

        try:
            if win32gui.GetClassName(hwnd) in SHELL_WINDOW_CLASSES:
                return None
        except Exception:
            pass

        return parse_game_title(win32gui.GetWindowText(hwnd))

    def reset_finish_status(self, *tasks):
        """清空任务完成标记，让同一个任务可以被重复执行。

        tasks: 'xun_you' / 'xiu_ye' / 'xiu_lian'，不传则清空全部
        """
        keys = [f"is_finish_{t}" for t in tasks] or ["is_finish_xun_you",
                                                     "is_finish_xiu_ye",
                                                     "is_finish_xiu_lian"]
        for status in self.hwnd_status.values():
            for key in keys:
                status[key] = False
        # 重新开始时清空失败计数，否则上一轮的失败会累积到跳过阈值
        self.window_fail_counts.clear()
        self.current_hwnd = None

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

    def find(self, frame, icon, threshold=None):
        return find_best_match(frame, icon, THRESHOLD if threshold is None else threshold,self.radio)

    def find_all(self, frame, icon, threshold=None):
        """模板匹配，返回所有匹配结果。"""
        return find_all_match(frame, icon, THRESHOLD if threshold is None else threshold,
                              self.radio)

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
        # display = frame.copy()
        # match = self.find(frame, self.resource.has_talk_icon)


        # x, y, w, h = match["bbox"]
        # cv2.rectangle(display, (x, y), (x + w, y + h), (0, 255, 0), 2)
        # cv2.putText(display, f"{match['score']:.2f}",
        #             (x, max(y - 6, 14)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        # cv2.imshow("resource 图标检测 - 按 q 退出", display)
        # if cv2.waitKey(1) & 0xFF == ord("q"):
        #     return match is not None
        return self.find(frame, self.resource.has_talk_icon,0.8) is not None

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

    def find_xiu_lian_task(self,frame):
        return self.find(frame, self.resource.xiu_lian_task_icon)

    def find_jiao_yi_zhong_xin(self,frame):
        """交易中心可能有多张模板，逐个匹配取分数最高的一次；模板列表为空返回 None"""
        icons = self.resource.jiao_yi_zhong_xin_icon or []
        best = None
        for icon in icons:
            match = self.find(frame, icon)
            if match is not None and (best is None or match["score"] > best["score"]):
                best = match
        return best

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

    # ---------- 一些状态检查 ----------
    
    # 检测是否在驱魔状态,如果没有,使用驱魔香
    def check_qu_mo(self, hwnd_index=0):
        hwnd = self.hwnd_list[hwnd_index]
        self.current_hwnd = hwnd
        try:
            set_current_top(hwnd)
            human_delay(0.1)

            left, top, right, bottom = get_physical_client_rect(hwnd)

            region = make_mss_region(hwnd,self.roi)
            frame = self.grab_frame(region)
            match = self.find(frame, self.resource.qu_mo_small_icon)

            if match is None:
                print("当前不在驱魔状态,使用驱魔香")
                frame = self.wait_until(region, self.is_open_bag, action=open_bag_keyboard, action_first=True,want=True)
                match = self.find(frame, self.resource.qu_mo_icon)
                abs_x,abs_y = get_abs_x_y_cv(match["bbox"],left, top)
                right_click(self.mouse,[abs_x, abs_y])
                self.wait_until(region, self.is_open_bag, action=open_bag_keyboard, action_first=False,want=False)
                self.mouse.move_to([right, bottom])
            else:
                print("当前已经在驱魔状态")
        except Exception:
            traceback.print_exc()
            human_delay(1)

    # 重置回合并确保自动战斗开启
    def reset_round(self, hwnd_index=0):
        """重置回合：自动战斗已开启（有缩小图标）时只重置回合；未开启则重置后再点「自动」。

        返回 True 表示回合已重置；「自动」图标未找到时返回 False。
        """
        hwnd = self.hwnd_list[hwnd_index]
        region = make_mss_region(hwnd, self.roi)

        auto_reset_round_keyboard()

        # 重置回合后重新截图定位「自动」按钮
        frame = self.grab_frame(region, "gray")
        match = self.find(frame, self.resource.zi_dong_icon)
        if match is None:
            return 

        self.click_match(match, region["left"], region["top"])

    # ---------- 业务流程 ----------

    def run_auto_reset_round(self,is_hide=False,stop_event=None):
        print("开始自动重置")
        while True:
            if is_stopped(stop_event):
                break
            for hwnd in self.hwnd_list:
                if is_stopped(stop_event):
                    break
                self.current_hwnd = hwnd
                set_current_top(hwnd)
                auto_reset_round_keyboard()
                if is_hide: 
                    win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
                human_delay(5)

    def run_xun_you(self,stop_event=None):
        failed_hwnds = []
        while True:
            if is_stopped(stop_event):
                break
            if all(self.hwnd_status[h].is_finish_xun_you for h in self.hwnd_list):
                if failed_hwnds:
                    print(f"⚠️ 巡游任务跳过 {len(failed_hwnds)} 个窗口：{failed_hwnds}")
                break

            for hwnd in self.hwnd_list:
                if is_stopped(stop_event):
                    break
                if self.hwnd_status[hwnd].is_finish_xun_you:
                    continue

                self.current_hwnd = hwnd
                try:
                    set_current_top(hwnd)
                    auto_reset_round_keyboard()
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
                    count = self.window_fail_counts.get(hwnd, 0) + 1
                    self.window_fail_counts[hwnd] = count
                    print(f"❌ 巡游任务出错 hwnd={hwnd}（第 {count} 次）")
                    traceback.print_exc()
                    if count >= MAX_WINDOW_FAILS:
                        print(f"⚠️ hwnd={hwnd} 连续失败 {count} 次，跳过该窗口")
                        self.hwnd_status[hwnd].is_finish_xun_you = True
                        failed_hwnds.append(hwnd)
                    human_delay(5)

    def run_fish(self,stop_event=None):
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
            if is_stopped(stop_event):
                break
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

        failed_hwnds = []
        for hwnd in self.hwnd_list:
            self.current_hwnd = hwnd
            try:
                left, top, right, bottom = get_physical_client_rect(hwnd)
                human_delay(1)

                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)

                # 先看看能不能找到该任务
                human_delay(1)
                game_image = ImageGrab.grab(bbox=(left, top, right, bottom))
                ocr_result = self.ocr.get_ocr_from_image(game_image, task_name)

                if not ocr_result:
                    print(f"❌ hwnd={hwnd} 上 OCR 找不到任务「{task_name}」")
                    failed_hwnds.append(hwnd)
                    continue

                print(f"✅ 检测到任务 {task_name}")
                best_bbox, best_text, best_conf = max(ocr_result, key=lambda x: x[2])
                bbox = np.array(best_bbox)
                center_x = np.mean(bbox[:, 0])
                center_y = np.mean(bbox[:, 1])
                abs_x = left + center_x
                abs_y = top + center_y
                self.mouse.click_on([abs_x, abs_y])
                human_delay(1)
            except Exception:
                print(f"❌ hwnd={hwnd} 执行 OCR 任务出错")
                traceback.print_exc()
                failed_hwnds.append(hwnd)
                human_delay(1)

        if failed_hwnds:
            print(f"⚠️ OCR 任务在 {len(failed_hwnds)} 个窗口上失败：{failed_hwnds}")

    # 修业任务
    def run_xiu_ye(self,stop_event=None):
        failed_hwnds = []
        while True:
            if is_stopped(stop_event):
                break
            if all(self.hwnd_status[h].is_finish_xiu_ye for h in self.hwnd_list):
                if failed_hwnds:
                    print(f"⚠️ 修业任务跳过 {len(failed_hwnds)} 个窗口：{failed_hwnds}")
                break

            for hwnd in self.hwnd_list:
                if is_stopped(stop_event):
                    break
                if self.hwnd_status[hwnd].is_finish_xiu_ye:
                    print("所有窗口的修业任务完成")
                    continue

                self.current_hwnd = hwnd
                try:
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
                            open_calendar_keyboard()
                            human_delay(1)

                        self.wait_until(region, self.is_open_ri_cheng, lead=0.2,action=open_calendar_and_wait)

                        frame = self.grab_frame(region, "bgr")
                        match = self.find(frame, self.resource.xiu_ye_finish_icon)
                        if match is not None:
                            self.hwnd_status[hwnd].is_finish_xiu_ye = True
                            print(" 当日修业任务已完成")
                            self.wait_until(region, self.is_open_ri_cheng,want=False, lead=0.2,action=open_calendar_and_wait)
                            continue
                        else:
                            # to-do
                            print("请在任务栏勾选修业任务")
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
                                item_location = generate_grid_mask(frame,self.radio)
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
                        self.close_talk(region, lead=0.5)

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
                        self.wait_until(region, self.is_has_xun_lu, want=False, lead=0.1,
                                        action=lambda: self.mouse.click_on([xiu_ye_abs_x, xiu_ye_abs_y]))

                        # 确保关闭了对话
                        self.close_talk(region, lead=0.1, gap=0.1)

                    # 战斗
                    elif task_type in (XiuYeTaskType.TIAO_ZHAN, XiuYeTaskType.TIAO_ZHAN_SHOU_XI,XiuYeTaskType.TONG_MEN):
                        auto_reset_round_keyboard()
                        print("开始修业战斗任务")

                        # 确保进入战斗中
                        def click_task_and_wait():
                            human_delay(1)
                            self.mouse.click_on([xiu_ye_abs_x, xiu_ye_abs_y])
                            human_delay(3)

                        self.wait_until(region, self.is_in_fight,action=click_task_and_wait, action_first=True)
                        human_delay(0.2)

                        self.wait_until(region, self.is_in_fight, want=False, lead=0.1)
                        human_delay(0.2)

                        self.close_talk(region, lead=0.1, gap=0.1)
                    
                    elif task_type == XiuYeTaskType.LIE_HEN:
                        auto_reset_round_keyboard()
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
                        # auto_reset_round_keyboard()

                        # # 取第二段封印
                        # self.mouse.click_on([xiu_ye_abs_x, xiu_ye_abs_y])

                        # self.wait_until(region, self.is_in_fight, want=False, lead=2)
                        # self.close_talk(region, lead=0.2, gap=0.2)
                    
                    else:
                        print("❌ 未知任务类型")
                except Exception:
                    count = self.window_fail_counts.get(hwnd, 0) + 1
                    self.window_fail_counts[hwnd] = count
                    print(f"❌ 修业任务出错 hwnd={hwnd}（第 {count} 次）")
                    traceback.print_exc()
                    if count >= MAX_WINDOW_FAILS:
                        print(f"⚠️ hwnd={hwnd} 连续失败 {count} 次，跳过该窗口")
                        self.hwnd_status[hwnd].is_finish_xiu_ye = True
                        failed_hwnds.append(hwnd)
                    human_delay(1)
                    continue

    def run_xiu_lian(self,stop_event=None):
        failed_hwnds = []
        while True:
            if is_stopped(stop_event):
                break
            if all(self.hwnd_status[h].is_finish_xiu_lian for h in self.hwnd_list):
                if failed_hwnds:
                    print(f"⚠️ 修炼任务跳过 {len(failed_hwnds)} 个窗口：{failed_hwnds}")
                print("所有窗口的修炼任务完成")
                break

            for hwnd in self.hwnd_list:
                if is_stopped(stop_event):
                    break
                if self.hwnd_status[hwnd].is_finish_xiu_lian:
                    continue
                self.current_hwnd = hwnd
                try:
                    set_current_top(hwnd)
                    human_delay(0.1)

                    left, top, right, bottom = get_physical_client_rect(hwnd)

                    region = make_mss_region(hwnd,self.roi)
                    frame = self.wait_until(region, self.is_open_f9, action=press_f9)

                    # 判断有没有修炼任务,如果没有,就认为没开始接任务,就从日历开始寻路
                    if not self.has_xiu_lian_task(frame):

                        # 打开日历
                        def open_calendar_and_wait():
                            open_calendar_keyboard()
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

                        frame = self.wait_until(region, self.is_open_xiu_lian_talk, gap=0.1)
                        match = self.find(frame, self.resource.xiu_lian_talk_icon)
                        self.click_match(match, left, top)
                        pyautogui.press('esc')

                    human_delay(0.1)
                    frame = self.grab_frame(region)
                    match_result = self.find_xiu_lian_task(frame)
                    # 这个是修炼任务完成后,定位修炼任务的坐标,然后再点击,因为直接用xiu_lian_task_abs_x的话,未完成和完成之后的任务栏的尺寸不一样
                    xiu_lian_abs_x,xiu_lian_abs_y = get_abs_x_y_cv(match_result["bbox"],left, top)

                    frame = self.grab_frame(region)
                    task_type = self.get_xiu_lian_task_type(frame)

                    if task_type == XiuLianTaskType.XUN_WU:
                        print("开始修练寻物任务")

                        frame = self.grab_frame(region)
                        match_result = self.find_jiao_yi_zhong_xin(frame)
                        jiao_yi_zhong_xin_abs_x,jiao_yi_zhong_xin_abs_y = get_abs_x_y_cv(match_result["bbox"],left, top)

                        self.mouse.click_on([jiao_yi_zhong_xin_abs_x, jiao_yi_zhong_xin_abs_y]) 
                        human_delay(2)

                        item_buy_button_match = self.wait_shop_buy_button(
                            region, self.is_open_item_shop,
                            self.resource.item_shop_buy_button_icon, gap=0.5)

                        # 确保购买成功
                        while True:
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

                        # self.wait_until(region, self.is_has_xun_lu, want=False, lead=0.1)
                        # print("修炼任务自动寻路结束")
                        # human_delay(1)

                        while True:
                            frame = self.grab_frame(region, "raw")
                            frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB)
                            self.mouse.click_on([xiu_lian_abs_x, xiu_lian_abs_y]) 

                            if self.give_item(frame):
                                print("给予物品")
                                item_location = generate_grid_mask(frame,self.radio)
                                for item in item_location:
                                    center = item["center"]
                                    self.mouse.click_on([center[0]+left,center[1]+top])
                                    human_delay(0.1)
                                item_que_ding_match = self.find(frame,self.resource.xiu_ye_item_que_ding_icon)                        
                                self.click_match(item_que_ding_match, left, top,delay=0.1)
                                break
                            elif self.is_has_talk(frame_gray):
                                human_delay(0.1)
                                break
                            else:
                                human_delay(0.1)

                        print("修炼任务给予物品成功")

                        # 确保关闭了对话
                        self.close_talk(region, lead=1)
                        continue

                    frame = self.grab_frame(region, "raw")
                    color_result = get_color(frame,'blue',self.radio)

                    if not color_result:
                        print("❌ 未找到蓝色图标")
                        return
                    xiu_lian_task_abs_x,xiu_lian_task_abs_y = get_abs_x_y_cv(color_result,left, top)

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

                    # 找疯道人
                    if task_type == XiuLianTaskType.FENG_DAO_REN:
                        print("开始修练疯道人任务")
                        auto_reset_round_keyboard()

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

                except Exception:
                    count = self.window_fail_counts.get(hwnd, 0) + 1
                    self.window_fail_counts[hwnd] = count
                    print(f"❌ 修炼任务出错 hwnd={hwnd}（第 {count} 次）")
                    traceback.print_exc()
                    if count >= MAX_WINDOW_FAILS:
                        print(f"⚠️ hwnd={hwnd} 连续失败 {count} 次，跳过该窗口")
                        self.hwnd_status[hwnd].is_finish_xiu_lian = True
                        failed_hwnds.append(hwnd)
                    human_delay(1)
                    continue

    # 诊断用：实时可视化 get_color 的检测结果
    def test_get_color(self, color="blue", hwnd_index=0, stop_event=None):
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
            if is_stopped(stop_event):
                break
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
    def icon_names(self):
        """全部图标属性名（诊断面板下拉框用）"""
        return sorted(name for name in vars(self.resource) if name.endswith("_icon"))

    # 挖宝图
    def bao_tu(self,hwnd_index=0):
        hwnd = self.hwnd_list[hwnd_index]
        region = make_mss_region(hwnd, self.roi)

        self.wait_until(region, self.is_open_f9, action=press_f9)
        frame = self.wait_until(region,self.is_open_bag,want=True,action=open_bag_keyboard,action_first=True)

        all_match = self.find_all(frame,self.resource.si_nan_icon,0.7)

    # 玲珑宝塔
    def _detect_bao_ta(self, region, stop_event=None, timeout=None):
        if timeout is None:
            timeout = bao_ta_timeout

        prev_gray = None
        last_check = time.monotonic()

        while not is_stopped(stop_event):
            if time.monotonic() - last_check < bao_ta_diff_interval:
                human_delay(0.05)
                continue

            frame = self.grab_frame(region, "gray")
            gray = cv2.GaussianBlur(frame, (5, 5), 0)

            if prev_gray is None:
                prev_gray = gray
                last_check = time.monotonic()
                continue

            diff = cv2.absdiff(prev_gray, gray)

            # 中央台面 ROI 掩膜：屏蔽顶部状态栏与底部聊天栏
            h, w = diff.shape[:2]
            roi_mask = np.zeros((h, w), dtype=np.uint8)
            roi_mask[int(h * 0.15):int(h * 0.85), int(w * 0.20):int(w * 0.80)] = 255
            diff = cv2.bitwise_and(diff, diff, mask=roi_mask)

            # 阈值二值化与形态学膨胀
            _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
            dilated = cv2.dilate(thresh, kernel, iterations=2)

            # 寻找运动轮廓，按面积与宽高比过滤候选
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            candidates = []
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if bao_ta_min_area < area < bao_ta_max_area:
                    x, y, bw, bh = cv2.boundingRect(cnt)
                    if 0.5 < bw / bh < 2.0:
                        candidates.append((area, (x, y, bw, bh)))

            if candidates:
                # 取动态面积最大的连通块作为目标
                candidates.sort(key=lambda item: item[0], reverse=True)
                return candidates[0][1]

            # 未命中：推进帧对比基准，继续下一轮
            prev_gray = gray
            last_check = time.monotonic()

        return None

    def bao_ta(self, hwnd_index=0, stop_event=None,count=0):
        """宝塔任务：开 f9 面板后用帧间差分找动态宝塔目标，点击并返回其中心坐标。
        返回 (abs_x, abs_y) 屏幕绝对坐标；超时未检测到返回 None。
        """
        _count = 0
        hwnd = self.hwnd_list[hwnd_index]
        region = make_mss_region(hwnd, self.roi)
        left, top, right, bottom = get_physical_client_rect(hwnd)
        
        while _count < count:
            self.reset_round(hwnd_index)
            
            # 如果此层已经通关,一直点击
            while True:
                frame = self.grab_frame(region)
                human_delay(0.1)
                if self.find(frame,self.resource.bao_ta_tong_guan_icon,0.9):
                    match = self.find(frame,self.resource.bao_ta_an_niu_icon)                        
                    self.click_match(match, left, top,delay=0.1)
                    human_delay(0.1)
                else:
                    break

            # 如果一直没有开始挑战按钮,则一直等待
            while True:
                # 检测宝塔战斗目标,等待一会,不然每次战斗完会有弹窗
                human_delay(3)
                bbox = self._detect_bao_ta(region, stop_event)
                if bbox is None:
                    print("❌ 动态目标检测超时，未找到动态目标")
                    return None
                
                print("✅ 检测到动态目标")
                abs_x, abs_y = get_abs_x_y_cv(bbox, region["left"], region["top"])
                human_delay(0.1)
                self.mouse.click_on([abs_x, abs_y])

                human_delay(1)
                frame = self.grab_frame(region)
                item_que_ding_match = self.find(frame,self.resource.bao_ta_kai_shi_tiao_zhan_icon)                        
                if item_que_ding_match:
                    print("检测到开始挑战按钮")
                    self.click_match(item_que_ding_match, region["left"], region["top"],delay=0.1)   
                    human_delay(1)
                    break
                
                # 这一步是移动鼠标，防止被卡住,因为可能会去点击宝箱奖励按钮
                self.mouse.move_to((abs_x + 30, abs_y + 30))
                
            self.wait_until(region,self.is_in_fight,want=False)
            print("战斗结束")
            _count += 1

    def test_resources(self, hwnd_index=0, stop_event=None, threshold=None, icon_names=None):
        """测试 resource 中的图标能否在当前游戏窗口检测到。

        实时截图，命中的图标用绿框 + 匹配分数标注在预览窗口，
        控制台在结果变化时打印「检测到 / 未检测到」清单，按 q 退出。

        icon_names: 只看这几个图标（GameResource 的属性名），不给则用默认图标
        threshold : 临时匹配阈值，不给则用模块级 THRESHOLD
        """
        hwnd = self.hwnd_list[hwnd_index]
        set_current_top(hwnd)
        human_delay(1)
        region = make_mss_region(hwnd, self.roi)

        # self.close_talk(region, lead=1)
        if icon_names:
            icons = {name: getattr(self.resource, name)
                     for name in icon_names if hasattr(self.resource, name)}
        else:
            # 取出 resource 里全部图标(属性名以 _icon 结尾)
            # icons = {name: icon for name, icon in vars(self.resource).items()
            #          if name.endswith("_icon")}
            icons = {'test': self.resource.has_talk_icon }

        if not icons:
            print("❌ resource 中没有可测试的图标")
            return

        last_found = None
        while True:
            if is_stopped(stop_event):
                break
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
                    match = self.find(gray, icon, threshold)
                else:
                    # 彩色图标存储时可能是 BGR 或 RGB，两种顺序都试，取分高的
                    candidates = [m for m in (self.find(bgr, icon, threshold),
                                              self.find(rgb, icon, threshold)) if m]
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

            cv2.imshow("resource 图标检测 - 按 q 退出", display)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

        cv2.destroyAllWindows()