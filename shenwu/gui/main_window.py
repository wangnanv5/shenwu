"""PyQt 主窗口：以 hwnd 为核心的自动化控制台。

执行流程：在窗口列表选中一个 hwnd -> 在窗口面板选择要执行的队列 -> 点「运行」。
- 队列在「执行队列」面板里自定义（增删任务、排序、新建/删除队列），本地持久化；
- 运行即把该 hwnd 绑定到所选队列（按服务器名持久化），供定时执行与边框显示复用；
- 「定时」到点后按各窗口已绑定的队列依次执行（鼠标键盘独占，只能串行）。

任务卡片只负责「编辑参数 + 加入队列」，没有单独的启停按钮。
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time

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
    QInputDialog,
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
    QSpinBox,
    QSplitter,
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
from shenwu.gui.tasks import TASKS, TaskCard
from shenwu.gui.theme import QSS, repolish
from shenwu.gui.workers import RowWorker

# 「定位」标识：边框颜色与自动消失时长
IDENTIFY_COLOR = (255, 200, 0)
IDENTIFY_SECONDS = 5

GRID_COLUMNS = 2  # 任务卡片固定两列

# 紧急停止热键：Ctrl + Alt + Q（脚本运行时游戏窗口会盖住界面，用它兜底）
EMERGENCY_MODIFIERS = (0x11, 0x12)  # VK_CONTROL / VK_MENU(Alt)
EMERGENCY_VK = 0x51  # Q

DEFAULT_QUEUE_NAME = "默认队列"


class _LogTee:
    """把 print / traceback 同时送到界面日志和原始终端。

    业务代码是分多次 write 的（print 的正文和换行各一次），所以这里按行缓冲，
    凑满一行再加时间戳发出去，保证每行日志都有 [时:分:秒] 前缀。
    """

    def __init__(self, emit, original):
        self._emit = emit
        self._original = original
        self._buffer = ""
        self._lock = threading.Lock()  # 多个 RowWorker 同时 print 时保护行缓冲
        self.encoding = "utf-8"
        self.errors = "replace"

    def write(self, text):
        try:
            self._original.write(text)
        except Exception:
            pass

        if not text:
            return len(text or "")

        # 攒行过程持锁，emit 放到锁外，避免持锁期间触发 Qt 排队投递
        lines = []
        with self._lock:
            self._buffer += text
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                if line.strip():
                    lines.append(f"[{time.strftime('%H:%M:%S')}] {line}\n")
        for line in lines:
            self._emit(line)
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
    # 窗口队列线程结束时由线程内发出（跨线程 queued 投递，安全）
    row_finished = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.cards: dict[str, TaskCard] = {}
        # 运行中的窗口队列线程：hwnd -> {"worker": RowWorker, "queue": str}
        self._row_workers: dict[int, dict] = {}

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

        # 每行的行内控件（表格重建时同步重建）
        self._row_combos: dict[int, QComboBox] = {}
        self._row_run_buttons: dict[int, QPushButton] = {}
        self._row_stop_buttons: dict[int, QPushButton] = {}

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
        self.row_finished.connect(self._on_row_finished)

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

            self.chk_auto_scroll.setChecked(bool(conf.get("auto_scroll", True)))
            self.chk_auto_refresh.setChecked(bool(conf.get("auto_refresh", True)))

            loop = conf.get("loop") or {}
            self.spin_times.setValue(int(loop.get("times", 1)))
            self.spin_interval.setValue(int(loop.get("interval", 30)))
            self.chk_continue_on_error.setChecked(bool(loop.get("continue_on_error", False)))

            plan = conf.get("schedule") or {}
            self.chk_schedule.setChecked(bool(plan.get("enabled", False)))
            self.time_schedule.setTime(_parse_time(str(plan.get("time", "12:00"))))
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

        layout = QHBoxLayout()
        layout.setSpacing(12)
        layout.addLayout(texts)
        layout.addStretch(1)
        layout.addWidget(self.pill)
        layout.addWidget(self.btn_refresh)

        header = QWidget()
        header.setLayout(layout)
        self._header = header

    def _build_body(self):
        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(14)
        outer.addWidget(self._header)
        outer.addWidget(self._build_queue_task_split(), 1)
        outer.addWidget(self._build_window_table())
        outer.addWidget(self._build_log_area())
        self.setCentralWidget(root)

    # ---------- 队列与任务分栏 ----------

    def _build_queue_task_split(self) -> QWidget:
        """左右分栏：左=队列管理（高优先级、占宽），右=任务卡片（压缩、低优先级）"""
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_queue_panel())
        splitter.addWidget(self._build_task_area())
        # 左侧队列面板优先：额外空间全给左栏，右栏固定在初始宽度不再增长
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([520, 480])
        return splitter

    def _build_queue_panel(self) -> QWidget:
        """左侧队列管理区：队列增删改名 + 任务列表（纵向滚动）+ 顺序调整 + 轮次控制"""
        panel = QFrame()
        panel.setObjectName("queueBar")
        # 最小宽度保证「轮次/间隔/出错继续/定时」一行完整显示，不被挤压截断
        panel.setMinimumWidth(430)

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
        self.btn_queue_rename = QPushButton("重命名")
        self.btn_queue_rename.clicked.connect(self._rename_queue)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(label)
        head.addWidget(self.combo_queue, 1)
        head.addWidget(self.btn_queue_new)
        head.addWidget(self.btn_queue_rename)
        head.addWidget(self.btn_queue_delete)

        # 队列内容：纵向占满面板剩余高度，任务多时自动出滚动条
        self.queue_list = QListWidget()
        self.queue_list.setObjectName("queueList")
        self.queue_list.setToolTip("当前队列的任务顺序；选中后可上移 / 下移 / 移除")

        self.btn_task_up = QPushButton("上移")
        self.btn_task_up.clicked.connect(lambda: self._move_task(-1))
        self.btn_task_down = QPushButton("下移")
        self.btn_task_down.clicked.connect(lambda: self._move_task(1))
        self.btn_task_remove = QPushButton("移除")
        self.btn_task_remove.clicked.connect(self._remove_task)
        self.btn_queue_clear = QPushButton("清空")
        self.btn_queue_clear.clicked.connect(self._clear_queue_tasks)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self.btn_task_up)
        actions.addWidget(self.btn_task_down)
        actions.addWidget(self.btn_task_remove)
        actions.addStretch(1)
        actions.addWidget(self.btn_queue_clear)

        box = QVBoxLayout(panel)
        box.setContentsMargins(14, 10, 14, 10)
        box.setSpacing(8)
        box.addLayout(head)
        box.addWidget(self.queue_list, 1)
        box.addLayout(actions)
        box.addLayout(self._build_loop_controls())
        return panel

    def _rename_queue(self):
        """重命名当前队列：保持原顺序，同步绑定关系与持久化"""
        old = self.active_queue
        if not old or old not in self.queues:
            QMessageBox.information(self, "提示", "请先选择要重命名的队列")
            return
        new, ok = QInputDialog.getText(self, "重命名队列", "新名字:", text=old)
        new = (new or "").strip()
        if not ok or not new or new == old:
            return
        if new in self.queues:
            QMessageBox.information(self, "提示", f"队列「{new}」已存在")
            return
        # 字典按插入序重建，重命名后保持队列排列顺序不变
        self.queues = {(new if name == old else name): items
                       for name, items in self.queues.items()}
        self.active_queue = new
        self.bindings = {hwnd: (new if queue == old else queue)
                         for hwnd, queue in self.bindings.items()}
        self._save_bindings()
        self._refresh_queue_panel()
        self._append_log(f"✏️ 队列「{old}」已重命名为「{new}」\n")

    def _build_loop_controls(self) -> QVBoxLayout:
        """轮次 / 间隔 / 出错继续 / 定时执行（两行排布，每行顶格面板全宽，不截断）"""
        box = QVBoxLayout()
        box.setSpacing(6)

        # 第一行：轮次 + 间隔
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        self.spin_times = QSpinBox()
        self.spin_times.setRange(0, 999)
        self.spin_times.setValue(1)
        self.spin_times.setToolTip("整个计划执行的轮次：1 = 跑一遍；0 = 一直重复，直到手动停止")
        self.spin_times.valueChanged.connect(self._save_settings)

        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(0, 3600)
        self.spin_interval.setValue(30)
        self.spin_interval.setMinimumWidth(80)
        self.spin_interval.setSuffix("s")
        self.spin_interval.setToolTip("每轮结束后的等待秒数（可被停止打断）")
        self.spin_interval.valueChanged.connect(self._save_settings)

        row1.addWidget(QLabel("轮次"))
        row1.addWidget(self.spin_times)
        row1.addWidget(QLabel("间隔"))
        row1.addWidget(self.spin_interval)
        row1.addStretch(1)

        # 第二行：出错继续 + 定时
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        self.chk_continue_on_error = QCheckBox("出错继续")
        self.chk_continue_on_error.setToolTip("某个任务报错时跳过它，继续执行后面的任务")
        self.chk_continue_on_error.toggled.connect(self._save_settings)

        self.chk_schedule = QCheckBox("定时")
        self.chk_schedule.setToolTip("到点自动执行已绑定的计划（界面需保持开启）")
        self.chk_schedule.toggled.connect(self._apply_schedule_setting)

        self.time_schedule = QTimeEdit()
        self.time_schedule.setDisplayFormat("HH:mm")
        self.time_schedule.timeChanged.connect(lambda _t: self._apply_schedule_setting())

        row2.addWidget(self.chk_continue_on_error)
        row2.addWidget(self.chk_schedule)
        row2.addWidget(self.time_schedule)
        row2.addStretch(1)

        box.addLayout(row1)
        box.addLayout(row2)
        return box

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
        # 同步各行「绑定队列」下拉框的选项（保持当前选择不变）
        for hwnd, combo in self._row_combos.items():
            current = self.bindings.get(hwnd, combo.currentText())
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(list(self.queues))
            if current in self.queues:
                combo.setCurrentText(current)
            combo.blockSignals(False)
        self.btn_queue_delete.setEnabled(len(self.queues) > 1)

    def _refresh_queue_list(self):
        self.queue_list.clear()
        for item in self._active_queue_items():
            spec = next((s for s in TASKS if s.key == item["key"]), None)
            title = spec.title if spec else item["key"]
            extra = _fmt_params(item.get("params") or {})
            self.queue_list.addItem(QListWidgetItem(
                f"{title}{'  ' + extra if extra else ''}"))

    def _active_queue_items(self) -> list[dict]:
        return self.queues.get(self.active_queue, [])

    def _on_queue_selected(self, name: str):
        if self._restoring or name == self.active_queue or name not in self.queues:
            return
        self.active_queue = name
        self._refresh_queue_list()
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
        self._save_settings()
        spec = next((s for s in TASKS if s.key == removed["key"]), None)
        self._append_log(f"➖ 已从队列移除「{spec.title if spec else removed['key']}」\n")

    def _clear_queue_tasks(self):
        if not self._active_queue_items():
            return
        self.queues[self.active_queue] = []
        self._refresh_queue_list()
        self._save_settings()
        self._append_log(f"🧹 已清空队列「{self.active_queue}」\n")

    # ---------- 任务区（卡片 + 窗口表） ----------

    def _build_task_area(self) -> QWidget:
        container = QWidget()
        container.setObjectName("taskContainer")
        outer = QVBoxLayout(container)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.setSpacing(10)

        label = QLabel("任务")
        label.setObjectName("sectionLabel")
        outer.addWidget(label)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)

        self._cards_grid = grid
        for index, spec in enumerate(TASKS):
            card = TaskCard(spec)
            card.add_to_queue.connect(self._on_card_add)
            self.cards[spec.key] = card
            grid.addWidget(card, index // GRID_COLUMNS, index % GRID_COLUMNS)

        outer.addLayout(grid)
        outer.addStretch(1)

        # 右侧任务区独立滚动：任务多时纵向滚动查看，不影响左侧队列
        self._task_scroll = QScrollArea()
        self._task_scroll.setObjectName("taskArea")
        self._task_scroll.setWidgetResizable(True)
        self._task_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._task_scroll.setWidget(container)
        return self._task_scroll

    def _build_window_table(self) -> QWidget:
        """窗口列表：每行 = hwnd + 该行的绑定队列下拉框 + 运行/停止按钮"""
        frame = QFrame()
        frame.setObjectName("card")

        title = QLabel("窗口（hwnd）")
        title.setObjectName("cardTitle")

        self.window_label = QLabel("每行选择绑定队列后点「运行」，可多行同时运行")
        self.window_label.setObjectName("cardDesc")

        self.chk_auto_refresh = QCheckBox("自动刷新")
        self.chk_auto_refresh.setChecked(True)
        self.chk_auto_refresh.setToolTip("空闲时每 5 秒刷新一次窗口列表（任务运行中暂停）")
        self.chk_auto_refresh.toggled.connect(self._on_auto_refresh_toggled)

        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(lambda: self._refresh_window_table(force=True))

        self.queue_progress = QLabel("")
        self.queue_progress.setObjectName("queueProgress")

        self.btn_stop_all = QPushButton("全部停止")
        self.btn_stop_all.setProperty("danger", True)
        self.btn_stop_all.setEnabled(False)
        self.btn_stop_all.setToolTip("立即终止所有运行中的窗口")
        self.btn_stop_all.clicked.connect(lambda: self._on_stop())

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(title)
        head.addWidget(self.window_label, 1)
        head.addWidget(self.queue_progress)
        head.addWidget(self.chk_auto_refresh)
        head.addWidget(btn_refresh)
        head.addWidget(self.btn_stop_all)

        self.window_table = QTableWidget(0, 3)
        self.window_table.setObjectName("windowTable")
        self.window_table.setHorizontalHeaderLabels(("HWND", "绑定队列", "操作"))
        self.window_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.window_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.window_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.window_table.verticalHeader().setVisible(False)
        # 行高基准：默认行高小于嵌入按钮的 sizeHint（DPI 缩放下更明显），
        # 按钮会被竖直压瘪；显式抬高行高下限并让行随内容自适应
        self.window_table.verticalHeader().setDefaultSectionSize(36)
        self.window_table.verticalHeader().setMinimumSectionSize(32)
        self.window_table.setFixedHeight(180)
        self.window_table.itemSelectionChanged.connect(self._on_window_selection_changed)

        header = self.window_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        # 「操作」列固定宽度：ResizeToContents 按单元格文本算宽，嵌入的按钮
        # 控件不参与计算，空间不足时列会被压到按钮不可见；固定宽度杜绝挤压
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.window_table.setColumnWidth(2, 208)

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
        self._row_combos.clear()
        self._row_run_buttons.clear()
        self._row_stop_buttons.clear()

        for row, (_, hwnd, _title, server) in enumerate(infos):
            hwnd_item = QTableWidgetItem(str(hwnd))
            hwnd_item.setData(Qt.ItemDataRole.UserRole, hwnd)
            table.setItem(row, 0, hwnd_item)

            # 「绑定队列」下拉框：选择即绑定该行窗口（写入 bindings 并持久化）
            combo = QComboBox()
            combo.addItems(list(self.queues))
            bound = self.bindings.get(hwnd, "")
            if bound in self.queues:
                combo.setCurrentText(bound)
            combo.setFixedHeight(28)
            combo.currentTextChanged.connect(
                lambda text, h=hwnd: self._on_row_queue_changed(h, text))
            table.setCellWidget(row, 1, combo)
            self._row_combos[hwnd] = combo

            # 「操作」列：定位 | 运行 | 停止（停止仅在该行运行中可用）
            # 统一定高 28px + 容器上下边距对称 4px：36px 行高内垂直居中，
            # 且 28 > 按钮内容所需（12px 字 + 3px×2 紧凑内边距 + 描边 ≈ 20px），
            # 任何 DPI 缩放下汉字都完整不变形
            btn_identify = QPushButton("收起" if hwnd in self._identify_overlays else "定位")
            btn_identify.setToolTip(f"在屏幕上高亮标识 hwnd={hwnd} 对应的窗口（5 秒自动消失）")
            btn_identify.setFixedHeight(28)
            btn_identify.clicked.connect(lambda _=False, h=hwnd: self._identify_hwnd(h))

            running = hwnd in self._row_workers
            btn_run = QPushButton("运行中" if running else "运行")
            btn_run.setProperty("primary", True)
            btn_run.setFixedHeight(28)
            btn_run.setEnabled(not running)
            btn_run.clicked.connect(lambda _=False, h=hwnd: self._run_row(h))

            btn_stop = QPushButton("停止")
            btn_stop.setFixedHeight(28)
            btn_stop.setEnabled(running)
            btn_stop.clicked.connect(lambda _=False, h=hwnd: self._stop_row(h))

            ops = QWidget()
            ops_layout = QHBoxLayout(ops)
            ops_layout.setContentsMargins(4, 4, 4, 4)
            ops_layout.setSpacing(4)
            for b in (btn_identify, btn_run, btn_stop):
                ops_layout.addWidget(b)
            table.setCellWidget(row, 2, ops)
            self._identify_buttons[hwnd] = btn_identify
            self._row_run_buttons[hwnd] = btn_run
            self._row_stop_buttons[hwnd] = btn_stop

            # 上次保存的服务器名 → 恢复选中行（仅内部使用，不在表格显示）
            if server and server == saved_server:
                table.selectRow(row)

        # 行高随内容（含嵌入按钮容器）自适应，杜绝竖直挤压
        table.resizeRowsToContents()
        table.blockSignals(False)
        self.selected_hwnds = self._selected_hwnds()
        self._update_window_label()
        self._update_queue_progress()
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
        """绑定变化时同步各行的队列下拉框（不动选择与运行状态）"""
        for hwnd, combo in self._row_combos.items():
            bound = self.bindings.get(hwnd, "")
            if bound in self.queues and combo.currentText() != bound:
                combo.blockSignals(True)
                combo.setCurrentText(bound)
                combo.blockSignals(False)

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

    def _update_window_label(self):
        hwnd = self.selected_hwnds[0] if self.selected_hwnds else None
        if hwnd is None:
            self.window_label.setText("选中一个窗口，选择队列后点「运行」")
            return
        bound_queue = self.bindings.get(hwnd, "未绑定")
        self.window_label.setText(f"hwnd={hwnd} · 绑定队列：{bound_queue}")

    # ---------- 行级执行：每行独立线程，多行可同时运行 ----------

    def _on_row_queue_changed(self, hwnd: int, text: str):
        """行内下拉框选择队列 = 绑定该窗口（写入 bindings 并持久化）"""
        if self._restoring:
            return
        text = (text or "").strip()
        if text and text in self.queues:
            self.bindings[hwnd] = text
            self._save_bindings()

    def _run_row(self, hwnd: int):
        """运行某一行：该 hwnd 按其绑定的队列起独立线程，与其他行互不干扰"""
        if hwnd in self._row_workers:
            return
        combo = self._row_combos.get(hwnd)
        queue_name = combo.currentText().strip() if combo is not None \
            else self.bindings.get(hwnd, "")
        if queue_name not in self.queues:
            QMessageBox.information(self, "提示",
                                    f"hwnd={hwnd} 还没有选择队列，先在「绑定队列」下拉框选择")
            return
        tasks = [(item["key"], dict(item.get("params") or {}))
                 for item in self.queues.get(queue_name, [])]
        if not tasks:
            QMessageBox.information(self, "提示",
                                    f"队列「{queue_name}」是空的，先从任务卡片「加入队列」")
            return

        self.bindings[hwnd] = queue_name
        self._save_bindings()
        self._start_row_worker(hwnd, queue_name, tasks)

    def _start_row_worker(self, hwnd: int, queue_name: str, tasks):
        """为 hwnd 启动一条队列执行线程（已在线程中则忽略）"""
        if hwnd in self._row_workers:
            return
        from shenwu.controller_cv import get_controller

        controller = get_controller()
        worker = RowWorker(controller, hwnd, queue_name, tasks,
                           rounds=self.spin_times.value(),
                           round_interval=self.spin_interval.value(),
                           on_finished=self.row_finished.emit)
        self._row_workers[hwnd] = {"worker": worker, "queue": queue_name}
        self._set_row_buttons(hwnd)
        self._update_queue_progress()
        # 运行期间暂停自动刷新，避免重建行干扰运行状态显示
        self._auto_refresh_timer.stop()
        worker.start()
        self._append_log(
            f"▶ [{_now()}] hwnd={hwnd} 开始执行队列「{queue_name}」×{len(tasks)}\n")

    def _stop_row(self, hwnd: int):
        """立即停止单行：打断当前任务（行级 human_delay 立即抛 TaskTerminated）"""
        entry = self._row_workers.get(hwnd)
        if entry is None:
            return
        entry["worker"].request_stop()
        self._append_log(f"⏹ [{_now()}] hwnd={hwnd} 正在停止（打断当前操作）…\n")

    def _stop_all_rows(self, immediate: bool = False):
        """停止全部运行中的行；immediate=True 时同时置全局终止信号立即打断"""
        if not self._row_workers:
            return
        for entry in self._row_workers.values():
            entry["worker"].request_stop()
        if immediate:
            from shenwu.timing import request_terminate

            request_terminate()
        self._append_log(
            f"⏹ [{_now()}] 已请求停止全部运行中的窗口（{len(self._row_workers)} 个）\n")

    def _on_row_finished(self, hwnd: int):
        """行线程结束（跨线程信号）：恢复按钮状态与自动刷新

        只有线程真正退出（任务实际已终止）才会走到这里，界面状态以此为准。
        """
        entry = self._row_workers.pop(hwnd, None)
        queue_name = entry["queue"] if entry else ""
        stopped = entry is not None and entry["worker"].stop_event.is_set()
        self._set_row_buttons(hwnd)
        self._update_queue_progress()
        if stopped:
            self._append_log(f"⏹ [{_now()}] hwnd={hwnd} 队列「{queue_name}」已停止\n")
        else:
            self._append_log(f"✅ [{_now()}] hwnd={hwnd} 队列「{queue_name}」执行结束\n")
        if not self._row_workers:
            self.statusBar().clearMessage()  # 「正在停止…」在此刻真相大白
            if self.chk_auto_refresh.isChecked():
                self._auto_refresh_timer.start()

    def _set_row_buttons(self, hwnd: int):
        """行按钮状态与运行状态保持一致：运行中 → 运行禁用/停止可用"""
        running = hwnd in self._row_workers
        run_btn = self._row_run_buttons.get(hwnd)
        stop_btn = self._row_stop_buttons.get(hwnd)
        if run_btn is not None:
            run_btn.setText("运行中" if running else "运行")
            run_btn.setEnabled(not running)
        if stop_btn is not None:
            stop_btn.setEnabled(running)

    def _update_queue_progress(self):
        count = len(self._row_workers)
        self.queue_progress.setText(f"运行中 {count}" if count else "")
        self.btn_stop_all.setEnabled(count > 0)

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

        infos = controller.window_infos()
        self._set_pill("ok", f"已连接 {count} 个窗口 · 缩放 {controller.radio:.2f}")
        self._append_log(f"✅ 已连接 {count} 个游戏窗口，缩放比例 {controller.radio:.2f}\n")
        for index, hwnd, _title, _server in infos:
            self._append_log(f"   {index + 1}. hwnd={hwnd}\n")

    def _set_pill(self, state: str, text: str):
        self.pill.setText(text)
        self.pill.setProperty("state", state)
        repolish(self.pill)

    # ---------- 执行（每行独立线程，可并行） ----------

    def _is_busy(self) -> bool:
        return bool(self._row_workers)

    def _on_stop(self, key: str | None = None):
        """立即停止全部运行中的窗口（托盘 / Ctrl+Alt+Q 紧急停止入口）"""
        if not self._is_busy():
            return
        self._stop_all_rows(immediate=True)
        self.statusBar().showMessage("正在停止…")
        self._append_log(f"⏹ [{_now()}] 正在立即停止（打断当前操作，剩余任务不再执行）…\n")

    def _scheduled_start(self):
        """定时触发：为所有已绑定且队列非空的窗口各起一条线程并行执行"""
        if self._is_busy():
            self._append_log("⏰ 到点但仍有窗口在运行，跳过本次\n")
            return
        started = 0
        for hwnd, queue_name in self.bindings.items():
            tasks = [(item["key"], dict(item.get("params") or {}))
                     for item in self.queues.get(queue_name, [])]
            if not tasks:
                continue
            self._start_row_worker(hwnd, queue_name, tasks)
            started += 1
        if started:
            self._append_log(f"⏰ 定时触发，{started} 个窗口开始并行执行\n")
        else:
            self._append_log("⏰ 到点但没有可执行的计划（先在行内选好绑定队列），跳过本次\n")

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
            for entry in self._row_workers.values():
                entry["worker"].request_stop()
            for entry in self._row_workers.values():
                entry["worker"].join(5)
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
