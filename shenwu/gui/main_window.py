"""PyQt 主窗口：以 hwnd 为核心的自动化控制台。

执行流程：在窗口列表选中一个 hwnd -> 在窗口面板选择要执行的队列 -> 点「运行」。
- 队列在「执行队列」面板里自定义（增删任务、排序、新建/删除队列），本地持久化；
- 运行即把该 hwnd 绑定到所选队列（按服务器名持久化），供定时执行与边框显示复用；
- 「定时」到点后按各窗口已绑定的队列依次执行（鼠标键盘独占，只能串行）。

任务卡片只负责「编辑参数 + 加入队列」，没有单独的启停按钮；
开发/测试类功能（诊断等）默认隐藏，通过标题栏的「开发/测试」开关显示。
"""

from __future__ import annotations

import ctypes
import sys
import time
from dataclasses import dataclass

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

import win32con
import win32gui

from shenwu.gui import settings
from shenwu.gui.theme import QSS
from shenwu.gui.workers import TaskWorker

# 「定位」标识：边框颜色与自动消失时长
IDENTIFY_COLOR = (255, 200, 0)
IDENTIFY_SECONDS = 5

GRID_COLUMNS = 4

# 紧急停止热键：Ctrl + Alt + Q（脚本运行时游戏窗口会盖住界面，用它兜底）
EMERGENCY_MODIFIERS = (0x11, 0x12)  # VK_CONTROL / VK_MENU(Alt)
EMERGENCY_VK = 0x51  # Q

DEFAULT_QUEUE_NAME = "默认队列"


@dataclass
class Param:
    """卡片上的参数控件

    kind: text / check / combo / history(可编辑下拉+历史) / icon_combo(图标下拉,运行时填充)
          / slider(0~100 的滑杆，取值时换算成 0~1 的匹配阈值)
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
    dev_only: bool = False  # 开发/测试类功能，默认不在主界面显示


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
        "auto_task", "OCR 自动任务", "OCR 识别屏幕上的任务名并点击",
        params=(Param("task_name", "任务名", "history", default="法宝引导",
                      placeholder="如：法宝引导"),),
    ),
    # ---------- 开发/测试（默认隐藏，标题栏开关显示） ----------
    TaskSpec(
        "test_resources", "图标检测诊断", "实时预览指定图标的匹配结果（可调阈值）",
        tip="打开 OpenCV 预览窗口，按 q 退出",
        params=(Param("icon_name", "图标", "icon_combo"),
                Param("threshold", "阈值", "slider", default="0.70")),
        dev_only=True,
    ),
    TaskSpec(
        "test_get_color", "颜色检测诊断", "实时可视化 get_color 的搜索区域与结果",
        tip="打开 OpenCV 预览窗口，按 q 退出",
        params=(Param("color", "颜色", "combo", default="blue",
                      options=("blue", "yellow", "red")),),
        dev_only=True,
    ),
)

DEV_TASK_KEYS = tuple(spec.key for spec in TASKS if spec.dev_only)


def _repolish(widget: QWidget):
    """改了动态属性后强制重新应用样式表"""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


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
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        # 标题 + 队列计数
        head = QHBoxLayout()
        head.setSpacing(6)
        title = QLabel(spec.title)
        title.setObjectName("cardTitle")
        self.queue_badge = QLabel("")
        self.queue_badge.setObjectName("queueBadge")
        head.addWidget(title)
        head.addWidget(self.queue_badge)
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
            elif param.kind in ("combo", "icon_combo"):
                widget = QComboBox()
                if param.options:
                    widget.addItems(param.options)
                    widget.setCurrentText(param.default)
                if param.kind == "icon_combo":
                    widget.setToolTip("连接游戏窗口后自动填充 resource 里的图标")
            elif param.kind == "history":
                widget = QComboBox()
                widget.setEditable(True)
                widget.setInsertPolicy(QComboBox.InsertPolicy.InsertAtTop)
                if param.options:
                    widget.addItems(param.options)
                widget.setCurrentText(param.default)
                widget.lineEdit().setPlaceholderText(param.placeholder)
            elif param.kind == "slider":
                widget = QSlider(Qt.Orientation.Horizontal)
                widget.setRange(0, 100)
                widget.setSingleStep(5)
                widget.setValue(int(float(param.default) * 100))

                def show_value(value, _label=label, _base=param.label):
                    _label.setText(f"{_base}  {value / 100:.2f}")

                widget.valueChanged.connect(show_value)
                show_value(widget.value())
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
            elif isinstance(widget, QComboBox):
                values[name] = widget.currentText()
            elif isinstance(widget, QSlider):
                values[name] = widget.value() / 100.0
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
                elif isinstance(widget, QComboBox):
                    widget.setCurrentText(str(value))
                elif isinstance(widget, QSlider):
                    widget.setValue(int(float(value) * 100))
                else:
                    widget.setText(str(value))
            except Exception:
                pass

    def set_param_options(self, name: str, options):
        """运行时填充下拉框选项（图标列表要等 controller 就绪才有）"""
        widget = self.widgets.get(name)
        if not isinstance(widget, QComboBox):
            return
        current = widget.currentText()
        widget.blockSignals(True)
        widget.clear()
        widget.addItems(list(options))
        if current in options:
            widget.setCurrentText(current)
        widget.blockSignals(False)

    # ---------- 状态 ----------

    def set_state(self, state: str):
        """state: idle / running（当前正在执行的任务高亮）"""
        busy = state == "running"

        self.setProperty("state", state)
        self.setProperty("locked", False)
        self.btn_add.setEnabled(not busy)

        for widget in self.widgets.values():
            widget.setEnabled(not busy)

        _repolish(self)

    def set_locked(self, locked: bool):
        """有任务在跑时锁住所有卡片（队列正在执行，参数暂不能改）"""
        self.set_state("idle")
        if locked:
            self.btn_add.setEnabled(False)
            for widget in self.widgets.values():
                widget.setEnabled(False)
            self.setProperty("locked", True)
            _repolish(self)

    def set_queue_count(self, count: int):
        """该任务在当前队列里出现了几次，方便确认已加入"""
        self.queue_badge.setText(f"队列 ×{count}" if count else "")


class _LogTee:
    """把 print / traceback 同时送到界面日志和原始终端。

    业务代码是分多次 write 的（print 的正文和换行各一次），所以这里按行缓冲，
    凑满一行再加时间戳发出去，保证每行日志都有 [时:分:秒] 前缀。
    """

    def __init__(self, emit, original):
        self._emit = emit
        self._original = original
        self._buffer = ""
        self.encoding = "utf-8"
        self.errors = "replace"

    def write(self, text):
        try:
            self._original.write(text)
        except Exception:
            pass

        if not text:
            return len(text or "")

        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._emit(f"[{time.strftime('%H:%M:%S')}] {line}\n")
        return len(text)

    def flush(self):
        try:
            self._original.flush()
        except Exception:
            pass

    def isatty(self):
        return False


class MainWindow(QMainWindow):
    log_text = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.cards: dict[str, TaskCard] = {}
        self.worker: TaskWorker | None = None
        self.mode: str | None = None  # "plan" / None
        self._current_index = -1
        self._current_key: str | None = None
        self._stopping = False
        self._last_error = ""

        # 队列定义（持久化）与窗口绑定（运行时 hwnd -> 队列名）
        self.queues: dict[str, list[dict]] = {}
        self.active_queue: str = ""
        self.bindings: dict[int, str] = {}

        # 当前选中的窗口（单选）
        self.selected_hwnds: list[int] = []

        # 「定位」按钮的临时标识覆盖层：hwnd -> overlay，5 秒自动消失
        self._identify_overlays: dict[int, object] = {}
        self._identify_buttons: dict[int, QPushButton] = {}
        self._identify_timer = QTimer(self)
        self._identify_timer.setInterval(30)
        self._identify_timer.timeout.connect(self._pump_identify)

        # 当前任务名（显示在窗口边框上）/ 正在处理的窗口
        self._active_task = ""
        self._active_hwnd: int | None = None
        self._log_lines: list[str] = []  # 过滤用的日志缓冲
        self._listed_hwnds: list[int] = []  # 上一次列表里的 hwnd，用于判断是否需要重建
        self.settings = settings.load()
        self._restoring = False  # 回填配置期间禁止写回，见 _restore_settings

        # 空闲时自动刷新窗口列表
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setInterval(5000)
        self._auto_refresh_timer.timeout.connect(self._auto_refresh_windows)

        # 紧急停止热键轮询（读不到按键状态也不影响其它功能）
        self._hotkey_timer = QTimer(self)
        self._hotkey_timer.setInterval(150)
        self._hotkey_timer.timeout.connect(self._check_emergency_hotkey)

        # 定时任务：每 30 秒跑一次 pending（schedule 的 job 在主线程执行，不阻塞）
        self._schedule_timer = QTimer(self)
        self._schedule_timer.setInterval(30000)
        self._schedule_timer.timeout.connect(self._run_pending_schedule)

        self.setWindowTitle("幻唐志 · 脚本控制台")
        self.resize(1020, 960)
        self.setMinimumSize(900, 820)

        self.log_text.connect(self._append_log)

        self._build_header()
        self._build_body()
        self._restore_settings()
        self._refresh_queue_panel()
        self._build_tray()
        self.statusBar().showMessage("就绪")

        self._hotkey_timer.start()
        self._schedule_timer.start()
        if self.chk_auto_refresh.isChecked():
            self._auto_refresh_timer.start()

        # 窗口显示后再连游戏 / 枚举窗口，避免控制器初始化阻塞启动
        QTimer.singleShot(150, self._refresh_windows)
        QTimer.singleShot(300, self._refresh_window_table)

    # ---------- 配置持久化 ----------

    def _restore_settings(self):
        """把 gui_settings.json 里的内容回填到界面"""
        conf = self.settings
        # 回填过程中控件会触发 valueChanged/toggled -> _save_settings，
        # 不抑制就会把「还没恢复完」的状态写回文件
        self._restoring = True
        try:
            self.queues = {
                name: list(items or []) for name, items in (conf.get("queues") or {}).items()
            }
            self.active_queue = str(conf.get("active_queue") or "")
            if self.active_queue not in self.queues:
                self.active_queue = next(iter(self.queues), "")

            for key, values in (conf.get("params") or {}).items():
                card = self.cards.get(key)
                if card is not None:
                    card.set_params(values)

            self.cards["auto_task"].set_param_options("task_name", conf.get("ocr_history", []))
            self.chk_auto_scroll.setChecked(bool(conf.get("auto_scroll", True)))
            self.chk_auto_refresh.setChecked(bool(conf.get("auto_refresh", True)))
            self.btn_dev_tools.setChecked(bool(conf.get("show_dev_tools", False)))
            self._apply_dev_tools_visibility()

            loop = conf.get("loop") or {}
            self.spin_times.setValue(int(loop.get("times", 1)))
            self.spin_interval.setValue(int(loop.get("interval", 30)))
            self.chk_continue_on_error.setChecked(bool(loop.get("continue_on_error", False)))

            plan = conf.get("schedule") or {}
            self.chk_schedule.setChecked(bool(plan.get("enabled", False)))
            self.time_schedule.setTime(_parse_time(str(plan.get("time", "12:00"))))

            diag = conf.get("diagnostic") or {}
            self.cards["test_resources"].set_params({"threshold": float(diag.get("threshold", 70)) / 100})
            self.cards["test_get_color"].set_params({"color": diag.get("color", "blue")})
        finally:
            self._restoring = False
            self._apply_schedule_setting()

    def _save_settings(self):
        """把当前界面状态写回 gui_settings.json"""
        if self._restoring:
            return
        conf = self.settings
        conf["queues"] = self.queues
        conf["active_queue"] = self.active_queue
        conf["show_dev_tools"] = self.btn_dev_tools.isChecked()
        conf["params"] = {key: card.get_params() for key, card in self.cards.items()
                          if card.get_params()}
        conf["auto_scroll"] = self.chk_auto_scroll.isChecked()
        conf["auto_refresh"] = self.chk_auto_refresh.isChecked()
        conf["loop"] = {
            "times": self.spin_times.value(),
            "interval": self.spin_interval.value(),
            "continue_on_error": self.chk_continue_on_error.isChecked(),
        }
        conf["schedule"] = {
            "enabled": self.chk_schedule.isChecked(),
            "time": self.time_schedule.time().toString("HH:mm"),
        }
        conf["diagnostic"] = {
            "threshold": int(self.cards["test_resources"].get_params().get("threshold", 0.7) * 100),
            "icon_name": self.cards["test_resources"].get_params().get("icon_name", ""),
            "color": self.cards["test_get_color"].get_params().get("color", "blue"),
        }
        settings.save(conf)

    def _save_bindings(self):
        """把 hwnd 绑定转成 服务器名 -> 队列名 存盘（hwnd 跨重启会变）"""
        from shenwu.controller_cv import get_controller

        by_server = {}
        try:
            controller = get_controller()
            for hwnd, queue_name in self.bindings.items():
                status = controller.hwnd_status.get(hwnd)
                if status is not None and status.server:
                    by_server[status.server] = queue_name
        except Exception:
            pass
        self.settings["bindings"] = by_server
        self._save_settings()

    def _update_ocr_history(self, task_name: str):
        """OCR 任务名去重后入历史（最多 10 条）"""
        task_name = (task_name or "").strip()
        if not task_name:
            return
        history = self.settings.get("ocr_history") or []
        if task_name in history:
            history.remove(task_name)
        history.insert(0, task_name)
        self.settings["ocr_history"] = history[:10]
        self.cards["auto_task"].set_param_options("task_name", self.settings["ocr_history"])

    # ---------- 构建界面 ----------

    def _build_header(self):
        title = QLabel("幻唐志 · 脚本控制台")
        title.setObjectName("appTitle")
        sub = QLabel("流程：选择窗口 → 选择队列 → 运行 · 请先打开游戏窗口")
        sub.setObjectName("appSub")

        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(title)
        texts.addWidget(sub)

        self.pill = QLabel("未连接")
        self.pill.setObjectName("pill")
        self.pill.setProperty("state", "idle")

        self.btn_refresh = QPushButton("连接 / 刷新窗口")
        self.btn_refresh.clicked.connect(self._refresh_windows)

        self.btn_dev_tools = QPushButton("开发/测试")
        self.btn_dev_tools.setCheckable(True)
        self.btn_dev_tools.setToolTip("显示 / 隐藏图标检测、颜色检测等开发调试功能")
        self.btn_dev_tools.toggled.connect(self._on_dev_tools_toggled)

        layout = QHBoxLayout()
        layout.setSpacing(12)
        layout.addLayout(texts)
        layout.addStretch(1)
        layout.addWidget(self.btn_dev_tools)
        layout.addWidget(self.pill)
        layout.addWidget(self.btn_refresh)

        header = QWidget()
        header.setLayout(layout)
        self._header = header

    def _on_dev_tools_toggled(self, _checked: bool):
        self._apply_dev_tools_visibility()
        self._save_settings()

    def _apply_dev_tools_visibility(self):
        show = self.btn_dev_tools.isChecked()
        for key in DEV_TASK_KEYS:
            card = self.cards.get(key)
            if card is not None:
                card.setVisible(show)

    def _build_body(self):
        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(14)
        outer.addWidget(self._header)
        outer.addWidget(self._build_queue_panel())
        outer.addWidget(self._build_task_area(), 1)
        outer.addWidget(self._build_log_area())
        self.setCentralWidget(root)

    # ---------- 队列管理面板 ----------

    def _build_queue_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("queueBar")

        label = QLabel("执行队列")
        label.setObjectName("sectionLabel")

        self.combo_queue = QComboBox()
        self.combo_queue.setEditable(True)
        self.combo_queue.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo_queue.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.combo_queue.setToolTip("选择要编辑 / 绑定的队列；输入新名字后点「新建」可创建")
        self.combo_queue.currentTextChanged.connect(self._on_queue_selected)

        self.btn_queue_new = QPushButton("新建")
        self.btn_queue_new.clicked.connect(self._new_queue)
        self.btn_queue_delete = QPushButton("删除")
        self.btn_queue_delete.clicked.connect(self._delete_queue)

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        row1.addWidget(label)
        row1.addWidget(self.combo_queue, 1)
        row1.addWidget(self.btn_queue_new)
        row1.addWidget(self.btn_queue_delete)

        # 队列内容
        self.queue_list = QListWidget()
        self.queue_list.setObjectName("queueList")
        self.queue_list.setFixedHeight(120)
        self.queue_list.setToolTip("当前队列的任务顺序；选中后可上移 / 下移 / 移除")

        self.btn_task_up = QPushButton("上移")
        self.btn_task_up.clicked.connect(lambda: self._move_task(-1))
        self.btn_task_down = QPushButton("下移")
        self.btn_task_down.clicked.connect(lambda: self._move_task(1))
        self.btn_task_remove = QPushButton("移除")
        self.btn_task_remove.clicked.connect(self._remove_task)
        self.btn_queue_clear = QPushButton("清空")
        self.btn_queue_clear.clicked.connect(self._clear_queue_tasks)

        side = QVBoxLayout()
        side.setSpacing(6)
        side.addWidget(self.btn_task_up)
        side.addWidget(self.btn_task_down)
        side.addWidget(self.btn_task_remove)
        side.addWidget(self.btn_queue_clear)

        content = QHBoxLayout()
        content.setSpacing(10)
        content.addWidget(self.queue_list, 1)
        content.addLayout(side)

        box = QVBoxLayout(panel)
        box.setContentsMargins(14, 10, 14, 10)
        box.setSpacing(8)
        box.addLayout(row1)
        box.addLayout(content)
        box.addLayout(self._build_loop_controls())
        return panel

    def _build_loop_controls(self) -> QHBoxLayout:
        """轮次 / 间隔 / 出错继续 / 定时执行"""
        row = QHBoxLayout()
        row.setSpacing(8)

        self.spin_times = QSpinBox()
        self.spin_times.setRange(0, 999)
        self.spin_times.setValue(1)
        self.spin_times.setFixedWidth(52)
        self.spin_times.setToolTip("整个计划执行的轮次：1 = 跑一遍；0 = 一直重复，直到手动停止")
        self.spin_times.valueChanged.connect(self._save_settings)

        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(0, 3600)
        self.spin_interval.setValue(30)
        self.spin_interval.setFixedWidth(60)
        self.spin_interval.setSuffix("s")
        self.spin_interval.setToolTip("每轮结束后的等待秒数（可被停止打断）")
        self.spin_interval.valueChanged.connect(self._save_settings)

        self.chk_continue_on_error = QCheckBox("出错继续")
        self.chk_continue_on_error.setToolTip("某个任务报错时跳过它，继续执行后面的任务")
        self.chk_continue_on_error.toggled.connect(self._save_settings)

        self.chk_schedule = QCheckBox("定时")
        self.chk_schedule.setToolTip("到点自动执行已绑定的计划（界面需保持开启）")
        self.chk_schedule.toggled.connect(self._apply_schedule_setting)

        self.time_schedule = QTimeEdit()
        self.time_schedule.setDisplayFormat("HH:mm")
        self.time_schedule.setFixedWidth(62)
        self.time_schedule.timeChanged.connect(lambda _t: self._apply_schedule_setting())

        row.addWidget(QLabel("轮次"))
        row.addWidget(self.spin_times)
        row.addWidget(QLabel("间隔"))
        row.addWidget(self.spin_interval)
        row.addWidget(self.chk_continue_on_error)
        row.addWidget(self.chk_schedule)
        row.addWidget(self.time_schedule)
        row.addStretch(1)
        return row

    # ---------- 队列管理 ----------

    def _refresh_queue_panel(self):
        """按 self.queues / self.active_queue 重建下拉框和任务列表"""
        self.combo_queue.blockSignals(True)
        self.combo_queue.clear()
        self.combo_queue.addItems(list(self.queues))
        if self.active_queue:
            self.combo_queue.setCurrentText(self.active_queue)
        self.combo_queue.blockSignals(False)

        self._refresh_queue_list()
        self._refresh_card_badges()
        # 同步窗口面板的运行队列下拉框（保持当前选择不变）
        current = self.combo_run_queue.currentText()
        self.combo_run_queue.blockSignals(True)
        self.combo_run_queue.clear()
        self.combo_run_queue.addItems(list(self.queues))
        if current in self.queues:
            self.combo_run_queue.setCurrentText(current)
        elif self.active_queue:
            self.combo_run_queue.setCurrentText(self.active_queue)
        self.combo_run_queue.blockSignals(False)
        self.btn_queue_delete.setEnabled(len(self.queues) > 1)
        self._update_run_button()

    def _refresh_queue_list(self):
        self.queue_list.clear()
        for item in self._active_queue_items():
            spec = next((s for s in TASKS if s.key == item["key"]), None)
            title = spec.title if spec else item["key"]
            extra = _fmt_params(item.get("params") or {})
            self.queue_list.addItem(QListWidgetItem(
                f"{title}{'  ' + extra if extra else ''}"))

    def _refresh_card_badges(self):
        for key, card in self.cards.items():
            card.set_queue_count(sum(1 for item in self._active_queue_items()
                                     if item["key"] == key))

    def _active_queue_items(self) -> list[dict]:
        return self.queues.get(self.active_queue, [])

    def _on_queue_selected(self, name: str):
        if self._restoring or name == self.active_queue or name not in self.queues:
            return
        self.active_queue = name
        self._refresh_queue_list()
        self._refresh_card_badges()
        self._save_settings()

    def _new_queue(self):
        name = self.combo_queue.currentText().strip()
        if not name:
            QMessageBox.information(self, "提示", "请先在上拉框输入新队列的名字")
            return
        if name in self.queues:
            QMessageBox.information(self, "提示", f"队列「{name}」已存在")
            return
        self.queues[name] = []
        self.active_queue = name
        self._refresh_queue_panel()
        self._save_settings()
        self._append_log(f"📁 新建队列「{name}」，从任务卡片点「加入队列」添加任务\n")

    def _delete_queue(self):
        if len(self.queues) <= 1:
            QMessageBox.information(self, "提示", "至少保留一个队列")
            return
        name = self.active_queue
        if not name:
            return
        answer = QMessageBox.question(
            self, "确认删除", f"确定删除队列「{name}」吗？绑定它的窗口会一并解绑。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.queues.pop(name, None)
        self.active_queue = next(iter(self.queues), "")
        self.bindings = {hwnd: q for hwnd, q in self.bindings.items() if q != name}
        self._save_bindings()
        self._refresh_queue_panel()
        self._refresh_bindings_column()
        self._append_log(f"🗑 已删除队列「{name}」\n")

    def _on_card_add(self, key: str):
        """卡片「加入队列」：把任务（连同当前参数快照）追加到当前队列末尾"""
        if not self.active_queue:
            QMessageBox.information(self, "提示", "请先选择或新建一个队列")
            return
        params = self.cards[key].get_params()
        self.queues[self.active_queue].append({"key": key, "params": params})
        self._refresh_queue_list()
        self._refresh_card_badges()
        self._update_run_button()
        self._save_settings()
        title = self.cards[key].spec.title
        self._append_log(f"➕ 已把「{title}」加入队列「{self.active_queue}」\n")

    def _move_task(self, delta: int):
        row = self.queue_list.currentRow()
        items = self._active_queue_items()
        if row < 0 or not items:
            return
        target = row + delta
        if not 0 <= target < len(items):
            return
        items[row], items[target] = items[target], items[row]
        self._refresh_queue_list()
        self.queue_list.setCurrentRow(target)
        self._save_settings()

    def _remove_task(self):
        row = self.queue_list.currentRow()
        items = self._active_queue_items()
        if row < 0 or not 0 <= row < len(items):
            return
        removed = items.pop(row)
        self._refresh_queue_list()
        self._refresh_card_badges()
        self._update_run_button()
        self._save_settings()
        spec = next((s for s in TASKS if s.key == removed["key"]), None)
        self._append_log(f"➖ 已从队列移除「{spec.title if spec else removed['key']}」\n")

    def _clear_queue_tasks(self):
        if not self._active_queue_items():
            return
        self.queues[self.active_queue] = []
        self._refresh_queue_list()
        self._refresh_card_badges()
        self._update_run_button()
        self._save_settings()
        self._append_log(f"🧹 已清空队列「{self.active_queue}」\n")

    # ---------- 任务区（卡片 + 窗口表） ----------

    def _build_task_area(self) -> QWidget:
        container = QWidget()
        container.setObjectName("taskContainer")
        outer = QVBoxLayout(container)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.setSpacing(14)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(14)

        for index, spec in enumerate(TASKS):
            card = TaskCard(spec)
            card.add_to_queue.connect(self._on_card_add)
            self.cards[spec.key] = card
            grid.addWidget(card, index // GRID_COLUMNS, index % GRID_COLUMNS)

        outer.addLayout(grid)
        outer.addWidget(self._build_window_table())
        outer.addStretch(1)

        area = QScrollArea()
        area.setObjectName("taskArea")
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(container)
        return area

    def _build_window_table(self) -> QWidget:
        """窗口列表：已连接的游戏窗口（按 hwnd 升序），单选后选队列直接运行"""
        frame = QFrame()
        frame.setObjectName("card")

        title = QLabel("窗口（hwnd）")
        title.setObjectName("cardTitle")

        self.window_label = QLabel("选中一个窗口，选择队列后点「运行」")
        self.window_label.setObjectName("cardDesc")

        self.chk_auto_refresh = QCheckBox("自动刷新")
        self.chk_auto_refresh.setChecked(True)
        self.chk_auto_refresh.setToolTip("空闲时每 5 秒刷新一次窗口列表（任务运行中暂停）")
        self.chk_auto_refresh.toggled.connect(self._on_auto_refresh_toggled)

        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(lambda: self._refresh_window_table(force=True))

        # 运行控件：选中 hwnd -> 选队列 -> 运行
        self.queue_progress = QLabel("")
        self.queue_progress.setObjectName("queueProgress")

        self.combo_run_queue = QComboBox()
        self.combo_run_queue.setToolTip("当前选中窗口要执行的队列")
        self.combo_run_queue.currentTextChanged.connect(lambda _t: self._update_run_button())

        self.btn_run = QPushButton("运行")
        self.btn_run.setProperty("primary", True)
        self.btn_run.setEnabled(False)
        self.btn_run.clicked.connect(self._run_selected)

        self.btn_stop = QPushButton("停止")
        self.btn_stop.setProperty("danger", True)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(lambda: self._on_stop())

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(title)
        head.addWidget(self.window_label, 1)
        head.addWidget(self.queue_progress)
        head.addWidget(QLabel("队列"))
        head.addWidget(self.combo_run_queue)
        head.addWidget(self.chk_auto_refresh)
        head.addWidget(btn_refresh)
        head.addWidget(self.btn_run)
        head.addWidget(self.btn_stop)

        self.window_table = QTableWidget(0, 3)
        self.window_table.setObjectName("windowTable")
        self.window_table.setHorizontalHeaderLabels(("HWND", "绑定队列", "操作"))
        self.window_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.window_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.window_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.window_table.verticalHeader().setVisible(False)
        self.window_table.setFixedHeight(180)
        self.window_table.itemSelectionChanged.connect(self._on_window_selection_changed)

        header = self.window_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        box = QVBoxLayout(frame)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(10)
        box.addLayout(head)
        box.addWidget(self.window_table)
        return frame

    # ---------- 窗口列表 / 绑定 ----------

    def _refresh_window_table(self, force: bool = False):
        """只取已连接的游戏窗口（controller.connected_hwnds），按 hwnd 升序填充。

        force=False 时（自动刷新）窗口集合没变化就不重建表格，也不打日志，避免刷屏。
        """
        # 延迟导入：controller_cv 较重（加载图标等），必须晚于 QApplication 创建
        from shenwu.controller_cv import get_controller

        try:
            controller = get_controller()
            infos = sorted(controller.window_infos(), key=lambda item: item[1])
        except Exception as e:
            self._append_log(f"❌ 获取已连接窗口失败：{e}\n")
            return

        hwnds = [item[1] for item in infos]
        if not force and hwnds == self._listed_hwnds:
            return
        self._listed_hwnds = hwnds

        # 窗口集合变化时：清理失效绑定，按保存的 服务器名->队列 恢复
        self._rebind_from_settings(controller)

        table = self.window_table
        saved_server = self.settings.get("selected_server") or ""
        table.blockSignals(True)
        table.setRowCount(len(infos))
        self._identify_buttons.clear()

        for row, (_, hwnd, _title, server) in enumerate(infos):
            hwnd_item = QTableWidgetItem(str(hwnd))
            hwnd_item.setData(Qt.ItemDataRole.UserRole, hwnd)
            table.setItem(row, 0, hwnd_item)

            table.setItem(row, 1, QTableWidgetItem(self.bindings.get(hwnd, "")))

            # 「定位」按钮：点击给目标窗口挂临时边框标识，再点提前收起
            btn = QPushButton("收起" if hwnd in self._identify_overlays else "定位")
            btn.setToolTip(f"在屏幕上高亮标识 hwnd={hwnd} 对应的窗口（5 秒自动消失）")
            btn.clicked.connect(lambda _=False, h=hwnd: self._identify_hwnd(h))
            table.setCellWidget(row, 2, btn)
            self._identify_buttons[hwnd] = btn

            # 上次保存的服务器名 → 恢复选中行（仅内部使用，不在表格显示）
            if server and server == saved_server:
                table.selectRow(row)

        table.blockSignals(False)
        self.selected_hwnds = self._selected_hwnds()
        self._update_window_label()
        self._update_run_button()
        if self._identify_overlays:
            self._identify_timer.start()
        if force:
            self._append_log(f"🔍 已连接 {len(infos)} 个游戏窗口（按 hwnd 升序）\n")

    def _rebind_from_settings(self, controller):
        """把持久化的 服务器名->队列 解析回 hwnd->队列；清理已失效的绑定"""
        by_server = self.settings.get("bindings") or {}
        resolved = {}
        for hwnd, server in ((hwnd, controller.hwnd_status[hwnd].server)
                             for hwnd in controller.connected_hwnds):
            queue_name = by_server.get(server)
            if queue_name and queue_name in self.queues:
                resolved[hwnd] = queue_name
        self.bindings = resolved

    def _refresh_bindings_column(self):
        table = self.window_table
        table.blockSignals(True)
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is None:
                continue
            hwnd = int(item.data(Qt.ItemDataRole.UserRole))
            bind_item = table.item(row, 1)
            if bind_item is not None:
                bind_item.setText(self.bindings.get(hwnd, ""))
        table.blockSignals(False)

    def _on_auto_refresh_toggled(self, enabled: bool):
        if enabled and not self._is_busy():
            self._auto_refresh_timer.start()
        elif not enabled:
            self._auto_refresh_timer.stop()
        self._save_settings()

    def _auto_refresh_windows(self):
        """空闲时自动刷新；任务运行中不动，避免打断脚本"""
        if self._is_busy() or not self.chk_auto_refresh.isChecked():
            return
        self._refresh_window_table(force=False)

    def _selected_hwnd(self) -> int | None:
        """单选模式：返回当前选中行的 hwnd，未选中返回 None"""
        indexes = self.window_table.selectedIndexes()
        if not indexes:
            return None
        item = self.window_table.item(indexes[0].row(), 0)
        return int(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def _selected_hwnds(self) -> list[int]:
        """兼容覆盖层等需要列表的调用：单选模式下最多一个元素"""
        hwnd = self._selected_hwnd()
        return [hwnd] if hwnd is not None else []

    def _on_window_selection_changed(self):
        self.selected_hwnds = self._selected_hwnds()
        controller = self._active_controller()
        server = ""
        if self.selected_hwnds and controller is not None:
            status = controller.hwnd_status.get(self.selected_hwnds[0])
            server = status.server if status else ""
        self.settings["selected_server"] = server
        self._save_settings()
        self._update_window_label()
        self._update_run_button()

    def _update_window_label(self):
        hwnd = self.selected_hwnds[0] if self.selected_hwnds else None
        if hwnd is None:
            self.window_label.setText("选中一个窗口，选择队列后点「运行」")
            return
        bound_queue = self.bindings.get(hwnd, "未绑定")
        self.window_label.setText(f"hwnd={hwnd} · 绑定队列：{bound_queue}")

    def _run_selected(self):
        """以 hwnd 为核心的执行入口：选中窗口 + 所选队列，点「运行」立即执行"""
        if self._is_busy():
            QMessageBox.information(self, "提示", "已有任务在运行，请先停止后再执行")
            return
        hwnd = self._selected_hwnd()
        if hwnd is None:
            QMessageBox.information(self, "提示", "请先在窗口列表选中一个窗口")
            return
        queue_name = self.combo_run_queue.currentText().strip()
        if queue_name not in self.queues:
            QMessageBox.information(self, "提示", "请先选择一个队列（没有就先在「执行队列」面板新建）")
            return
        tasks = [(item["key"], dict(item.get("params") or {}))
                 for item in self.queues.get(queue_name, [])]
        if not tasks:
            QMessageBox.information(self, "提示",
                                    f"队列「{queue_name}」是空的，先从任务卡片「加入队列」")
            return

        # 运行即绑定：该 hwnd 执行此队列；定时执行与边框显示复用这条绑定
        self.bindings[hwnd] = queue_name
        self._refresh_bindings_column()
        self._save_bindings()

        plan = [(hwnd, queue_name, tasks)]
        self._append_log(f"\n▶ [{_now()}] 开始执行：hwnd={hwnd} → 队列「{queue_name}」×{len(tasks)}\n")
        self._launch(plan)

    def _update_run_button(self):
        """有选中窗口且所选队列非空时，「运行」才可用"""
        busy = self._is_busy()
        hwnd = self._selected_hwnd()
        queue_name = self.combo_run_queue.currentText().strip()
        self.btn_run.setEnabled(
            not busy and hwnd is not None and bool(self.queues.get(queue_name)))

    # ---------- 「定位」按钮：临时高亮标识目标窗口 ----------

    def _identify_hwnd(self, hwnd: int):
        """给目标窗口挂 5 秒自动消失的彩色边框标识；再次点击提前收起

        标识形式：四周 6px 亮黄边框 + 顶部「👉 hwnd=xxx」标签的置顶覆盖层，
        独立于目标窗口进程，被遮挡也能看到。
        - 已失效窗口：IsWindow 检查后提示并刷新列表
        - 最小化窗口：坐标在屏幕外，先自动还原再标识（覆盖层本身在目标
          最小化时也会自动隐藏，双保险）
        - 无响应窗口：覆盖层与定位都只查窗口管理器，不受目标卡死影响
        """
        if not win32gui.IsWindow(hwnd):
            self._append_log(f"❌ hwnd={hwnd} 已失效，无法定位\n")
            self._refresh_window_table(force=True)
            return
        if hwnd in self._identify_overlays:      # 再点一次 = 提前撤掉
            self._close_identify(hwnd)
            return
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            self._append_log(f"⚠️ hwnd={hwnd} 处于最小化，已自动还原后标识\n")

        # 延迟导入：windows_utils 触碰进程 DPI 感知，须晚于 QApplication 创建
        from shenwu.windows_utils import Win32BorderWithLabel

        try:
            overlay = Win32BorderWithLabel(
                hwnd,
                label_text=f"👉 这里 hwnd={hwnd}",
                border_width=6,
                color_rgb=IDENTIFY_COLOR,
            )
        except Exception as e:
            self._append_log(f"❌ 标识失败 hwnd={hwnd}：{e}\n")
            return
        self._identify_overlays[hwnd] = overlay
        self._set_identify_button(hwnd)
        self._identify_timer.start()
        QTimer.singleShot(IDENTIFY_SECONDS * 1000, lambda: self._close_identify(hwnd))
        self._append_log(f"👉 正在标识 hwnd={hwnd}（{IDENTIFY_SECONDS} 秒后自动消失）\n")

    def _close_identify(self, hwnd: int):
        """撤掉指定 hwnd 的标识覆盖层（重复调用安全）"""
        overlay = self._identify_overlays.pop(hwnd, None)
        if overlay is not None:
            try:
                overlay.close()
            except Exception:
                pass
        self._set_identify_button(hwnd)
        if not self._identify_overlays:
            self._identify_timer.stop()

    def _pump_identify(self):
        """驱动所有标识覆盖层跟随目标窗口；目标关闭时自动移除"""
        for hwnd in list(self._identify_overlays):
            overlay = self._identify_overlays.get(hwnd)
            if overlay is None:
                continue
            try:
                alive = overlay.update_position()
            except Exception:
                alive = False
            if not alive:
                self._close_identify(hwnd)

    def _set_identify_button(self, hwnd: int):
        """按钮文字与覆盖层状态保持一致（收起 = 标识正挂着）"""
        btn = self._identify_buttons.get(hwnd)
        if btn is not None:
            btn.setText("收起" if hwnd in self._identify_overlays else "定位")

    def _active_controller(self):
        """拿到已构造好的 controller；还没连接过就返回 None（不触发构造）"""
        try:
            from shenwu.controller_cv import get_controller

            if get_controller.cache_info().currsize == 0:
                return None
            return get_controller()
        except Exception:
            return None

    def _build_log_area(self) -> QWidget:
        label = QLabel("运行日志")
        label.setObjectName("sectionLabel")

        self.chk_auto_scroll = QCheckBox("自动滚动")
        self.chk_auto_scroll.setChecked(True)
        self.chk_auto_scroll.setToolTip(
            "勾选：新日志出现时自动滚动到底部，始终看到最新内容。\n"
            "不勾选：保持你当前的滚动位置不动，方便回看历史日志（新内容仍会写入末尾）。"
        )

        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(self.log_clear)

        btn_export = QPushButton("导出")
        btn_export.setToolTip("把当前日志保存成 txt 文件")
        btn_export.clicked.connect(self.log_export)

        self.log_filter = QLineEdit()
        self.log_filter.setPlaceholderText("过滤关键字…")
        self.log_filter.setFixedWidth(120)
        self.log_filter.textChanged.connect(self._render_log)

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(label)
        head.addStretch(1)
        head.addWidget(self.log_filter)
        head.addWidget(self.chk_auto_scroll)
        head.addWidget(btn_export)
        head.addWidget(btn_clear)

        self.log = QTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setFixedHeight(180)
        self.log.document().setMaximumBlockCount(3000)
        self.log.setFont(QFont("Consolas", 9))

        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        box.addLayout(head)
        box.addWidget(self.log)

        wrapper = QWidget()
        wrapper.setLayout(box)
        return wrapper

    # ---------- 窗口连接 ----------

    def _refresh_windows(self):
        # 延迟导入：controller_cv 较重（加载图标等），必须等 QApplication 创建后再导入
        from shenwu.controller_cv import get_controller

        try:
            controller = get_controller()
            count = controller.refresh_hwnds()
        except Exception as e:
            self._set_pill("err", "未找到游戏窗口")
            self._append_log(f"❌ 连接游戏窗口失败：{e}\n请打开《幻唐志》后点击「连接 / 刷新窗口」\n")
            return

        if count == 0:
            self._set_pill("err", "未找到游戏窗口")
            self._append_log("❌ 未枚举到《幻唐志》游戏窗口\n")
            return

        # 图标列表要等 controller 就绪才有，这里补进诊断卡片的下拉框
        card = self.cards.get("test_resources")
        if card is not None:
            card.set_param_options("icon_name", controller.icon_names())
            saved_icon = (self.settings.get("diagnostic") or {}).get("icon_name")
            if saved_icon:
                card.set_params({"icon_name": saved_icon})

        infos = controller.window_infos()
        self._set_pill("ok", f"已连接 {count} 个窗口 · 缩放 {controller.radio:.2f}")
        self._append_log(f"✅ 已连接 {count} 个游戏窗口，缩放比例 {controller.radio:.2f}\n")
        for index, hwnd, _title, _server in infos:
            self._append_log(f"   {index + 1}. hwnd={hwnd}\n")

    def _set_pill(self, state: str, text: str):
        self.pill.setText(text)
        self.pill.setProperty("state", state)
        _repolish(self.pill)

    # ---------- 执行计划 ----------

    def _is_busy(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _build_plan_items(self) -> list[tuple[int, str, list[tuple[str, dict]]]]:
        """把绑定转成执行计划：[(hwnd, 队列名, [(key, params), ...]), ...]，按 hwnd 升序"""
        plan = []
        for hwnd in sorted(self.bindings):
            queue_name = self.bindings[hwnd]
            tasks = [(item["key"], dict(item.get("params") or {}))
                     for item in self.queues.get(queue_name, [])]
            if tasks:
                plan.append((hwnd, queue_name, tasks))
        return plan

    def _start_plan(self):
        """定时执行的入口：按各窗口已绑定的队列依次执行（手动运行走 _run_selected）"""
        if self._is_busy():
            QMessageBox.information(self, "提示", "已有任务在运行，请先停止后再执行")
            return
        plan = self._build_plan_items()
        if not plan:
            QMessageBox.information(
                self, "提示",
                "还没有可执行的计划：先在窗口面板选中窗口、选好队列点「运行」（运行即绑定）")
            return

        plan_desc = " | ".join(
            f"hwnd={hwnd}→{name}×{len(tasks)}" for hwnd, name, tasks in plan)
        self._append_log(f"\n▶ [{_now()}] 开始执行计划（{len(plan)} 个窗口）：{plan_desc}\n")
        self._launch(plan)

    def _launch(self, plan):
        rounds = self.spin_times.value()
        interval = self.spin_interval.value()

        worker = TaskWorker(plan, self, rounds=rounds, round_interval=interval,
                            continue_on_error=self.chk_continue_on_error.isChecked())
        worker.hwnd_started.connect(self._on_hwnd_started)
        worker.task_started.connect(self._on_task_started)
        worker.task_failed.connect(self._on_task_failed)
        worker.round_started.connect(self._on_round_started)
        worker.done.connect(self._on_done)
        worker.finished.connect(worker.deleteLater)

        self.worker = worker
        self.mode = "plan"
        self._stopping = False
        self._last_error = ""
        self._current_index = -1
        self._current_key = None

        if rounds != 1:
            self._append_log(f"🔁 轮次：{'一直重复' if rounds == 0 else f'{rounds} 轮'}"
                             f"（间隔 {interval}s）\n")

        # 运行期间暂停自动刷新，避免打断脚本
        self._auto_refresh_timer.stop()
        self._update_view(None)
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        worker.start()

    def _on_stop(self, key: str | None = None):
        if not self._is_busy():
            return
        self.worker.request_stop()
        self._stopping = True
        self._update_view(None, stopping=True)
        self.btn_stop.setEnabled(False)
        self.statusBar().showMessage("正在停止…")
        self._append_log(f"⏹ [{_now()}] 已请求停止，等待当前操作结束（剩余任务不再执行）…\n")

    def _on_round_started(self, round_index: int, rounds: int):
        if rounds <= 1:
            return
        text = f"第 {round_index} 轮" + ("" if rounds == 0 else f"/{rounds}")
        self.statusBar().showMessage(f"{text} 开始")
        self._append_log(f"🔁 [{_now()}] {text}开始\n")

    def _on_hwnd_started(self, hwnd: int, queue_name: str):
        self._active_hwnd = hwnd
        self.statusBar().showMessage(f"正在执行：hwnd={hwnd} · 队列「{queue_name}」")
        self._append_log(f"🎯 [{_now()}] 窗口 hwnd={hwnd} 开始执行队列「{queue_name}」\n")

    def _on_task_started(self, index: int, key: str):
        self._current_index = index
        self._current_key = key
        spec = self.cards[key].spec
        # 从计划里取「当前窗口队列」中这个任务的参数
        params = {}
        if self.worker is not None:
            current = [entry for entry in self.worker.plan if entry[0] == self._active_hwnd]
            if current and 0 <= index < len(current[0][2]):
                params = current[0][2][index][1]

        self._active_task = spec.title
        if key == "auto_task" and params.get("task_name"):
            self._update_ocr_history(params["task_name"])

        self._update_view(key)
        extra = _fmt_params(params)
        self.statusBar().showMessage(f"正在执行：{spec.title}")
        self._append_log(f"▶ [{_now()}] ({index + 1}) {spec.title}{'  ' + extra if extra else ''}\n")

    def _on_task_failed(self, index: int, key: str, message: str):
        title = self.cards[key].spec.title
        self._last_error = message
        self._append_log(f"❌ [{_now()}] 任务异常：{title}\n{message}\n")
        if self.chk_continue_on_error.isChecked():
            self._append_log(f"⏭ 出错继续：跳过「{title}」，执行后面的任务\n")
            return
        last_line = message.strip().splitlines()[-1] if message.strip() else "未知错误"
        QMessageBox.warning(self, "任务异常", f"「{title}」执行失败，计划已中断：\n{last_line}")

    def _on_done(self, ok: bool, message: str):
        self.worker = None
        self.mode = None
        self._active_task = ""
        self._active_hwnd = None
        self._update_view(None)
        self._update_run_button()
        self.btn_stop.setEnabled(False)
        self.queue_progress.setText("")
        # 空闲了再恢复自动刷新
        if self.chk_auto_refresh.isChecked():
            self._auto_refresh_timer.start()

        if not ok and message and message != self._last_error:
            self._append_log(f"❌ [{_now()}] 执行失败：\n{message}\n")
            QMessageBox.warning(self, "执行失败", message.strip().splitlines()[-1])
            self.statusBar().showMessage("执行失败，详见日志")
        elif self._stopping:
            self._append_log(f"⏹ [{_now()}] 已停止\n")
            self.statusBar().showMessage("已停止")
        elif ok:
            self._append_log(f"✅ [{_now()}] 计划执行完成\n")
            self.statusBar().showMessage("计划执行完成")
        else:
            self.statusBar().showMessage("任务异常，详见日志")

        self._stopping = False

    def _update_view(self, running_key: str | None, stopping: bool = False):
        """统一刷新卡片状态 + 进度标签"""
        busy = running_key is not None
        for key, card in self.cards.items():
            if key == running_key:
                card.set_state("stopping" if stopping else "running")
            else:
                card.set_locked(busy)

        if busy and self.worker is not None and self._active_hwnd is not None:
            current = [entry for entry in self.worker.plan if entry[0] == self._active_hwnd]
            if current:
                total = len(current[0][2])
                self.queue_progress.setText(f"hwnd={self._active_hwnd} {self._current_index + 1}/{total}")
        elif not busy:
            self.queue_progress.setText("")

    # ---------- 托盘 / 热键 / 定时 ----------

    def _build_tray(self):
        """托盘图标：界面被游戏窗口盖住时也能停止 / 唤出"""
        icon = self.windowIcon()
        self.tray = QSystemTrayIcon(icon if not icon.isNull() else self.style().standardIcon(
            self.style().StandardPixmap.SP_ComputerIcon), self)
        self.tray.setToolTip("幻唐志 · 脚本控制台")

        menu = QMenu()
        act_show = QAction("显示 / 隐藏", self)
        act_show.triggered.connect(self._toggle_visible)
        act_stop = QAction("立即停止任务", self)
        act_stop.triggered.connect(lambda: self._on_stop())
        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self.close)
        menu.addAction(act_show)
        menu.addAction(act_stop)
        menu.addSeparator()
        menu.addAction(act_quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._toggle_visible()
            if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    def _toggle_visible(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def _check_emergency_hotkey(self):
        """Ctrl+Alt+Q 紧急停止：轮询 GetAsyncKeyState，避免动用全局钩子"""
        if not self._is_busy():
            return
        try:
            user32 = ctypes.windll.user32
            pressed = all(user32.GetAsyncKeyState(vk) & 0x8000 for vk in EMERGENCY_MODIFIERS)
            if pressed and user32.GetAsyncKeyState(EMERGENCY_VK) & 0x8000:
                self._append_log("🚨 触发紧急停止热键（Ctrl+Alt+Q）\n")
                self._on_stop()
        except Exception:
            self._hotkey_timer.stop()

    def _apply_schedule_setting(self):
        """按「定时」勾选状态注册 / 注销 schedule 任务"""
        try:
            import schedule
        except Exception:
            if getattr(self, "chk_schedule", None) is not None and self.chk_schedule.isChecked():
                self._append_log("❌ 未安装 schedule，无法使用定时执行\n")
            return

        schedule.clear()
        if not self.chk_schedule.isChecked():
            return

        at = self.time_schedule.time().toString("HH:mm")
        schedule.every().day.at(at).do(self._scheduled_start)
        self._append_log(f"⏰ 已设置每天 {at} 自动执行计划\n")

    def _run_pending_schedule(self):
        if not self.chk_schedule.isChecked():
            return
        try:
            import schedule

            schedule.run_pending()
        except Exception as e:
            self._append_log(f"❌ 定时任务执行失败：{e}\n")

    def _scheduled_start(self):
        if self._is_busy():
            self._append_log("⏰ 到点但计划仍在运行，跳过本次\n")
            return
        if not self._build_plan_items():
            self._append_log("⏰ 到点但没有可执行的计划（先绑定窗口），跳过本次\n")
            return
        self._append_log("⏰ 定时触发，开始执行计划\n")
        self._start_plan()

    # ---------- 日志 ----------

    def log_clear(self):
        self.log.clear()
        self._log_lines.clear()

    def log_export(self):
        """把日志导出成 txt（默认放在项目根目录）"""
        default = f"gui_log_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(self, "导出日志", default, "文本文件 (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fp:
                fp.write("".join(self._log_lines))
            self._append_log(f"💾 日志已导出：{path}\n")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _log_color(self, text: str):
        """按行首标记决定颜色：❌ 红 / ✅ 绿 / ⚠️ 橙 / ▶🎯 蓝"""
        if text.startswith(("❌", "⚠️", "Traceback")):
            return QColor(255, 122, 122) if text.startswith("❌") else QColor(255, 180, 84)
        if text.startswith(("✅", "💾", "🧹")):
            return QColor(92, 214, 140)
        if text.startswith(("▶", "🎯", "🔁", "⏰", "🖍", "🔍", "🔗")):
            return QColor(130, 180, 255)
        return None

    def _render_log(self):
        """过滤条件变化时整屏重绘（平时是增量插入，不重绘）"""
        keyword = self.log_filter.text().strip().lower()
        self.log.blockSignals(True)
        self.log.clear()
        for line in self._log_lines:
            if keyword and keyword not in line.lower():
                continue
            self._insert_line(line)
        self.log.blockSignals(False)
        scroll_bar = self.log.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum() if self.chk_auto_scroll.isChecked() else 0)

    def _insert_line(self, text: str):
        color = self._log_color(text)
        if color is None:
            self.log.insertPlainText(text)
            return
        fmt = QTextCharFormat()
        fmt.setForeground(color)
        cursor = self.log.textCursor()
        cursor.insertText(text, fmt)

    def _append_log(self, text: str):
        if not text:
            return

        # 留一份副本供过滤 / 导出使用
        self._log_lines.append(text)
        if len(self._log_lines) > 3000:
            del self._log_lines[:len(self._log_lines) - 3000]

        keyword = self.log_filter.text().strip().lower()
        if keyword and keyword not in text.lower():
            return

        if self.chk_auto_scroll.isChecked():
            # 自动滚动打开：光标移到末尾，并把滚动条直接拉到最底部
            # （ensureCursorVisible 只保证光标可见，末尾有空行时不会真正贴底）
            self.log.moveCursor(QTextCursor.MoveOperation.End)
            self.log.insertPlainText(text)
            scroll_bar = self.log.verticalScrollBar()
            scroll_bar.setValue(scroll_bar.maximum())
            return

        # 自动滚动关闭：只在末尾插入文本，插完把滚动条还原到用户原来的位置。
        # 注意不能 moveCursor(End) 后再插入 —— moveCursor 会把视口一起滚到底部。
        scroll_bar = self.log.verticalScrollBar()
        position = scroll_bar.value()

        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log.setTextCursor(cursor)
        self.log.insertPlainText(text)

        scroll_bar.setValue(position)

    # ---------- 退出 ----------

    def closeEvent(self, event):
        if self._is_busy():
            answer = QMessageBox.question(
                self, "确认退出", "任务正在运行，确定要停止并退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.worker.request_stop()
            self.worker.wait(10000)
        for hwnd in list(self._identify_overlays):
            self._close_identify(hwnd)
        self._save_settings()
        if getattr(self, "tray", None) is not None:
            self.tray.hide()
        event.accept()


def _now() -> str:
    return time.strftime("%H:%M:%S")


def _parse_time(text: str):
    """'HH:mm' -> QTime，解析失败回退 12:00"""
    from PyQt6.QtCore import QTime

    try:
        hour, minute = str(text).split(":")[:2]
        return QTime(int(hour), int(minute))
    except Exception:
        return QTime(12, 0)


def _fmt_params(params: dict | None) -> str:
    if not params:
        return ""
    return "  ".join(f"{k}={v}" for k, v in params.items() if v not in ("", False))


def run_gui():
    """GUI 入口（main.py 的 gui 命令调用）

    注意：这里不要再调 SetProcessDpiAwareness —— Qt6 创建 QApplication 时会自己把进程
    设成 PER_MONITOR_AWARE_V2（比脚本里用的 v1 更完整），而 Windows 一个进程只允许
    设置一次，提前设置会让 Qt 失败并打印「SetProcessDpiAwarenessContext() failed」。
    controller_cv 的导入也因此全部延后到 QApplication 创建之后。
    """
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setStyleSheet(QSS)
    app.setApplicationName("幻唐志 · 脚本控制台")

    # 给进程一个独立的 AppUserModelID，否则 Windows 会把任务栏图标归到 python.exe 名下
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("shenwu.ScriptConsole")
    except Exception:
        pass

    # 标题栏 + 任务栏图标（Pillow 现画，见 shenwu/gui/app_icon.py）
    # 延迟导入：app_icon 会带进 Pillow，没必要在 import shenwu.gui 时就付这个代价
    from shenwu.gui.app_icon import build_app_icon

    app_icon = build_app_icon()
    app.setWindowIcon(app_icon)

    window = MainWindow()
    window.setWindowIcon(app_icon)
    # 托盘是在 MainWindow 里建的，那时还没有图标，这里补上
    if getattr(window, "tray", None) is not None:
        window.tray.setIcon(app_icon)

    # 业务代码的 print / traceback 直接进日志面板（跨线程 emit 是安全的）
    tee = _LogTee(window.log_text.emit, sys.stdout)
    sys.stdout = tee
    sys.stderr = tee

    window.show()
    app.exec()
