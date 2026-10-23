"""终止信号与人味化延时。

职责边界：只负责「怎么停」与「等多久」，不碰窗口、截图、输入。
所有后台任务都通过 human_delay 感知终止，因此这里是并发停止语义的唯一实现点。

两级终止：
- 全局 terminate_event：GUI 的「全部停止 / 紧急停止」，打断所有线程；
- 行级线程本地事件（bind_thread_terminate）：GUI 单行「停止」，只打断绑定的线程。
"""

import math
import random
import threading
import time

# ---------- 「终止」信号（GUI 的停止按钮用） ----------
# 置位后 human_delay 会在下一片睡眠（最多 0.1s）内抛 TaskTerminated，把当前任务
# 从任意调用深度立即打断；命令行从不置位，行为与原来完全一致。
terminate_event = threading.Event()


class TaskTerminated(BaseException):
    """用户请求立即终止。

    继承 BaseException 而不是 Exception，是为了绕过业务代码里
    「except Exception」的逐窗口兜底，把终止信号一路传回任务线程。
    """


def request_terminate():
    terminate_event.set()


def clear_terminate():
    terminate_event.clear()


# 行级立即终止：后台线程可绑定一个专属事件，human_delay 同样立即打断。
# 与全局 terminate_event 的区别：只打断绑定了它的那一条线程，其他线程
# （其他窗口的并行任务）完全不受影响，GUI 的单行「停止」靠它实现。
_thread_terminate = threading.local()


def bind_thread_terminate(event: threading.Event):
    """给当前线程绑定专属终止事件；human_delay 会同时检查全局与该事件"""
    _thread_terminate.event = event


def _is_terminated() -> bool:
    """全局终止或当前线程的行级终止任一置位即视为终止"""
    if terminate_event.is_set():
        return True
    ev = getattr(_thread_terminate, "event", None)
    return ev is not None and ev.is_set()


def is_stopped(stop_event) -> bool:
    """GUI 用来中断长循环的标志位；stop_event 为 None 时永不停止（命令行行为不变）"""
    return stop_event is not None and stop_event.is_set()


def rand_secs(base_seconds: float, sigma: float = 0.3) -> float:
    """生成一条人类化的随机等待秒数，base_seconds 为中位数"""
    return max(0.05, random.lognormvariate(math.log(base_seconds), sigma))


def human_delay(base_seconds: float, sigma: float = 0.3) -> None:
    """睡眠一段人类化的随机时间；需要拿到秒数本身时用 rand_secs。

    睡眠按最多 0.1s 一片切分，每片之间检查终止信号 —— 收到「终止」立即抛
    TaskTerminated，让 wait_until / 业务循环当场退出，而不是睡完这一觉。
    """
    deadline = time.monotonic() + rand_secs(base_seconds, sigma)
    while True:
        if _is_terminated():
            raise TaskTerminated("用户请求终止")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.1, remaining))
