"""业务流程模块（Mixin）。

每个模块只承载一类任务的单窗口流程，方法通过 self 使用 GameController 提供的
公共能力（grab_frame / find / find_all / click_match / wait_until / is_open_*）。

约定：
- 公开方法按窗口序号：`xxx(hwnd_index=0, stop_event=None)`；
- 单窗口实现：`_xxx_hwnd(hwnd, ...)`，只读写自己 hwnd 的状态，可多线程并行；
- 新增任务时：在此目录建模块 -> 定义 Mixin -> 让 GameController 继承 ->
  在 gui/tasks.py 注册卡片 -> 在 gui/workers.py 注册派发分支。
"""

from shenwu.tasks.bao_ta import BaoTaTasks
from shenwu.tasks.bao_tu import BaoTuTasks

__all__ = ["BaoTaTasks", "BaoTuTasks"]
