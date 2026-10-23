import ctypes
import time

import cv2
import mss
import numpy as np
import win32gui

# ---------------------------------------------------------------------------
# DPI：设置 PER_MONITOR_AWARE(2)，保证 GetClientRect / ClientToScreen 返回
# 物理像素，与 mss 抓屏坐标一致
# ---------------------------------------------------------------------------
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# 排除桌面/任务栏等系统壳窗口，以及标题带 RENDER 的渲染窗口
_SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}


def find_game_hwnd():
    """枚举可见顶层窗口，返回标题含「幻唐志」的游戏窗口 hwnd；找不到返回 None。"""
    matches = []

    def _on_window(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).strip()
        if not title or "RENDER" in title.upper():
            return
        if win32gui.GetClassName(hwnd) in _SHELL_CLASSES:
            return
        if "幻唐志" in title:
            matches.append((hwnd, title))

    win32gui.EnumWindows(_on_window, None)
    if not matches:
        return None
    if len(matches) > 1:
        print(f"⚠️ 找到 {len(matches)} 个幻唐志窗口，使用第一个：")
        for h, t in matches:
            print(f"    hwnd={h} 「{t}」")
    hwnd, title = matches[0]
    try:
        print(f"✅ 目标窗口：hwnd={hwnd} 「{title}」")
    except UnicodeEncodeError:  # GBK 控制台打不出 emoji 时降级输出
        print(f"target window: hwnd={hwnd} {title}")
    return hwnd


def get_window_region(hwnd):
    """按窗口客户区当前矩形生成 mss 截图区域；窗口不可用/最小化返回 None。"""
    if not win32gui.IsWindow(hwnd) or win32gui.IsIconic(hwnd):
        return None
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    if right <= 0 or bottom <= 0:
        return None
    left, top = win32gui.ClientToScreen(hwnd, (left, top))
    return {"left": left, "top": top, "width": right, "height": bottom}


def run_realtime_sword_detector():
    """
    实时动态剑检测与可视化（只抓取幻唐志窗口客户区）。

    每帧重新计算窗口客户区矩形，窗口拖动/缩放自动跟随；
    窗口最小化或关闭时显示等待画面，不崩溃。
    """
    hwnd = find_game_hwnd()
    if hwnd is None:
        print("❌ 未找到幻唐志窗口，请先打开游戏")
        return

    sct = mss.mss()

    # 参数设置
    DIFF_INTERVAL = 0.12     # 差分对比时间窗（秒）：0.10 ~ 0.15 秒动态最明显
    MIN_AREA = 100           # 最小运动轮廓面积（过滤噪点）
    MAX_AREA = 12000         # 最大运动轮廓面积（过滤大面积刷新）

    # 状态缓存
    prev_gray = None
    last_check_time = time.time()

    # 记录当前锁定的目标框 (x, y, w, h)，实现平滑显示
    locked_box = None
    fps = 0.0
    frame_count = 0
    fps_start_time = time.time()

    print("--- 实时检测已启动，在显示窗口按 'q' 键退出 ---")

    while True:
        loop_start = time.time()

        # 1. 抓取幻唐志窗口客户区（窗口关闭则退出）
        if not win32gui.IsWindow(hwnd):
            print("❌ 幻唐志窗口已关闭，退出")
            break
        monitor = get_window_region(hwnd)
        if monitor is None:
            # 窗口最小化 / 客户区为 0：等待其恢复
            time.sleep(0.2)
            prev_gray = None
            continue
        sct_img = sct.grab(monitor)
        frame = np.array(sct_img)[:, :, :3]  # 去除 Alpha 通道，保留 BGR
        h, w = frame.shape[:2]

        # 2. 预处理
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        # 初始化上一帧
        if prev_gray is None:
            prev_gray = gray
            continue

        # 3. 按时间间隔执行动态差分判断
        current_time = time.time()
        time_elapsed = current_time - last_check_time

        mask_debug_view = np.zeros((h, w), dtype=np.uint8)

        if time_elapsed >= DIFF_INTERVAL:
            # 计算绝对差分
            diff = cv2.absdiff(prev_gray, gray)

            # 中央台面 ROI 掩膜：屏蔽顶部状态栏与底部聊天栏
            roi_mask = np.zeros((h, w), dtype=np.uint8)
            roi_mask[int(h * 0.15):int(h * 0.85), int(w * 0.20):int(w * 0.80)] = 255
            masked_diff = cv2.bitwise_and(diff, diff, mask=roi_mask)

            # 阈值二值化与形态学膨胀
            _, thresh = cv2.threshold(masked_diff, 25, 255, cv2.THRESH_BINARY)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
            dilated = cv2.dilate(thresh, kernel, iterations=2)
            mask_debug_view = dilated

            # 寻找运动轮廓
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            candidates = []
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if MIN_AREA < area < MAX_AREA:
                    x, y, bw, bh = cv2.boundingRect(cnt)
                    # 宽高比接近正方形方块
                    if 0.5 < float(bw) / bh < 2.0:
                        candidates.append((area, (x, y, bw, bh)))

            if candidates:
                # 取动态面积最大的连通块作为目标
                candidates.sort(key=lambda item: item[0], reverse=True)
                locked_box = candidates[0][1]
            else:
                locked_box = None

            # 推进帧对比基准
            prev_gray = gray
            last_check_time = current_time

        # 4. 可视化绘制（实时渲染）
        vis_frame = frame.copy()

        # 绘制检测框与十字瞄准线
        if locked_box is not None:
            bx, by, bw, bh = locked_box
            cx, cy = bx + bw // 2, by + bh // 2

            # 绘制绿色方框
            cv2.rectangle(vis_frame, (bx, by), (bx + bw, by + bh), (0, 255, 0), 2)
            # 绘制中心十字星
            cv2.drawMarker(vis_frame, (cx, cy), (0, 0, 255), markerType=cv2.MARKER_CROSS, markerSize=16, thickness=2)
            # 标注坐标文本
            coord_text = f"Sword: ({cx}, {cy})"
            cv2.putText(vis_frame, coord_text, (bx, max(20, by - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        # 计算并绘制 FPS
        frame_count += 1
        if time.time() - fps_start_time >= 0.5:
            fps = frame_count / (time.time() - fps_start_time)
            frame_count = 0
            fps_start_time = time.time()

        cv2.putText(vis_frame, f"FPS: {fps:.1f}", (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        # 5. 画中画（PiP）：在右上角缩放展示当前的差分二值图，方便调参
        pip_w, pip_h = int(w * 0.22), int(h * 0.22)
        small_mask = cv2.resize(mask_debug_view, (pip_w, pip_h))
        small_mask_bgr = cv2.cvtColor(small_mask, cv2.COLOR_GRAY2BGR)
        # 贴到右上角
        vis_frame[10:10 + pip_h, w - pip_w - 10:w - 10] = small_mask_bgr
        cv2.rectangle(vis_frame, (w - pip_w - 10, 10), (w - 10, 10 + pip_h), (255, 255, 255), 1)

        # 6. 显示窗口
        cv2.imshow("Dynamic Sword Detector (Press 'q' to exit)", vis_frame)

        # 7. 退出判定（按 q 键）
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cv2.destroyAllWindows()

if __name__ == "__main__":
    run_realtime_sword_detector()
