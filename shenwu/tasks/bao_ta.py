"""玲珑宝塔任务：帧间差分找动态目标 → 点击 → 检测进入战斗 → 重置回合。

职责边界：只描述单窗口的层循环与识别参数；抓屏、模板匹配、回合重置
由 GameController 提供（self.grab_frame / find / wait_until / reset_round）。
"""

import time

import cv2
import numpy as np

from shenwu.game_window import restore_window
from shenwu.timing import human_delay, is_stopped
from shenwu.utils import get_abs_x_y_cv_windows
from shenwu.win_input import windows_click, windows_move_to

# 宝塔检测（帧间差分找动态目标）参数，来自 legacy/test_only copy.py
bao_ta_diff_interval = 0.12  # 差分时间窗（秒），0.10 ~ 0.15 秒动态最明显
bao_ta_min_area = 100        # 最小运动轮廓面积（过滤噪点）
bao_ta_max_area = 12000      # 最大运动轮廓面积（过滤大面积刷新）
bao_ta_timeout = 30.0        # 检测超时（秒），超时未找到返回 None
bao_ta_diff_thresh = 25      # 帧间差分二值化阈值（0-255）

# 中央台面 ROI 掩膜比例：屏蔽顶部状态栏与底部聊天栏，只检测台面区域。
# 调参时可直接用 make_bao_ta_mask(shape, ...) 叠加预览验证。
bao_ta_mask_top = 0.08       # 上边界（高度比例）
bao_ta_mask_bottom = 0.75    # 下边界
bao_ta_mask_left = 0.10      # 左边界（宽度比例）
bao_ta_mask_right = 0.90     # 右边界


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


class BaoTaTasks:
    """宝塔流程（依赖 GameController 的公共能力，需由 GameController 继承使用）"""

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

    def bao_ta(self, hwnd_index=0, count=10, stop_event=None,):
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
                if self.find(frame, self.resource.bao_ta_tong_guan_icon, 0.9):
                    match = self.find(frame, self.resource.bao_ta_an_niu_icon)
                    abs_x, abs_y = get_abs_x_y_cv_windows(match["bbox"])
                    windows_click(hwnd, abs_x, abs_y)
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
                windows_click(hwnd, abs_x, abs_y)
                human_delay(3)

                frame = self.grab_frame(hwnd)

                item_que_ding_match = self.find(frame, self.resource.bao_ta_kai_shi_tiao_zhan_icon)
                if item_que_ding_match:
                    abs_x, abs_y = get_abs_x_y_cv_windows(item_que_ding_match["bbox"])
                    windows_click(hwnd, abs_x, abs_y)
                    human_delay(2)
                    break

                # 这一步是移动光标，防止被卡住,因为可能会去点击宝箱奖励按钮
                windows_move_to(hwnd, abs_x, abs_y)
            self.wait_until(hwnd, self.is_in_fight, want=True)
            print("宝塔战斗开始")
            human_delay(2)
            self.reset_round(hwnd_index)
            self.wait_until(hwnd, self.is_in_fight, want=False)
            print("战斗结束")
            _count += 1

        if is_stopped(stop_event):
            print(f"⏹ 宝塔任务已停止（完成 {_count}/{count} 层）")
        else:
            print(f"✅ 宝塔任务完成（{_count} 层）")
