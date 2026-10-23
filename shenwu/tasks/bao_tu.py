"""挖宝图（司南）任务：开背包 → 记录所有司南 → 逐个右键 → YOLO 挖宝。

职责边界：只描述单窗口的业务顺序；抓屏、模板匹配、点击、开背包等能力
由 GameController 提供（self.grab_frame / find_all / click_match / _open_bag_hwnd）。
"""

import traceback

from shenwu.game_window import make_region
from shenwu.timing import human_delay, is_stopped
from shenwu.utils import get_abs_x_y_cv_windows
from shenwu.win_input import windows_move_to, windows_right_click

# 挖宝 YOLO 检测参数
wa_bao_round_gap = 3.0     # 每轮所有目标点完后的等待秒数，再进下一轮检测


class BaoTuTasks:
    """挖宝图流程（依赖 GameController 的公共能力，需由 GameController 继承使用）"""

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

    def _snap_si_nan(self, hwnd, target, used=None, tolerance=30):
        """重新检测司南，返回距 target 最近且未被点击过的目标（match）；无目标返回 None。

        挖宝过程中界面可能滚动/移动导致旧坐标失效，每次右键前先吸附到当前位置。
        used: 本次流程已点击过的中心坐标列表；与其距离在 tolerance 像素内的候选
        会被排除，避免界面位移后把已处理的目标再次吸附回来（重复挖宝）。
        """
        matches = self._find_si_nans(hwnd)
        if not matches:
            return None

        candidates = [(get_abs_x_y_cv_windows(m["bbox"]), m) for m in matches]
        if used:
            candidates = [((cx, cy), m) for (cx, cy), m in candidates
                          if all((cx - ux) ** 2 + (cy - uy) ** 2 > tolerance ** 2
                                 for ux, uy in used)]
        if not candidates:
            return None
        return min(candidates, key=lambda item: (item[0][0] - target[0]) ** 2
                                               + (item[0][1] - target[1]) ** 2)[1]

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
                self.click_match({"bbox": bbox}, region, delay=0.2)

            # 4. 所有目标点完，等 3 秒再进行下一轮
            human_delay(wa_bao_round_gap)

        print("⏹ 收到停止信号，挖宝结束")
        return None

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

        used = []  # 已点击过的司南中心坐标，吸附时排除，避免重复处理
        for i, target in enumerate(targets):
            if is_stopped(stop_event):
                break

            match = self._snap_si_nan(hwnd, target, used)
            if match is None:
                print(f"⚠️ 第 {i + 1}/{len(targets)} 个司南重检测失败或已处理，跳过")
                continue

            print(f"🧭 处理第 {i + 1}/{len(targets)} 个司南")
            self._open_si_nan_hwnd(hwnd, match)
            used.append(get_abs_x_y_cv_windows(match["bbox"]))
            human_delay(1)

            # 挖到 YOLO 无目标（返回 None）后继续下一个司南
            if self._wa_bao_yolo_hwnd(hwnd, stop_event) is None:
                # 进一步确认是否已回到背包界面；未回到说明 yolo 检测未完全收尾
                if not self.is_open_bag(self.grab_frame(hwnd, "gray")):
                    print("⚠️ yolo检测不完全，请手动点击")

        print("🏁 所有司南均已处理，挖宝流程结束")
        return True
