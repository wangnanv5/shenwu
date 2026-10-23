import functools
import os
import re
import threading
import time
from enum import Enum, auto

import traceback
import win32gui
import win32con
import win32process
import cv2
import numpy as np
from munch import DefaultMunch

from shenwu.config import *
from shenwu.resource import GameResource
from shenwu.yolo_detector import DEFAULT_ONNX_MODEL, YoloDetector
from shenwu.utils import *

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
bao_ta_diff_thresh = 25      # 帧间差分二值化阈值（0-255）

# 中央台面 ROI 掩膜比例：屏蔽顶部状态栏与底部聊天栏，只检测台面区域。
# 可用 test_bao_ta_mask 实时调参验证后再回填这里。
bao_ta_mask_top = 0.08       # 上边界（高度比例）
bao_ta_mask_bottom = 0.75    # 下边界
bao_ta_mask_left = 0.10      # 左边界（宽度比例）
bao_ta_mask_right = 0.90     # 右边界

# 开背包（点击 bag_small）参数
open_bag_retries = 3       # 定位+点击的最大尝试次数
open_bag_check_rounds = 3  # 每次点击后确认 is_open_bag 的轮数
open_bag_check_gap = 0.3   # 确认轮询间隔（秒）

# 挖宝 YOLO 检测参数
wa_bao_round_gap = 3.0     # 每轮所有目标点完后的等待秒数，再进下一轮检测

def make_bao_ta_mask(shape, top=None, bottom=None, left=None, right=None):
    """构造宝塔检测的中央台面 ROI 掩膜（与 _detect_bao_ta 实际使用的完全一致）

    :param shape: 帧的 (h, w) 或完整 shape
    :param top/bottom/left/right: 四边裁剪比例（0~1），缺省用模块级
                                  bao_ta_mask_* 常量
    :return: (mask, rect) —— mask 为 uint8 单通道（白=参与检测区域）；
             rect=(x1, y1, x2, y2) 为覆盖范围的像素坐标
    """
    top = bao_ta_mask_top if top is None else top
    bottom = bao_ta_mask_bottom if bottom is None else bottom
    left = bao_ta_mask_left if left is None else left
    right = bao_ta_mask_right if right is None else right

    h, w = shape[:2]
    x1, y1 = int(w * left), int(h * top)
    x2, y2 = int(w * right), int(h * bottom)
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[y1:y2, x1:x2] = 255
    return mask, (x1, y1, x2, y2)

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

        # print(self.hwnd_list)
        self.resource = GameResource()
        # self.hwnd_list = self.hwnd_list[0]
        # YOLO 检测器：模型文件缺失时只警告不拦截启动（self.yolo = None），
        # 业务方法统一用 self.detect_centers(frame) 取目标中心坐标
        if os.path.exists(DEFAULT_ONNX_MODEL):
            self.yolo = YoloDetector(DEFAULT_ONNX_MODEL)
        else:
            self.yolo = None
            print(f"❌ 未找到 YOLO 模型 {DEFAULT_ONNX_MODEL}，YOLO 检测不可用")

    def set_radio(self,hwnd):
        restore_window(hwnd)
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

    def reset_finish_status(self, *tasks, hwnd=None):
        """清空任务完成标记，让同一个任务可以被重复执行。

        tasks: 'xun_you' / 'xiu_ye' / 'xiu_lian'，不传则清空全部
        hwnd : 只重置该窗口（多窗口并行运行时各线程互不清对方的标记）；
               不传则重置全部窗口（旧行为）
        """
        keys = [f"is_finish_{t}" for t in tasks] or ["is_finish_xun_you",
                                                     "is_finish_xiu_ye",
                                                     "is_finish_xiu_lian"]
        if hwnd is not None:
            statuses = [self.hwnd_status[hwnd]] if hwnd in self.hwnd_status else []
        else:
            statuses = list(self.hwnd_status.values())
        for status in statuses:
            for key in keys:
                status[key] = False
        # 重新开始时清空失败计数，否则上一轮的失败会累积到跳过阈值
        if hwnd is None:
            self.window_fail_counts.clear()
            self.current_hwnd = None
        else:
            self.window_fail_counts.pop(hwnd, None)

    # ---------- 底层：截图 / 匹配 / 轮询 ----------

    def grab_frame(self, region, mode="gray"):
        """截取窗口客户区并返回帧（WGC 截图，窗口无需置顶、可被遮挡）。

        region: make_region 返回的 dict，或直接传 hwnd
        mode  : gray(默认,配灰度图标) / bgr(配 xiu_lian_finish_icon 这类彩色图标)
                / raw(不转换的 BGR 帧,get_color / generate_grid_mask 需要)
        帧统一裁剪到 self.roi，帧内坐标系与旧版截图完全一致。
        """
        hwnd = region["hwnd"] if isinstance(region, dict) else region
        frame = capture_client_only(hwnd)

        # 裁剪到 roi（roi 始终从 (0,0) 开始，等价于旧版的子区域截图）
        rw, rh = self.roi[2], self.roi[3]
        fh, fw = frame.shape[:2]
        frame = frame[:min(rh, fh), :min(rw, fw)]

        if mode == "raw" or mode == "bgr":
            return frame
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    def find(self, frame, icon, threshold=None):
        return find_best_match(frame, icon, THRESHOLD if threshold is None else threshold,self.radio)

    def find_all(self, frame, icon, threshold=None):
        """模板匹配，返回所有匹配结果。"""
        return find_all_match(frame, icon, THRESHOLD if threshold is None else threshold,
                              self.radio)

    def wait_until(self, region, predicate, want=True, action=None,
                   action_first=False, lead=1, gap=1, mode="gray"):
        """轮询截图直到 predicate(frame) == want，返回命中的那一帧。

        region: make_region 返回的 dict，或直接传 hwnd
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
        hwnd = region["hwnd"] if isinstance(region, dict) else region

        def press_esc():
            if gap:
                human_delay(gap)
            print("按 esc 关闭对话框")
            windows_key(hwnd, 'esc')
        self.wait_until(region, self.is_has_talk, want=False, lead=lead, action=press_esc)

    def wait_shop_buy_button(self, region, shop_predicate, buy_button_icon, gap=0.5):
        """等商店页面出现，返回其购买按钮的 match"""
        frame = self.wait_until(region, shop_predicate, gap=gap)
        return self.find(frame, buy_button_icon)

    def click_match(self, match, region, delay=0.0):
        """把 match["bbox"] 中心用消息级点击落到窗口客户区，delay 是点击前的等待

        region: make_region 返回的 dict，或直接传 hwnd
        """
        if delay:
            human_delay(delay)
        x, y = get_abs_x_y_cv_windows(match["bbox"])
        hwnd = region["hwnd"] if isinstance(region, dict) else region
        windows_click(hwnd, x, y)

    def click_ri_cheng_small(self, region):
        """识别并点击屏幕上的日程小图标（ri_cheng_small_icon），打开日历

        替代 Alt+Y 组合键的纯后台实现。region: make_region 的 dict 或 hwnd。

        :return: True = 识别到并已点击；False = 未识别到
        """
        hwnd = region["hwnd"] if isinstance(region, dict) else region
        frame = self.grab_frame(region, "gray")
        match = self.find(frame, self.resource.ri_cheng_small_icon)
        if match is None:
            print("❌ 未找到日程小图标（ri_cheng_small）")
            return False
        x, y = get_abs_x_y_cv_windows(match["bbox"])
        windows_click(hwnd, x, y)
        return True

    def open_calendar_and_wait(self, region):
        """识别并点击日程小图标打开日历，等待界面响应（替代 Alt+Y 组合键）"""
        self.click_ri_cheng_small(region)
        human_delay(1)

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
            restore_window(hwnd)
            human_delay(0.1)

            region = make_region(hwnd)
            frame = self.grab_frame(region)
            match = self.find(frame, self.resource.qu_mo_small_icon)

            if match is None:
                print("当前不在驱魔状态,使用驱魔香")
                frame = self.wait_until(region, self.is_open_bag,
                                        action=lambda: hotkey('alt', 'e', hwnd=hwnd),
                                        action_first=True, want=True)
                match = self.find(frame, self.resource.qu_mo_icon)
                x, y = get_abs_x_y_cv_windows(match["bbox"])
                windows_right_click(hwnd, x, y)
                self.wait_until(region, self.is_open_bag,
                                action=lambda: hotkey('alt', 'e', hwnd=hwnd),
                                action_first=False, want=False)
                # 把消息级光标移到客户区右下角，离开背包区域
                fw, fh = self.roi[2], self.roi[3]
                windows_move_to(hwnd, fw - 1, fh - 1)
            else:
                print("当前已经在驱魔状态")
        except Exception:
            traceback.print_exc()
            human_delay(1)

    # 重置回合并确保自动战斗开启
    def reset_round(self, hwnd_index=0):
        try:
            return self._reset_round_hwnd(self.hwnd_list[hwnd_index])
        except Exception:
            traceback.print_exc()
            return False

    def _reset_round_hwnd(self, hwnd):
        """按 hwnd 重置回合（消息级点击「自动」按钮）。

        纯消息级、只读写自己 hwnd 的状态，线程安全，可多窗口并行调用。
        """
        region = make_region(hwnd)
        frame = self.grab_frame(region, "gray")
        match = self.find(frame, self.resource.zi_dong_icon)
        if match is None:
            return False
        self.click_match(match, region)
        frame = self.grab_frame(region, "gray")
        match = self.find(frame, self.resource.zi_dong_small_icon)
        if match is None:
            return False
        self.click_match(match, region)
        return True

    def open_bag(self, hwnd_index=0):
        try:
            return self._open_bag_hwnd(self.hwnd_list[hwnd_index])
        except Exception:
            traceback.print_exc()
            return False

    def _open_bag_hwnd(self, hwnd):
        """按 hwnd 点击 bag_small 打开背包，用 is_open_bag 确认是否成功。

        纯消息级、只读写自己 hwnd 的状态，线程安全，可多窗口并行调用。
        返回 True 表示背包已打开；定位失败 / 点击后未打开返回 False。
        """
        region = make_region(hwnd)

        for attempt in range(open_bag_retries):
            frame = self.grab_frame(region, "gray")
            match = self.find(frame, self.resource.bag_small_icon)
            if match is None:
                print("❌ 未找到 bag_small 图标")
                return False

            self.click_match(match, region)
            windows_move_to(hwnd, 200, 200)

            # 点击后确认：is_open_bag 命中即成功
            for _ in range(open_bag_check_rounds):
                frame = self.grab_frame(region, "gray")
                if self.is_open_bag(frame):
                    print("✅ 背包已打开")
                    return True
                human_delay(open_bag_check_gap)
            print(f"⚠️ 点击后背包未打开，重试（第 {attempt + 1}/{open_bag_retries} 次）")

        print("❌ 背包打开失败")
        return False

    def open_si_nan(self, hwnd_index=0):
        try:
            return self._open_si_nan_hwnd(self.hwnd_list[hwnd_index])
        except Exception:
            traceback.print_exc()
            return False

    def _find_si_nans(self, hwnd):
        """检测界面上所有司南图标，返回按匹配分数降序的 match 列表"""
        region = make_region(hwnd)
        frame = self.grab_frame(region, "gray")
        return self.find_all(frame, self.resource.si_nan_icon)

    def _open_si_nan_hwnd(self, hwnd, match=None):
        """按 hwnd 右键点击「司南」图标。

        match 不给时自动检测并取匹配分数最高的一个；给了则直接右键该目标
        （供 bao_tu 循环逐个点击已记录的司南坐标复用）。

        纯消息级、只读写自己 hwnd 的状态，线程安全，可多窗口并行调用。
        返回 True 表示已右键；自动检测模式下未找到目标返回 False。
        """
        if match is None:
            matches = self._find_si_nans(hwnd)
            if not matches:
                print("❌ 未找到司南图标")
                return False
            if len(matches) > 1:
                print(f"🔍 检测到 {len(matches)} 个司南图标，点击分数最高的一个")
            match = matches[0]

        # 右键点击：先消息级悬停到位再右键，点完把光标移开，防止悬停框遮挡
        x, y = get_abs_x_y_cv_windows(match["bbox"])
        windows_move_to(hwnd, x, y)
        windows_right_click(hwnd, x, y)
        windows_move_to(hwnd, 200, 200)

        print(f"✅ 已右键点击司南图标 ({x}, {y})")
        return True

    def _snap_si_nan(self, hwnd, target):
        """重新检测司南，返回距 target 最近的目标（match）；无目标返回 None。

        挖宝过程中界面可能滚动/移动导致旧坐标失效，每次右键前先吸附到当前位置。
        """
        matches = self._find_si_nans(hwnd)
        if not matches:
            return None
        return min(matches, key=lambda m: (m["bbox"][0] + m["bbox"][2] / 2 - target[0]) ** 2
                                         + (m["bbox"][1] + m["bbox"][3] / 2 - target[1]) ** 2)

    def _wa_bao_yolo(self, hwnd_index=0, stop_event=None):
        """_wa_bao_yolo_hwnd 的按窗口序号封装"""
        return self._wa_bao_yolo_hwnd(self.hwnd_list[hwnd_index], stop_event)

    def _wa_bao_yolo_hwnd(self, hwnd, stop_event=None):
        """挖宝(YOLO)：截图 -> YOLO 检测 -> 逐一消息级点击所有目标 -> 等 3 秒进下一轮。

        某轮未检测到任何目标时返回 None（调用方借此切到下一个司南），
        收到停止信号同样返回 None 结束。
        YOLO 按彩色帧训练，必须传 grab_frame(region, "bgr") 的 BGR 帧。
        """
        if self.yolo is None:
            print("❌ YOLO 模型未加载，挖宝任务无法执行")
            return None

        region = make_region(hwnd)

        round_no = 0
        while not is_stopped(stop_event):
            round_no += 1

            # 1. 截图并检测
            frame = self.grab_frame(region, "bgr")
            dets = self.yolo.detect(frame)

            # 2. 本轮无目标：返回 None，该司南挖宝结束
            if not dets:
                print(f"🔍 第 {round_no} 轮未检测到目标，该司南挖宝结束")
                return None

            # 3. 逐一记录并点击所有目标（bbox 为帧内坐标，click_match 转消息级点击）
            print(f"🔍 第 {round_no} 轮检测到 {len(dets)} 个目标")
            for i, (x1, y1, x2, y2, conf, cid) in enumerate(dets):
                bbox = (x1, y1, x2 - x1, y2 - y1)
                print(f"  🎯 目标 {i + 1}: bbox={bbox} conf={conf:.2f}")
                self.click_match({"bbox": bbox}, region, delay=0.2)

            # 4. 所有目标点完，等 3 秒再进行下一轮
            human_delay(wa_bao_round_gap)

        print("⏹ 收到停止信号，挖宝结束")
        return None

    # ---------- 业务流程 ----------

    def _run_for_all(self, stop_event, runner, task_name, finish_key):
        """run_all=True 的公共实现：所有窗口各起一个线程并行执行 runner

        并发安全说明：
        - 鼠标/键盘输入全部是消息级 PostMessage（按 hwnd 定向投递），各窗口
          互不抢占真实光标与键盘状态，可同时进行；
        - 每线程只写自己 hwnd 的 hwnd_status / window_fail_counts，无共享争用；
        - WGC 截图每次调用独立会话，按窗口各自捕获；
        - 停止：request_stop 置位的 terminate_event 会让各线程的 human_delay
          立即抛 TaskTerminated，线程自行退出；全部结束后检测到终止标记则
          重新抛出，保持「终止后不再执行后续任务」的原有语义。
        """
        if not self.hwnd_list:
            print(f"❌ 未找到游戏窗口，{task_name}任务无法执行")
            return

        threads = []
        for hwnd_index, hwnd in enumerate(self.hwnd_list):
            status = self.hwnd_status.get(hwnd)
            if status is not None and getattr(status, finish_key, False):
                print(f"⏭ hwnd={hwnd} 的{task_name}任务已完成，跳过")
                continue
            threads.append(threading.Thread(
                target=runner, args=(hwnd_index, stop_event, False),
                name=f"{task_name}-hwnd{hwnd}", daemon=True))
        if not threads:
            print(f"🏁 {task_name}任务所有窗口均已完成")
            return

        print(f"📋 {task_name}任务开始并行执行（共 {len(threads)} 个窗口）")
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 各窗口线程把「终止」吞在了自己体内（TaskTerminated 绕过 except
        # Exception 但终止于线程边界），这里重新抛出交给上层（GUI TaskWorker）
        if terminate_event.is_set():
            raise TaskTerminated("用户请求终止")
        print(f"🏁 {task_name}任务全部窗口处理完毕")

    def run_auto_reset_round(self,is_hide=False,stop_event=None):
        print("开始自动重置")
        while True:
            if is_stopped(stop_event):
                break
            for hwnd in self.hwnd_list:
                if is_stopped(stop_event):
                    break
                self.current_hwnd = hwnd
                restore_window(hwnd)
                hotkey('ctrl', 'a', hwnd=hwnd)
                if is_hide:
                    win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
                human_delay(5)

    def run_xun_you(self, hwnd_index=0, stop_event=None, run_all=False):
        """巡游任务（单窗口版，按 hwnd_index 定位目标窗口，与 run_xiu_ye 等一致）。

        :param hwnd_index: 目标窗口在 hwnd_list 中的下标，越界抛 IndexError
        :param run_all: True 时忽略 hwnd_index，按 hwnd_list 顺序逐窗口执行
        """
        if run_all:
            self._run_for_all(stop_event, self.run_xun_you, "巡游", "is_finish_xun_you")
            return
        if not 0 <= hwnd_index < len(self.hwnd_list):
            raise IndexError(
                f"hwnd_index={hwnd_index} 超出范围，当前游戏窗口数: {len(self.hwnd_list)}")
        hwnd = self.hwnd_list[hwnd_index]

        while True:
            if is_stopped(stop_event):
                break
            if self.hwnd_status[hwnd].is_finish_xun_you:
                print("巡游任务完成")
                break

            self.current_hwnd = hwnd
            try:
                region = make_region(hwnd)
                frame = self.grab_frame(region)

                # 战斗中：重置回合确保自动战斗，等一轮再查
                if self.is_in_fight(frame):
                    human_delay(10)
                    continue

                finish_match = self.find(frame, self.resource.xun_you_finish_icon)
                if finish_match is not None:
                    self.hwnd_status[hwnd].is_finish_xun_you = True
                    self.click_match(finish_match, region, delay=1)
                    human_delay(1)
                    continue

                match = self.find(frame, self.resource.xun_you_start_fight_icon)
                if match is None:
                    print("模式匹配结果为空")
                    human_delay(5)
                    continue

                self.click_match(match, region, delay=1)
                human_delay(2)
                self.reset_round(hwnd_index)

            except Exception:
                count = self.window_fail_counts.get(hwnd, 0) + 1
                self.window_fail_counts[hwnd] = count
                print(f"❌ 巡游任务出错 hwnd={hwnd}（第 {count} 次）")
                traceback.print_exc()
                if count >= MAX_WINDOW_FAILS:
                    print(f"⚠️ hwnd={hwnd} 连续失败 {count} 次，标记任务完成")
                    self.hwnd_status[hwnd].is_finish_xun_you = True
                human_delay(5)

    def run_fish(self,stop_event=None):
        win32gui.EnumWindows(self.get_hwnd, None)
        assert self.hwnd_list , "幻唐志窗口未找到"

        hwnd = self.hwnd_list[0]
        restore_window(hwnd)

        # 抛竿
        press_key('f1', hwnd=hwnd)
        human_delay(2)
        press_key('f1', hwnd=hwnd)
        human_delay(1)

        # 「有鱼」图标只加载一次，用项目统一的 cv2 模板匹配替代 pyautogui.locate
        you_yu_templ = cv2.imread(str(you_yu_path), cv2.IMREAD_GRAYSCALE)
        assert you_yu_templ is not None, f"钓鱼图标加载失败: {you_yu_path}"

        while True:
            if is_stopped(stop_event):
                break
            # WGC 抓全客户区再裁出浮漂区域，灰度化后做模板匹配
            frame = capture_client_only(hwnd)
            crop = frame[fish_height_start:fish_height_end,
                         fish_width_start:fish_width_end]
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

            match = find_best_match(gray, you_yu_templ, 0.7)
            if match is None:
                print("还未钓到鱼")
                human_delay(1)
                continue

            x, y, w, h = match["bbox"]
            # 裁剪区域坐标换算回客户区坐标
            client_x = fish_width_start + x + w // 2
            client_y = fish_height_start + y + h // 2
            windows_click(hwnd, client_x, client_y)
            human_delay(1)
            break

    def run_auto_task(self,task_name):
        win32gui.EnumWindows(self.get_hwnd, None)
        assert self.hwnd_list , "幻唐志窗口未找到"

        failed_hwnds = []
        for hwnd in self.hwnd_list:
            self.current_hwnd = hwnd
            try:
                human_delay(1)
                restore_window(hwnd)

                # 先看看能不能找到该任务
                human_delay(1)
                frame = capture_client_only(hwnd)
                ocr_result = self.ocr.get_ocr_from_image(frame, task_name)

                if not ocr_result:
                    print(f"❌ hwnd={hwnd} 上 OCR 找不到任务「{task_name}」")
                    failed_hwnds.append(hwnd)
                    continue

                print(f"✅ 检测到任务 {task_name}")
                best_bbox, best_text, best_conf = max(ocr_result, key=lambda x: x[2])
                bbox = np.array(best_bbox)
                center_x = int(np.mean(bbox[:, 0]))
                center_y = int(np.mean(bbox[:, 1]))
                windows_click(hwnd, center_x, center_y)
                human_delay(1)
            except Exception:
                print(f"❌ hwnd={hwnd} 执行 OCR 任务出错")
                traceback.print_exc()
                failed_hwnds.append(hwnd)
                human_delay(1)

        if failed_hwnds:
            print(f"⚠️ OCR 任务在 {len(failed_hwnds)} 个窗口上失败：{failed_hwnds}")

    # 修业任务
    def run_xiu_ye(self, hwnd_index=0, stop_event=None, run_all=False):
        """修业任务（单窗口版，按 hwnd_index 定位目标窗口，与 bao_ta 风格一致）。

        GUI 的 TaskWorker 本就逐窗口执行（set_selected_hwnds 后 hwnd_list
        只含目标窗口，index=0 即命中）；命令行直接指定窗口下标。

        :param hwnd_index: 目标窗口在 hwnd_list 中的下标，越界抛 IndexError
        :param run_all: True 时忽略 hwnd_index，按 hwnd_list 顺序逐窗口执行
        """
        if run_all:
            self._run_for_all(stop_event, self.run_xiu_ye, "修业", "is_finish_xiu_ye")
            return
        if not 0 <= hwnd_index < len(self.hwnd_list):
            raise IndexError(
                f"hwnd_index={hwnd_index} 超出范围，当前游戏窗口数: {len(self.hwnd_list)}")
        hwnd = self.hwnd_list[hwnd_index]

        while True:
            if is_stopped(stop_event):
                break
            if self.hwnd_status[hwnd].is_finish_xiu_ye:
                print("修业任务完成")
                break

            self.current_hwnd = hwnd
            try:
                # restore_window(hwnd)
                human_delay(0.1)

                # 检查页面是否有修业任务
                region = make_region(hwnd)
                frame = self.grab_frame(region)
                match_result = self.find_xiu_ye_task(frame)

                if match_result is None:
                    # 打开日历

                    self.wait_until(region, self.is_open_ri_cheng, lead=1,
                                    action=lambda: self.open_calendar_and_wait(region))

                    frame = self.grab_frame(region, "bgr")
                    match = self.find(frame, self.resource.xiu_ye_finish_icon)
                    if match is not None:
                        self.hwnd_status[hwnd].is_finish_xiu_ye = True
                        print(" 当日修业任务已完成")
                        self.wait_until(region, self.is_open_ri_cheng, want=False, lead=1,
                                        action=lambda: windows_key(hwnd, 'esc'))
                        continue
                    else:
                        # to-do
                        print("请在任务栏勾选修业任务")
                        self.hwnd_status[hwnd].is_finish_xiu_ye = True
                        human_delay(0.2)
                        continue

                frame = self.wait_until(region, self.is_open_f9,
                                        action=lambda: windows_key(hwnd, 'f9'))
                task_type = self.get_xiu_ye_task_type(frame)

                if task_type is None:
                    print("❌ 修业任务类型错误")
                    continue

                print(f"✅ 检测到修业任务 {task_type}")
                # 任务点直接用客户区坐标（消息级点击不需要换算屏幕绝对坐标）
                xiu_ye_x, xiu_ye_y = get_abs_x_y_cv_windows(match_result["bbox"])
                human_delay(0.2)

                # 物资
                if task_type == XiuYeTaskType.WU_ZI:
                    print("开始修业物资任务")
                    windows_click(hwnd, xiu_ye_x, xiu_ye_y)
                    human_delay(1)

                    item_buy_button_match = self.wait_shop_buy_button(
                        region, self.is_open_item_shop,
                        self.resource.item_shop_buy_button_icon, gap=0.5)

                    while True:
                        self.click_match(item_buy_button_match, region)
                        human_delay(1)
                        frame = self.grab_frame(region)

                        # 如果弹出价格确认
                        item_que_ren_match = self.find(frame, self.resource.item_xu_que_ren_icon)
                        if item_que_ren_match is not None:
                            self.click_match(item_que_ren_match, region, delay=0.1)
                            human_delay(1)
                            frame = self.grab_frame(region)

                        if not self.is_open_item_shop(frame):
                            print("修业任务购买物品成功")
                            human_delay(0.1)
                            break

                    # 确保开始自动寻路
                    def click_task():
                        windows_click(hwnd, xiu_ye_x, xiu_ye_y)
                        human_delay(0.1)

                    self.wait_until(region, self.is_has_xun_lu, want=False,action=click_task, action_first=True)

                    while True:
                        frame = self.grab_frame(region, "raw")
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                        if self.give_item(frame):
                            print("给予物品")
                            item_location = generate_grid_mask(frame,self.radio)
                            for item in item_location:
                                center = item["center"]
                                windows_click(hwnd, center[0], center[1])
                                human_delay(0.1)
                            item_que_ding_match = self.find(frame,self.resource.xiu_ye_item_que_ding_icon)
                            self.click_match(item_que_ding_match, region, delay=0.1)
                        else:
                            break
                    print("给予物品成功")
                    # 确保关闭了对话
                    self.wait_until(region, self.is_has_talk, lead=1,want=False,
                                                        action=lambda: self.close_talk(region))
                # 宠物
                elif task_type == XiuYeTaskType.CHONG_WU:
                    print("开始修业宠物任务")
                    windows_click(hwnd, xiu_ye_x, xiu_ye_y)
                    human_delay(1)

                    # 检测是否打开了宠物购买页面
                    pet_buy_button_match = self.wait_shop_buy_button(
                        region, self.is_open_pet_shop,
                        self.resource.pet_shop_button_icon, gap=1)
                    print("✅ 检测到宠物页面")

                    def click_buy():
                        self.click_match(pet_buy_button_match, region)
                        human_delay(1)

                    self.wait_until(region, self.is_open_pet_shop, want=False,
                                    action=click_buy, action_first=True)
                    print("宠物购买成功")
                    # 确保开始自动寻路
                    self.wait_until(region, self.is_has_xun_lu, want=False, lead=0.1,
                                    action=lambda: windows_click(hwnd, xiu_ye_x, xiu_ye_y))

                    # 确保关闭了对话
                    self.wait_until(region, self.is_has_talk, lead=1,want=False,
                                        action=lambda: self.close_talk(region))
                # 战斗
                elif task_type in (XiuYeTaskType.TIAO_ZHAN, XiuYeTaskType.TIAO_ZHAN_SHOU_XI,XiuYeTaskType.TONG_MEN):
                    print("开始修业战斗任务")

                    # 确保进入战斗中
                    def click_task_and_wait():
                        human_delay(1)
                        windows_click(hwnd, xiu_ye_x, xiu_ye_y)
                        human_delay(3)

                    self.wait_until(region, self.is_in_fight,action=click_task_and_wait, action_first=True)
                    self.wait_until(region, self.is_has_talk, lead=1,want=False,
                                        action=lambda: self.close_talk(region))                    
                    self.reset_round(hwnd_index)

                    self.wait_until(region, self.is_in_fight, want=False, lead=0.1)
                    human_delay(0.2)

                    self.wait_until(region, self.is_has_talk, lead=1,want=False,
                                        action=lambda: self.close_talk(region))
                elif task_type == XiuYeTaskType.LIE_HEN:
                    print("开始修业裂痕任务")

                    def click_task_and_wait():
                        human_delay(1)
                        windows_click(hwnd, xiu_ye_x, xiu_ye_y)
                        human_delay(3)

                    # 第一次封印,封印结束出现对话框
                    self.wait_until(region, self.is_in_fight,action=click_task_and_wait, action_first=True)
                    self.wait_until(region, self.is_has_talk, lead=1,want=False,
                                    action=lambda: self.close_talk(region))
                    
                    self.reset_round(hwnd_index)

                    self.wait_until(region, self.is_in_fight, want=False, lead=2)
                    human_delay(0.2)

                    self.wait_until(region, self.is_has_talk, lead=1,want=False,
                                        action=lambda: self.close_talk(region))
                else:
                    print("❌ 未知任务类型")
            except Exception:
                count = self.window_fail_counts.get(hwnd, 0) + 1
                self.window_fail_counts[hwnd] = count
                print(f"❌ 修业任务出错 hwnd={hwnd}（第 {count} 次）")
                traceback.print_exc()
                if count >= MAX_WINDOW_FAILS:
                    print(f"⚠️ hwnd={hwnd} 连续失败 {count} 次，标记任务完成")
                    self.hwnd_status[hwnd].is_finish_xiu_ye = True
                human_delay(1)
                continue

    def run_xiu_lian(self, hwnd_index=0, stop_event=None, run_all=False):
        """修炼任务（单窗口版，按 hwnd_index 定位目标窗口，与 run_xiu_ye/bao_ta 一致）。

        :param hwnd_index: 目标窗口在 hwnd_list 中的下标，越界抛 IndexError
        :param run_all: True 时忽略 hwnd_index，按 hwnd_list 顺序逐窗口执行
        """
        if run_all:
            self._run_for_all(stop_event, self.run_xiu_lian, "修炼", "is_finish_xiu_lian")
            return
        if not 0 <= hwnd_index < len(self.hwnd_list):
            raise IndexError(
                f"hwnd_index={hwnd_index} 超出范围，当前游戏窗口数: {len(self.hwnd_list)}")
        hwnd = self.hwnd_list[hwnd_index]

        while True:
            if is_stopped(stop_event):
                break
            if self.hwnd_status[hwnd].is_finish_xiu_lian:
                print("修炼任务完成")
                break

            self.current_hwnd = hwnd
            try:
                human_delay(0.1)

                region = make_region(hwnd)
                # frame = self.wait_until(region, self.is_open_f9,action=lambda: windows_key(hwnd, 'f9'))
                frame = self.grab_frame(region)
                # 判断有没有修炼任务,如果没有,就认为没开始接任务,就从日历开始寻路
                if not self.has_xiu_lian_task(frame):
                    windows_move_to(hwnd, 100, 200)
                    # 打开日历
                    self.wait_until(region, self.is_open_ri_cheng, lead=0.2,
                                    action=lambda: self.open_calendar_and_wait(region))

                    frame = self.grab_frame(region, "bgr")
                    match = self.find(frame, self.resource.xiu_lian_finish_icon)
                    if match is not None:
                        self.hwnd_status[hwnd].is_finish_xiu_lian = True
                        print(" 当日修炼任务已完成")
                        continue

                    frame = self.grab_frame(region)
                    match = self.find(frame, self.resource.xiu_lian_no_finish_icon)
                    self.click_match(match, region)
                    windows_key(hwnd, 'esc')
                    human_delay(0.1)

                    frame = self.wait_until(region, self.is_open_xiu_lian_talk, gap=0.1)
                    match = self.find(frame, self.resource.xiu_lian_talk_icon)
                    self.click_match(match, region)
                    human_delay(0.5)
                    windows_key(hwnd, 'esc')

                human_delay(1)
                frame = self.grab_frame(region)
                match_result = self.find_xiu_lian_task(frame)
                # 这个是修炼任务完成后,定位修炼任务的坐标,然后再点击,因为直接用xiu_lian_task_x的话,未完成和完成之后的任务栏的尺寸不一样
                xiu_lian_x, xiu_lian_y = get_abs_x_y_cv_windows(match_result["bbox"])

                frame = self.grab_frame(region)
                task_type = self.get_xiu_lian_task_type(frame)

                if task_type == XiuLianTaskType.XUN_WU:
                    print("开始修练寻物任务")

                    frame = self.grab_frame(region)
                    match_result = self.find_jiao_yi_zhong_xin(frame)
                    jiao_yi_zhong_xin_x, jiao_yi_zhong_xin_y = get_abs_x_y_cv_windows(match_result["bbox"])

                    windows_click(hwnd, jiao_yi_zhong_xin_x, jiao_yi_zhong_xin_y)
                    human_delay(2)

                    item_buy_button_match = self.wait_shop_buy_button(
                        region, self.is_open_item_shop,
                        self.resource.item_shop_buy_button_icon, gap=0.5)

                    # 确保购买成功
                    while True:
                        self.click_match(item_buy_button_match, region)
                        human_delay(1)
                        frame = self.grab_frame(region)

                        # 如果弹出价格确认
                        item_que_ren_match = self.find(frame, self.resource.item_xu_que_ren_icon)
                        if item_que_ren_match is not None:
                            self.click_match(item_que_ren_match, region, delay=0.1)
                            human_delay(1)
                            frame = self.grab_frame(region)

                        if not self.is_open_item_shop(frame):
                            print("修炼任务购买物品成功")
                            human_delay(2)
                            break

                    while True:
                        frame = self.grab_frame(region, "raw")
                        frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        windows_click(hwnd, xiu_lian_x, xiu_lian_y)

                        if self.give_item(frame):
                            print("给予物品")
                            item_location = generate_grid_mask(frame,self.radio)
                            for item in item_location:
                                center = item["center"]
                                windows_click(hwnd, center[0], center[1])
                                human_delay(0.1)
                            item_que_ding_match = self.find(frame,self.resource.xiu_ye_item_que_ding_icon)
                            self.click_match(item_que_ding_match, region, delay=0.1)
                            break
                        elif self.is_has_talk(frame_gray):
                            human_delay(2)
                            break
                        else:
                            human_delay(2)

                    print("修炼任务给予物品成功")

                    # 确保关闭了对话
                    self.wait_until(region, self.is_has_talk, lead=1,want=False,
                                        action=lambda: self.close_talk(region))                    
                    continue

                frame = self.grab_frame(region, "raw")
                color_result = get_color(frame,'blue',self.radio)

                if not color_result:
                    print("❌ 未找到蓝色图标")
                    return
                xiu_lian_task_x, xiu_lian_task_y = get_abs_x_y_cv_windows(color_result)

                # 找人
                if task_type == XiuLianTaskType.ZHAO_REN:
                    print("开始修练找人任务")
                    windows_click(hwnd, xiu_lian_task_x, xiu_lian_task_y)
                    human_delay(2)

                    # 确保开始自动寻路
                    self.wait_until(region, self.is_has_xun_lu, want=False, lead=0.1)

                    # 确保关闭了对话
                    self.wait_until(region, self.is_has_talk, lead=1,want=False,
                                        action=lambda: self.close_talk(region))                    
                    print("✅ 修炼任务关闭对话框成功")

                # 找疯道人
                if task_type == XiuLianTaskType.FENG_DAO_REN:
                    print("开始修练疯道人任务")
                    def click_task_and_wait():
                        windows_click(hwnd, xiu_lian_task_x, xiu_lian_task_y)
                        human_delay(2)

                    # 确保开始自动寻路
                    self.wait_until(region, self.is_in_fight,action=click_task_and_wait, action_first=True)
                    print("开始进入修炼战斗")
                    self.reset_round(hwnd_index)

                    self.wait_until(region, self.is_in_fight, want=False, lead=2)
                    print("修炼任务结束战斗")

                    self.wait_until(region, self.is_has_talk, lead=1,want=False,
                                        action=lambda: self.close_talk(region))                    
                    print("修炼任务关闭对话框成功")
                    self.hwnd_status[hwnd].is_finish_xiu_lian = True

            except Exception:
                count = self.window_fail_counts.get(hwnd, 0) + 1
                self.window_fail_counts[hwnd] = count
                print(f"❌ 修炼任务出错 hwnd={hwnd}（第 {count} 次）")
                traceback.print_exc()
                if count >= MAX_WINDOW_FAILS:
                    print(f"⚠️ hwnd={hwnd} 连续失败 {count} 次，标记任务完成")
                    self.hwnd_status[hwnd].is_finish_xiu_lian = True
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
        human_delay(1)

        last_result = None
        while True:
            if is_stopped(stop_event):
                break
            # get_color 内部走 BGR2RGB，必须喂原始 raw 帧
            raw = self.grab_frame(hwnd, "raw")
            display = raw  # raw 就是 BGR，可直接画框

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

    # 挖宝图：开背包 -> 记录所有司南 -> 逐个右键 -> YOLO 挖宝
    def bao_tu(self, hwnd_index=0, stop_event=None):
        try:
            return self._bao_tu_hwnd(self.hwnd_list[hwnd_index], stop_event)
        except Exception:
            traceback.print_exc()
            return False

    def _bao_tu_hwnd(self, hwnd, stop_event=None):
        """完整挖宝流程（按 hwnd，消息级，可多窗口并行）。

        1. 打开背包；2. 记录所有司南中心坐标；3. 逐个右键司南并挖宝。
        每个司南挖到 YOLO 无目标（_wa_bao_yolo_hwnd 返回 None）后换下一个，
        直至所有司南坐标均被点击过。
        """
        if not self._open_bag_hwnd(hwnd):
            print("❌ 背包未打开，挖宝流程终止")
            return False

        matches = self._find_si_nans(hwnd)
        if not matches:
            print("❌ 未找到司南图标，挖宝流程终止")
            return False

        # 记录所有司南中心坐标（客户区坐标），逐个处理
        targets = [get_abs_x_y_cv_windows(m["bbox"]) for m in matches]
        print(f"✅ 共记录 {len(targets)} 个司南目标")

        for i, target in enumerate(targets):
            if is_stopped(stop_event):
                break

            match = self._snap_si_nan(hwnd, target)
            if match is None:
                print(f"⚠️ 第 {i + 1}/{len(targets)} 个司南重检测失败，跳过")
                continue

            print(f"🧭 处理第 {i + 1}/{len(targets)} 个司南")
            self._open_si_nan_hwnd(hwnd, match)
            human_delay(1)

            # 挖到 YOLO 无目标（返回 None）后继续下一个司南
            if self._wa_bao_yolo_hwnd(hwnd, stop_event) is None:
                # 进一步确认是否已回到背包界面；未回到说明 yolo 检测未完全收尾
                if not self.is_open_bag(self.grab_frame(hwnd, "gray")):
                    print("⚠️ yolo检测不完全，请手动点击")

        print("🏁 所有司南均已处理，挖宝流程结束")
        return True

    # 玲珑宝塔
    def _detect_bao_ta(self, hwnd, stop_event=None, timeout=None):
        if timeout is None:
            timeout = bao_ta_timeout

        prev_gray = None
        last_check = time.monotonic()

        while not is_stopped(stop_event):
            if time.monotonic() - last_check < bao_ta_diff_interval:
                human_delay(0.05)
                continue

            frame = self.grab_frame(hwnd)

            gray = cv2.GaussianBlur(frame, (5, 5), 0)

            if prev_gray is None:
                prev_gray = gray
                last_check = time.monotonic()
                continue

            diff = cv2.absdiff(prev_gray, gray)

            # 中央台面 ROI 掩膜：屏蔽顶部状态栏与底部聊天栏
            roi_mask, _ = make_bao_ta_mask(diff.shape[:2])
            diff = cv2.bitwise_and(diff, diff, mask=roi_mask)

            # 阈值二值化与形态学膨胀
            _, thresh = cv2.threshold(diff, bao_ta_diff_thresh, 255, cv2.THRESH_BINARY)
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

    def bao_ta(self,hwnd_index=0,count=10, stop_event=None,):
        if not 0 <= hwnd_index < len(self.hwnd_list):
            raise IndexError(
                f"hwnd_index={hwnd_index} 超出范围，当前游戏窗口数: {len(self.hwnd_list)}")
        hwnd = self.hwnd_list[hwnd_index]
        restore_window(hwnd)
        _count = 0

        while _count < count and not is_stopped(stop_event):
            # 如果此层已经通关,一直点击
            while not is_stopped(stop_event):
                frame = self.grab_frame(hwnd)
                human_delay(0.1)
                if self.find(frame,self.resource.bao_ta_tong_guan_icon,0.9):
                    match = self.find(frame,self.resource.bao_ta_an_niu_icon)
                    abs_x, abs_y = get_abs_x_y_cv_windows(match["bbox"])
                    windows_click(hwnd,abs_x,abs_y)
                    human_delay(0.5)
                else:
                    break

            # 如果一直没有开始挑战按钮,则一直等待
            while not is_stopped(stop_event):
                # 检测宝塔战斗目标,等待一会,不然每次战斗完会有弹窗
                human_delay(3)
                bbox = self._detect_bao_ta(hwnd, stop_event)
                if bbox is None:
                    print("❌ 动态目标检测超时，未找到动态目标")
                    return None
                
                print("✅ 检测到动态目标")
                human_delay(0.1)
                abs_x, abs_y = get_abs_x_y_cv_windows(bbox)
                windows_click(hwnd,abs_x,abs_y)
                human_delay(3)

                frame = self.grab_frame(hwnd)

                item_que_ding_match = self.find(frame,self.resource.bao_ta_kai_shi_tiao_zhan_icon)
                if item_que_ding_match:
                    abs_x, abs_y = get_abs_x_y_cv_windows(item_que_ding_match["bbox"])
                    windows_click(hwnd,abs_x,abs_y)
                    human_delay(2)                    
                    break
                
                # 这一步是移动光标，防止被卡住,因为可能会去点击宝箱奖励按钮
                windows_move_to(hwnd,abs_x,abs_y)
            self.wait_until(hwnd,self.is_in_fight,want=True)
            print("宝塔战斗开始")
            human_delay(2)
            self.reset_round(hwnd_index)
            self.wait_until(hwnd,self.is_in_fight,want=False)
            print("战斗结束")
            _count += 1

        if is_stopped(stop_event):
            print(f"⏹ 宝塔任务已停止（完成 {_count}/{count} 层）")
        else:
            print(f"✅ 宝塔任务完成（{_count} 层）")

    # 测试
    # 诊断用：检测 resource 中所有图标是否出现在当前游戏窗口
    def icon_names(self):
        """全部图标属性名（诊断面板下拉框用）"""
        return sorted(name for name in vars(self.resource) if name.endswith("_icon"))

    def test_resources(self, hwnd_index=0, stop_event=None, threshold=None, icon_names=None):
        """测试 resource 中的图标能否在当前游戏窗口检测到。

        实时截图，命中的图标用绿框 + 匹配分数标注在预览窗口，
        控制台在结果变化时打印「检测到 / 未检测到」清单，按 q 退出。

        icon_names: 只看这几个图标（GameResource 的属性名），不给则用默认图标
        threshold : 临时匹配阈值，不给则用模块级 THRESHOLD
        """
        hwnd = self.hwnd_list[hwnd_index]
        human_delay(1)

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
            gray = self.grab_frame(hwnd, "gray")
            bgr = self.grab_frame(hwnd, "bgr")
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