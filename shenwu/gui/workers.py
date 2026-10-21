"""后台任务线程：把 controller 的业务方法搬到 QThread 里跑，避免卡住界面。

执行模型是「计划（plan）」：[(hwnd, 队列名, [(任务key, 参数), ...]), ...]，
逐个 hwnd 依次执行——先把 controller 的运行目标收窄到这一个 hwnd，
再按它绑定的队列顺序跑完，然后换下一个窗口（鼠标键盘独占，只能串行）。
可按轮次重复整个计划；每个 hwnd 共用同一个停止标志。

命令行路径不受影响（不构造 TaskWorker）。
"""

from __future__ import annotations

import threading
import time
import traceback

from PyQt6.QtCore import QThread, pyqtSignal

from shenwu.controller_cv import get_controller


class TaskWorker(QThread):
    """按计划执行：每个 hwnd 跑它绑定的队列，可重复多轮。

    plan: [(hwnd, 队列名, [(key, params), ...]), ...]
    rounds: 计划执行轮次，0 表示无限循环直到手动停止。
    round_interval: 两轮之间的等待秒数（可被停止打断）。
    continue_on_error: 某个任务出错时是否继续（否则中断整个计划）。

    信号：
      hwnd_started(hwnd, queue_name)      开始处理某个窗口
      task_started(index, key)            该窗口队列里第 index 个任务开始
      task_failed(index, key, msg)        某个任务异常
      round_started(round_index, rounds)  新一轮开始（rounds=0 表示无限）
      done(ok, message)                   整个计划结束，ok=False 时 message 是 traceback
    """

    hwnd_started = pyqtSignal(int, str)
    task_started = pyqtSignal(int, str)
    task_failed = pyqtSignal(int, str, str)
    round_started = pyqtSignal(int, int)
    done = pyqtSignal(bool, str)

    def __init__(self, plan, parent=None, rounds: int = 1,
                 round_interval: float = 0.0, continue_on_error: bool = False):
        super().__init__(parent)
        self.plan = list(plan)
        self.rounds = max(0, int(rounds))
        self.round_interval = max(0.0, float(round_interval))
        self.continue_on_error = continue_on_error
        self.stop_event = threading.Event()
        self._aborted = False  # 出错且不允许继续时置位，用于跳出整个计划

    def request_stop(self):
        """请求停止：置自身标志位，同时置全局终止信号。

        全局信号会让业务代码里所有 human_delay 在 ≤0.1s 内抛 TaskTerminated，
        从任意调用深度立即打断当前任务（不用等它跑完）。
        """
        self.stop_event.set()
        from shenwu.utils import request_terminate

        request_terminate()

    def run(self):
        # 延迟导入：controller_cv 较重（加载图标等），避免拖慢 GUI 启动
        from shenwu.controller_cv import get_controller
        from shenwu.utils import TaskTerminated, clear_terminate

        clear_terminate()
        try:
            controller = get_controller()
        except Exception:
            self.done.emit(False, traceback.format_exc())
            return

        ok, message = True, ""
        round_index = 0
        try:
            while True:
                if self.stop_event.is_set():
                    break
                if self.rounds and round_index >= self.rounds:
                    break

                round_index += 1
                self.round_started.emit(round_index, self.rounds)

                for hwnd, queue_name, tasks in self.plan:
                    if self.stop_event.is_set():
                        break
                    try:
                        controller.set_selected_hwnds([hwnd])
                    except Exception as e:
                        print(f"⚠️ hwnd={hwnd} 无法设为运行目标，跳过该窗口：{e}")
                        continue
                    self.hwnd_started.emit(hwnd, queue_name)

                    for index, (key, params) in enumerate(tasks):
                        if self.stop_event.is_set():
                            break
                        self.task_started.emit(index, key)
                        try:
                            self._dispatch(controller, key, params or {})
                        except TaskTerminated:
                            # 用户点了终止：把信号抛给外层，整个计划立即结束
                            raise
                        except Exception:
                            message = traceback.format_exc()
                            ok = False
                            self.task_failed.emit(index, key, message)
                            if not self.continue_on_error:
                                self._aborted = True
                                break
                    if self._aborted or self.stop_event.is_set():
                        break
                if self._aborted or self.stop_event.is_set():
                    break
                if self.round_interval and not self.stop_event.is_set():
                    self._interruptible_sleep(self.round_interval)
        except TaskTerminated:
            print("⏹ 已立即终止当前任务")
        finally:
            self._release_target(controller)
            self.done.emit(ok, message)

    # ---------- 内部 ----------

    def _release_target(self, controller):
        """计划结束后把运行目标恢复成全部已连接窗口"""
        try:
            controller.set_selected_hwnds([])
        except Exception:
            pass

    def _interruptible_sleep(self, seconds: float):
        """可被 stop_event 打断的等待（轮次间隔用）"""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.stop_event.is_set():
                return
            time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))

    def _dispatch(self, controller, key: str, params: dict):
        if key == "xun_you":
            controller.reset_finish_status("xun_you")
            controller.run_xun_you(stop_event=self.stop_event)

        elif key == "xiu_ye":
            controller.reset_finish_status("xiu_ye")
            controller.run_xiu_ye(stop_event=self.stop_event)

        elif key == "xiu_lian":
            controller.reset_finish_status("xiu_lian")
            controller.run_xiu_lian(stop_event=self.stop_event)

        elif key == "fish":
            controller.run_fish(stop_event=self.stop_event)

        elif key == "auto_reset_round":
            controller.run_auto_reset_round(
                is_hide=bool(params.get("is_hide", False)),
                stop_event=self.stop_event,
            )

        elif key == "qu_mo":
            controller.check_qu_mo()

        elif key == "auto_task":
            task_name = str(params.get("task_name", "")).strip()
            if not task_name:
                raise ValueError("任务名不能为空")
            controller.run_auto_task(task_name)

        elif key == "test_resources":
            controller.test_resources(
                stop_event=self.stop_event,
                threshold=params.get("threshold"),
                icon_names=params.get("icon_names"),
            )

        elif key == "test_get_color":
            controller.test_get_color(
                color=params.get("color", "blue"),
                stop_event=self.stop_event,
            )

        else:
            raise ValueError(f"未知任务: {key}")
