"""后台任务执行：任务分发 + 单窗口队列线程。

执行模型以 hwnd 为单位：每个窗口一条 RowWorker 线程，相互独立、可并行；
dispatch_task 按 key 调 controller 对应方法，hwnd 用于把 run_xxx 定位到
正确窗口。三个窗口级任务（巡游/修业/修炼）的输入全部是消息级 PostMessage
（按 hwnd 定向），多线程并行互不干扰。

停止语义：
- 单行「停止」：request_stop 同时置行级 stop_event（循环边界退出）与
  行级 terminate_event（bind_thread_terminate 绑定到本线程）→ 当前任务里的
  human_delay 在 ≤0.1s 内抛 TaskTerminated，立即打断且不影响其他窗口；
- 全局终止（Ctrl+Alt+Q / 托盘立即停止）置 terminate_event →
  human_delay 立即抛 TaskTerminated，打断所有行。
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

    elif key == "bao_tu":
        controller.bao_tu(hwnd_index=_resolve_index(controller, hwnd),
                          stop_event=stop_event)

    elif key == "check_qu_mo":
        controller.check_qu_mo(hwnd_index=_resolve_index(controller, hwnd))

    elif key == "reset_round":
        try:
            interval = float(params.get("interval", 3))
        except (TypeError, ValueError):
            raise ValueError("检查间隔必须是数字（秒）")
        controller.run_reset_round(hwnd_index=_resolve_index(controller, hwnd),
                                   interval=max(0.5, interval),
                                   stop_event=stop_event)

    else:
        raise ValueError(f"未知任务: {key}")


class RowWorker(threading.Thread):
    """单窗口队列线程：按顺序跑完绑定队列的任务，可按轮次重复。

    一次只服务一个 hwnd；多个 RowWorker 相互独立、可并行
    （输入全部为消息级，按 hwnd 定向）。request_stop 通过行级
    terminate_event 立即打断当前任务（见模块 docstring 的停止语义）。
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
        self.stop_event = threading.Event()        # 循环边界退出
        self.terminate_event = threading.Event()   # 行级立即打断（本线程专属）

    def request_stop(self):
        """立即停止：打断当前任务（行级 human_delay 立即抛 TaskTerminated），
        同时置 stop_event 保证循环边界判断也立即为真"""
        self.stop_event.set()
        self.terminate_event.set()

    def run(self):
        from shenwu.timing import TaskTerminated, bind_thread_terminate, clear_terminate

        # 上一次「全部停止 / 紧急停止」置位的全局信号必须在这里复位：否则本轮任务
        # 第一个 human_delay 就会抛 TaskTerminated，表现为「刚运行就自己停了」。
        # 全局信号只对当时正在运行的线程有意义（它们已经在 human_delay 里被唤醒）。
        clear_terminate()

        # 把行级终止事件绑定到本线程：human_delay 检查到它就抛 TaskTerminated，
        # 与其他窗口的 RowWorker 互不影响
        bind_thread_terminate(self.terminate_event)

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
