"""任务卡片：任务清单定义 + 参数控件 + 卡片行为。

职责边界：只描述「有哪些任务、需要哪些参数、卡片怎么展示与回填」，
不涉及队列管理、窗口绑定、线程调度（那些在 main_window / workers）。
新增任务 = 在 TASKS 里加一条 TaskSpec + 在 workers.dispatch_task 里加一个分支。
"""

from dataclasses import dataclass

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from shenwu.gui.theme import repolish


@dataclass
class Param:
    """卡片上的参数控件

    kind: text / check
    """

    name: str
    label: str
    kind: str = "text"
    default: str = ""
    options: tuple[str, ...] = ()
    placeholder: str = ""


@dataclass
class TaskSpec:
    """一个任务卡片的定义"""

    key: str
    title: str
    desc: str
    run_text: str = "加入队列"
    params: tuple[Param, ...] = ()
    tip: str = ""


TASKS: tuple[TaskSpec, ...] = (
    TaskSpec(
        "xun_you", "巡游", "自动完成该窗口的巡游任务，完成后自动结束",
    ),
    TaskSpec(
        "xiu_ye", "修业", "按任务类型自动购买 / 战斗 / 封印",
    ),
    TaskSpec(
        "xiu_lian", "修炼", "寻物 / 找人 / 疯道人，未接任务时从日历寻路",
    ),
    TaskSpec(
        "bao_ta", "玲珑宝塔", "自动挑战宝塔并确保战斗开启，按次数循环",
        params=(Param("count", "挑战次数", "text", default="10",
                      placeholder="如：10"),),
    ),
    TaskSpec(
        "bao_tu", "挖宝图（司南）", "开背包 → 识别所有司南 → 逐个右键 → YOLO 自动挖宝",
        tip="全部司南挖完后自动结束；挖宝中途可用行内「停止」立即中断",
    ),
    TaskSpec(
        "check_qu_mo", "检查驱魔", "不在驱魔状态时开背包右键驱魔香，收尾自动关闭背包",
        tip="每次执行检查一次；多开时各窗口独立判断",
    ),
    TaskSpec(
        "reset_round", "重置回合（队员）", "循环点击「自动」按钮重置回合，给队员窗口常驻用",
        params=(Param("interval", "检查间隔(秒)", "text", default="3",
                      placeholder="如：3"),),
        tip="队员窗口专用：轮次设 0（一直重复）；队长窗口另绑一条执行任务的队列",
    ),
)


class TaskCard(QFrame):
    """单个任务卡片：标题 + 说明 + 参数 + 「加入队列」按钮（没有单独启停）"""

    add_to_queue = pyqtSignal(str)

    def __init__(self, spec: TaskSpec, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.widgets: dict[str, QWidget] = {}
        self._param_labels: dict[str, QLabel] = {}

        self.setObjectName("card")
        self.setProperty("state", "idle")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        # 标题
        head = QHBoxLayout()
        head.setSpacing(6)
        title = QLabel(spec.title)
        title.setObjectName("cardTitle")
        head.addWidget(title)
        head.addStretch(1)
        root.addLayout(head)

        for param in spec.params:
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(param.label)
            label.setObjectName("paramLabel")
            self._param_labels[param.name] = label
            row.addWidget(label)
            if param.kind == "check":
                widget: QWidget = QCheckBox()
                widget.setChecked(bool(param.default))
            else:
                widget = QLineEdit()
                widget.setText(param.default)
                widget.setPlaceholderText(param.placeholder)
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            row.addWidget(widget, 1)
            self.widgets[param.name] = widget
            root.addLayout(row)

        if spec.tip:
            tip = QLabel(spec.tip)
            tip.setObjectName("cardTip")
            tip.setWordWrap(True)
            root.addWidget(tip)

        root.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.btn_add = QPushButton(spec.run_text)
        self.btn_add.setProperty("primary", True)
        self.btn_add.setToolTip("把该任务（连同当前参数）追加到当前选中的队列末尾")
        self.btn_add.clicked.connect(lambda: self.add_to_queue.emit(spec.key))
        buttons.addWidget(self.btn_add)
        buttons.addStretch(1)
        root.addLayout(buttons)

        self.set_state("idle")

    # ---------- 参数 ----------

    def get_params(self) -> dict:
        values = {}
        for name, widget in self.widgets.items():
            if isinstance(widget, QCheckBox):
                values[name] = widget.isChecked()
            else:
                values[name] = widget.text()
        return values

    def set_params(self, values: dict):
        """从配置回填参数（只写存在的控件）"""
        for name, value in (values or {}).items():
            widget = self.widgets.get(name)
            if widget is None:
                continue
            try:
                if isinstance(widget, QCheckBox):
                    widget.setChecked(bool(value))
                else:
                    widget.setText(str(value))
            except Exception:
                pass

    # ---------- 状态 ----------

    def set_state(self, state: str):
        """state: idle / running（当前正在执行的任务高亮）"""
        busy = state == "running"

        self.setProperty("state", state)
        self.setProperty("locked", False)
        self.btn_add.setEnabled(not busy)

        for widget in self.widgets.values():
            widget.setEnabled(not busy)

        repolish(self)

    def set_locked(self, locked: bool):
        """有任务在跑时锁住所有卡片（队列正在执行，参数暂不能改）"""
        self.set_state("idle")
        if locked:
            self.btn_add.setEnabled(False)
            for widget in self.widgets.values():
                widget.setEnabled(False)
            self.setProperty("locked", True)
            repolish(self)
