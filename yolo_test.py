# Ultralytics 🚀 AGPL-3.0 License - https://ultralytics.com/license
"""桌面窗口实时目标检测预览（YOLOv8 ONNX end2end 版）。

检测逻辑在 shenwu/yolo_detector.py 的 YoloDetector 类里；本文件只负责
「选窗口 -> 截帧 -> 调检测 -> 画框预览」，不含模型推理实现。

用法示例：
    uv run python yolo_test.py --list                 # 列出所有可选窗口
    uv run python yolo_test.py                        # 交互式选择窗口
    uv run python yolo_test.py --title 幻唐志          # 按标题（子串，取第一个匹配）
    uv run python yolo_test.py --hwnd 132540          # 按 hwnd 精确指定
    uv run python yolo_test.py --title 幻唐志 --every 2 --conf-thres 0.4

预览窗口内按 q 或 ESC 退出。
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import time

import cv2
import mss
import numpy as np
import win32gui

from shenwu.yolo_detector import DEFAULT_ONNX_MODEL, YoloDetector

# 预览用随机配色，按 class_id 取色
_COLOR_PALETTE = np.random.uniform(0, 255, size=(len(YoloDetector.classes), 3))

# ---------------------------------------------------------------------------
# DPI：命令行进程设置 PER_MONITOR_AWARE(2)，保证 GetClientRect / ClientToScreen
# 返回物理像素，与 mss 抓屏坐标一致（GUI 进程不要调用这里，见 CODEBUDDY.md）。
# ---------------------------------------------------------------------------

def _enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _safe_console() -> None:
    """Windows 控制台默认 GBK，窗口标题里的特殊字符（如零宽空格）会打印失败。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def list_windows() -> list[tuple[int, str]]:
    """枚举所有可见、有标题的顶层窗口，返回 (hwnd, 标题) 列表。"""
    results: list[tuple[int, str]] = []

    def _on_window(hwnd: int, _: object) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return
        # 排除桌面/任务栏等系统壳窗口
        if win32gui.GetClassName(hwnd) in ("Progman", "WorkerW", "Shell_TrayWnd"):
            return
        results.append((hwnd, title))

    win32gui.EnumWindows(_on_window, None)
    return results


class WindowCapture:
    """对指定窗口客户区做持续截帧。

    每帧重新计算客户区矩形（GetClientRect + ClientToScreen），因此窗口被
    拖动、缩放都能自动跟随；窗口最小化或客户区为 0 时返回 None，由上层
    平稳处理（显示等待画面，不退出）。
    """

    def __init__(self, hwnd: int):
        self.hwnd = hwnd
        self._sct = mss.mss()
        self.size: tuple[int, int] | None = None  # (w, h) 上一帧客户区尺寸

    def is_valid(self) -> bool:
        return bool(win32gui.IsWindow(self.hwnd)) and not win32gui.IsIconic(self.hwnd)

    def grab(self) -> np.ndarray | None:
        """返回 BGR 帧；窗口不可用/最小化/尺寸为 0 时返回 None。"""
        if not self.is_valid():
            return None
        try:
            left, top, right, bottom = win32gui.GetClientRect(self.hwnd)
            if right <= 0 or bottom <= 0:
                return None
            left, top = win32gui.ClientToScreen(self.hwnd, (left, top))
            region = {"left": left, "top": top, "width": right, "height": bottom}
            frame = np.asarray(self._sct.grab(region))[:, :, :3]  # BGRA -> BGR
            self.size = (right, bottom)
            return np.ascontiguousarray(frame)
        except Exception as e:  # mss 偶发截屏失败（锁屏/切换显示器等）
            print(f"❌ 截屏失败：{e}")
            return None


def _draw_detections(img: np.ndarray,
                     dets: list[tuple[float, float, float, float, float, int]]) -> np.ndarray:
    """在图上绘制边界框和标签（预览专用，直接修改并返回 img）。"""
    for x1, y1, x2, y2, conf, cid in dets:
        color = _COLOR_PALETTE[cid].tolist()
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)

        label = f"{YoloDetector.classes[cid]}: {conf:.2f}"
        (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        ly = int(y1 - 10) if y1 - 10 > lh else int(y1 + 10)
        cv2.rectangle(img, (int(x1), ly - lh), (int(x1 + lw), ly + lh), color, cv2.FILLED)
        cv2.putText(img, label, (int(x1), ly), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    return img


def _pick_window(args: argparse.Namespace) -> int | None:
    """确定目标窗口：--hwnd 精确指定 / --title 标题子串 / 交互式选择。"""
    if args.hwnd is not None:
        hwnd = args.hwnd
        if not win32gui.IsWindow(hwnd):
            print(f"❌ hwnd {hwnd} 不是有效窗口")
            return None
        print(f"✅ 目标窗口：hwnd={hwnd} 「{win32gui.GetWindowText(hwnd)}」")
        return hwnd

    windows = list_windows()
    if not windows:
        print("❌ 未找到任何可见窗口")
        return None

    if args.title:
        matches = [(h, t) for h, t in windows if args.title.lower() in t.lower()]
        if not matches:
            print(f"❌ 没有标题包含「{args.title}」的窗口")
            return None
        if len(matches) > 1:
            print(f"⚠️ 有 {len(matches)} 个匹配窗口，使用第一个：")
            for h, t in matches:
                print(f"    hwnd={h} 「{t}」")
        hwnd, title = matches[0]
        print(f"✅ 目标窗口：hwnd={hwnd} 「{title}」")
        return hwnd

    # 交互式选择
    print("\n可选窗口：")
    for i, (h, t) in enumerate(windows):
        print(f"  [{i:2d}] hwnd={h}  {t}")
    while True:
        raw = input("\n请输入窗口序号（q 退出）: ").strip()
        if raw.lower() == "q":
            return None
        if raw.isdigit() and int(raw) < len(windows):
            hwnd, title = windows[int(raw)]
            print(f"✅ 目标窗口：hwnd={hwnd} 「{title}」")
            return hwnd
        print("❌ 输入无效，请重试")


def _waiting_screen(width: int, height: int, text: str) -> np.ndarray:
    """窗口不可用时的占位画面。"""
    screen = np.full((max(height, 240), max(width, 320), 3), (40, 40, 40), dtype=np.uint8)
    cv2.putText(screen, text, (20, screen.shape[0] // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2, cv2.LINE_AA)
    return screen


def run_preview(detector: YoloDetector, hwnd: int, title: str, every: int, max_height: int) -> None:
    """主循环：抓帧 → 推理（每 every 帧一次）→ 绘制 → 预览。"""
    capture = WindowCapture(hwnd)
    dets: list[tuple[float, float, float, float, float, int]] = []
    last_size: tuple[int, int] | None = None  # 上一次推理的帧尺寸（尺寸变化立即重推）
    window_name = f"YOLO 实时检测 - {title}"
    fps = 0.0
    frame_idx = 0

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    print("🔍 开始实时检测，预览窗口按 q / ESC 退出")

    while True:
        if not win32gui.IsWindow(hwnd):
            print("❌ 目标窗口已关闭，退出")
            break

        t0 = time.perf_counter()
        frame = capture.grab()

        if frame is None:
            # 窗口最小化 / 客户区为 0 / 截屏失败：显示占位画面并继续等待
            w, h = capture.size or (640, 480)
            display = _waiting_screen(w, h, "waiting for window... (minimized?)")
        else:
            h0, w0 = frame.shape[:2]
            # 窗口尺寸变化或到了推理帧才重新检测，其余帧复用上次结果
            if frame_idx % every == 0 or last_size != (w0, h0):
                dets = detector.detect(frame)
                last_size = (w0, h0)
            display = _draw_detections(frame.copy(), dets)

        # 预览窗口过大时等比缩小，避免超出屏幕
        if display.shape[0] > max_height:
            scale = max_height / display.shape[0]
            display = cv2.resize(display, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)

        dt = time.perf_counter() - t0
        fps = 0.9 * fps + 0.1 * (1.0 / dt) if fps else 1.0 / dt
        n = len(dets) if dets else 0
        status = f"FPS: {fps:.1f} | det: {n} | infer every {every} frame(s)"
        cv2.setWindowTitle(window_name, f"{window_name} | {status}")
        cv2.imshow(window_name, display)
        frame_idx += 1

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break

    cv2.destroyWindow(window_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="对指定桌面窗口做 YOLOv8 实时检测")
    parser.add_argument("--model", type=str, default=DEFAULT_ONNX_MODEL, help="ONNX 模型路径")
    parser.add_argument("--conf-thres", type=float, default=0.5, help="置信度阈值")
    parser.add_argument("--hwnd", type=lambda v: int(v, 0), default=None, help="目标窗口句柄（支持 0x 前缀）")
    parser.add_argument("--title", type=str, default=None, help="按窗口标题子串匹配（取第一个）")
    parser.add_argument("--list", action="store_true", help="仅列出可见窗口后退出")
    parser.add_argument("--every", type=int, default=1, help="每 N 帧推理一次，中间帧复用上次结果（性能调优）")
    parser.add_argument("--max-height", type=int, default=720, help="预览窗口最大高度（像素）")
    args = parser.parse_args()

    _enable_dpi_awareness()
    _safe_console()

    if args.list:
        for h, t in list_windows():
            print(f"  hwnd={h}  {t}")
        return

    hwnd = _pick_window(args)
    if hwnd is None:
        return

    title = win32gui.GetWindowText(hwnd) or f"hwnd={hwnd}"
    detector = YoloDetector(args.model, args.conf_thres)
    run_preview(detector, hwnd, title, max(1, args.every), args.max_height)


if __name__ == "__main__":
    main()
