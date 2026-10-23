"""后台任务执行：任务分发 + 单窗口队列线程。

执行模型以 hwnd 为单位：每个窗口一条 RowWorker 线程，相互独立、可并行；
dispatch_task 按 key 调 controller 对应方法，hwnd 用于把 run_xxx 定位到
正确窗口。三个窗口级任务（巡游/修业/修炼）的输入全部是消息级 PostMessage
（按 hwnd 定向），多线程并行互不干扰。

停止语义：
- RowWorker.stop_event 置位 → 任务在循环边界优雅退出（数秒内）；
- 全局终止（Ctrl+Alt+Q / 托盘立即停止）置 terminate_event →
  human_delay 立即抛 TaskTerminated，从任意调用深度打断。
命令行路径不受影响（不构造 RowWorker）。
"""

from __future__ import annotations

import threading
import time
import traceback


def _resolve_index(controller, hwnd) -> int:
    """hwnd -> hwnd_list 下标；hwnd 无效时回退 0"""
    if hwnd is not None and hwnd in controller.hwnd_list:
        return controller.hwnd_list.index(hwnd)
    return 0


def dispatch_task(controller, key: str, params: dict,
                  stop_event: threading.Event, hwnd=None):
    """把任务 key 分发到 controller 对应方法（行内运行与定时执行共用）。

    hwnd 给了就把窗口级任务（巡游/修业/修炼）定位到该窗口——这是多窗口
    并行执行的基础；不传则保持默认（hwnd_index=0）。
    """
    params = params or {}
    if key == "xun_you":
        controller.reset_finish_status("xun_you", hwnd=hwnd)
        controller.run_xun_you(hwnd_index=_resolve_index(controller, hwnd),
                               stop_event=stop_event)

    elif key == "xiu_ye":
        controller.reset_finish_status("xiu_ye", hwnd=hwnd)
        controller.run_xiu_ye(hwnd_index=_resolve_index(controller, hwnd),
                              stop_event=stop_event)

    elif key == "xiu_lian":
        controller.reset_finish_status("xiu_lian", hwnd=hwnd)
        controller.run_xiu_lian(hwnd_index=_resolve_index(controller, hwnd),
                                stop_event=stop_event)

    elif key == "bao_ta":
        try:
            count = int(params.get("count", 10))
        except (TypeError, ValueError):
            raise ValueError("挑战次数必须是数字")
        controller.bao_ta(hwnd_index=_resolve_index(controller, hwnd),
                          count=max(1, count), stop_event=stop_event)

    elif key == "auto_task":
        task_name = str(params.get("task_name", "")).strip()
        if not task_name:
            raise ValueError("任务名不能为空")
        controller.run_auto_task(task_name)

    elif key == "test_resources":
        controller.test_resources(
            stop_event=stop_event,
            threshold=params.get("threshold"),
            icon_names=params.get("icon_names"),
        )

    elif key == "test_get_color":
        controller.test_get_color(
            color=params.get("color", "blue"),
            stop_event=stop_event,
        )

    elif key == "test_si_nan":
        controller.test_si_nan(
            stop_event=stop_event,
            threshold=params.get("threshold"),
        )

    else:
        raise ValueError(f"未知任务: {key}")


class RowWorker(threading.Thread):
    """单窗口队列线程：按顺序跑完绑定队列的任务，可按轮次重复。

    一次只服务一个 hwnd；多个 RowWorker 相互独立、可并行
    （输入全部为消息级，按 hwnd 定向）。stop_event 置位后在任务循环
    边界优雅退出。
    """

    def __init__(self, controller, hwnd, queue_name, tasks,
                 rounds: int = 1, round_interval: float = 0.0,
                 on_finished=None):
        super().__init__(name=f"row-hwnd{hwnd}", daemon=True)
        self.controller = controller
        self.hwnd = hwnd
        self.queue_name = queue_name
        self.tasks = list(tasks)
        self.rounds = max(0, int(rounds))          # 0 = 无限循环
        self.round_interval = max(0.0, float(round_interval))
        self._on_finished = on_finished            # 结束回调（线程内调用）
        self.stop_event = threading.Event()

    def request_stop(self):
        """优雅停止：在任务循环边界退出，不打断当前操作"""
        self.stop_event.set()

    def run(self):
        from shenwu.utils import TaskTerminated

        try:
            round_index = 0
            while not self.stop_event.is_set():
                if self.rounds and round_index >= self.rounds:
                    break
                round_index += 1

                for key, params in self.tasks:
                    if self.stop_event.is_set():
                        return
                    try:
                        dispatch_task(self.controller, key, params or {},
                                      self.stop_event, hwnd=self.hwnd)
                    except TaskTerminated:
                        raise          # 全局终止：向上穿透，立即结束
                    except Exception:
                        # 单个任务异常不拖垮整条队列，继续后面的任务
                        traceback.print_exc()

                if self.rounds and round_index >= self.rounds:
                    break
                if self.round_interval and not self.stop_event.is_set():
                    self._interruptible_sleep(self.round_interval)
        except TaskTerminated:
            print(f"⏹ hwnd={self.hwnd} 已立即终止")
        finally:
            if self._on_finished is not None:
                self._on_finished(self.hwnd)

    def _interruptible_sleep(self, seconds: float):
        """可被 stop_event 打断的等待（轮次间隔用）"""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.stop_event.is_set():
                return
            time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
