"""GUI 深色主题设计系统（QSS）。

配色令牌（全局统一，改色只动这里）：
    bg        #0b0f17   最底层背景
    surface   #121826   面板/卡片
    surface-2 #182031   输入框、表格、日志底
    surface-3 #1f2940   悬停态
    border    #232c40   常规描边 / border-strong #2e3a55
    text      #eef2fb   主文字 / text-2 #9aa4bd 次级 / text-3 #6b7691 弱化
    accent    #5b8cff   主色（悬停 #6f9bff，按下 #4a7af0）
    gradient  #6a5cff → #4f8cff  主按钮渐变（靛→蓝）
    success   #3ddc97 / danger #ff6b6b / warning #ffb454

字体层级：标题 18px/700 · 卡片题 14px/600 · 区块题 12px/600 加字距 ·
          正文 12px · 提示 11px · 日志 Consolas 12px
间距体系：4 的倍数（面板 16，卡片 10~12，行距 6~8）

状态通过动态属性切换：
- QLabel#pill[state]  : idle / ok / err / run
- QFrame#card[state]  : idle / running / stopping，locked="true" 表示被其它任务占用
"""

from PyQt6.QtWidgets import QWidget

QSS = """
/* ---------- 全局 ---------- */
QWidget#root {
    background: #0b0f17;
}

QScrollArea#taskArea, QWidget#taskContainer {
    background: transparent;
    border: none;
}

QToolTip {
    background: #1f2940;
    color: #eef2fb;
    border: 1px solid #2e3a55;
    border-radius: 6px;
    padding: 6px 9px;
    font-size: 12px;
}

/* ---------- 顶部标题区 ---------- */
QLabel#appTitle {
    font-size: 18px;
    font-weight: 700;
    letter-spacing: 1px;
    color: #eef2fb;
}
QLabel#appSub {
    font-size: 12px;
    color: #9aa4bd;
}

QLabel#pill {
    padding: 5px 14px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    background: #182031;
    color: #9aa4bd;
    border: 1px solid #2e3a55;
}
QLabel#pill[state="ok"] {
    background: #10281e;
    color: #3ddc97;
    border: 1px solid #1e5b41;
}
QLabel#pill[state="err"] {
    background: #2b1518;
    color: #ff8a8a;
    border: 1px solid #5f2a2f;
}
QLabel#pill[state="run"] {
    background: #14243d;
    color: #6ba8ff;
    border: 1px solid #2c518a;
}

/* ---------- 面板与卡片 ---------- */
/* 队列面板保持精致；任务卡片走极简风：方角、纯平、无悬停装饰 */
QFrame#queueBar {
    background: #121826;
    border: 1px solid #232c40;
    border-radius: 14px;
}

/* 顶部卡密验证条：输入框 + 验证按钮 + 结果状态 */
QFrame#licenseBar {
    background: #121826;
    border: 1px solid #232c40;
    border-radius: 10px;
}
QLabel#licenseState {
    font-size: 12px;
    color: #9aa4bd;
}
QLabel#licenseState[state="ok"] {
    color: #3ddc97;
}
QLabel#licenseState[state="err"] {
    color: #ff6b6b;
}
QLabel#licenseState[state="busy"] {
    color: #ffb454;
}
QFrame#card {
    background: #10151f;
    border: 1px solid #1f2739;
    border-radius: 4px;
}
QFrame#card[state="running"] {
    border: 1px solid #5b8cff;
}
QFrame#card[state="stopping"] {
    border: 1px solid #ffb454;
}
QFrame#card[locked="true"] {
    background: #0e1219;
}

QLabel#cardTitle {
    font-size: 14px;
    font-weight: 600;
    color: #eef2fb;
}
QLabel#cardTip {
    font-size: 11px;
    color: #6b7691;
}
QLabel#paramLabel {
    font-size: 12px;
    color: #9aa4bd;
}
QLabel#sectionLabel {
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 1px;
    color: #9aa4bd;
}

QLabel#queueProgress {
    font-size: 12px;
    font-weight: 600;
    color: #6ba8ff;
}

/* ---------- 按钮（含悬停/按下/聚焦/禁用全状态） ---------- */
QPushButton {
    background: #1c2434;
    border: 1px solid #2e3a55;
    border-radius: 8px;
    padding: 6px 16px;
    font-size: 12px;
    color: #e6ebf5;
}
QPushButton:hover {
    background: #232d42;
    border-color: #3d4b6b;
}
QPushButton:pressed {
    background: #182031;
}
QPushButton:focus {
    border: 1px solid #5b8cff;
}
QPushButton:disabled {
    background: #141a26;
    border: 1px solid #202839;
    color: #5c6478;
}

QPushButton[primary="true"] {
    background: #4a6ef5;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    color: #ffffff;
    font-size: 12px;
    font-weight: 600;
}
QPushButton[primary="true"]:hover {
    background: #5b7ff7;
}
QPushButton[primary="true"]:pressed {
    background: #3f5fd9;
}
QPushButton[primary="true"]:focus {
    border: 1px solid #9db4ff;
}
QPushButton[primary="true"]:disabled {
    background: #1c2434;
    color: #5c6478;
}

QPushButton[danger="true"] {
    background: #2b1518;
    border: 1px solid #5f2a2f;
    color: #ff9a9a;
    font-weight: 600;
}
QPushButton[danger="true"]:hover {
    background: #3a1b20;
    border-color: #83353c;
    color: #ffb3b3;
}
QPushButton[danger="true"]:pressed {
    background: #241114;
}
QPushButton[danger="true"]:disabled {
    background: #171a22;
    border: 1px solid #232836;
    color: #5c6478;
}

/* ---------- 输入组件（悬停/聚焦/禁用态） ---------- */
QComboBox, QLineEdit, QSpinBox, QTimeEdit {
    background: #101724;
    border: 1px solid #26314a;
    border-radius: 8px;
    padding: 5px 9px;
    font-size: 12px;
    color: #e2e8f4;
    selection-background-color: #2c518a;
}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QTimeEdit:hover {
    border: 1px solid #33405e;
}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QTimeEdit:focus {
    border: 1px solid #5b8cff;
    background: #121a2b;
}
QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled {
    background: #12161f;
    color: #5c6478;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background: #161d2b;
    color: #e2e8f4;
    border: 1px solid #2e3a55;
    border-radius: 8px;
    selection-background-color: #2c518a;
    outline: none;
}

QCheckBox {
    font-size: 12px;
    color: #c6cede;
    spacing: 6px;
}
QCheckBox:hover {
    color: #eef2fb;
}
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border-radius: 4px;
    border: 1px solid #3a4560;
    background: #101724;
}
QCheckBox::indicator:hover {
    border: 1px solid #5b8cff;
}
QCheckBox::indicator:checked {
    background: #5b8cff;
    border: 1px solid #5b8cff;
}
QCheckBox:disabled {
    color: #5c6478;
}

/* ---------- 队列列表 ---------- */
QListWidget#queueList {
    background: #0f1522;
    border: 1px solid #232c40;
    border-radius: 8px;
    font-size: 12px;
    color: #dfe5f0;
    outline: none;
}
QListWidget#queueList::item {
    padding: 5px 9px;
    border-radius: 6px;
}
QListWidget#queueList::item:hover {
    background: #1b2436;
}
QListWidget#queueList::item:selected {
    background: #24406e;
    color: #eaf1ff;
}

/* ---------- 窗口表格 ---------- */
QTableWidget#windowTable {
    background: #0f1522;
    alternate-background-color: #111827;
    border: 1px solid #232c40;
    border-radius: 8px;
    gridline-color: transparent;
    font-size: 12px;
    color: #dfe5f0;
    outline: none;
}
QTableWidget#windowTable::item {
    padding: 4px 8px;
    border: none;
}
QTableWidget#windowTable::item:hover {
    background: #1b2436;
}
QTableWidget#windowTable::item:selected {
    background: #24406e;
    color: #eaf1ff;
}
/* 表格内嵌按钮：紧凑内边距，保证 sizeHint 高度恒小于行内可用高度，
   汉字在任何 DPI 缩放下都不被纵向挤压（字体 12 + 上下 3×2 + 描边 ≈ 20 逻辑px） */
QTableWidget QPushButton {
    padding: 3px 10px;
    border-radius: 6px;
}
QTableWidget QPushButton[primary="true"] {
    padding: 3px 12px;
}
QHeaderView::section {
    background: #141a26;
    color: #9aa4bd;
    font-size: 12px;
    font-weight: 600;
    border: none;
    border-bottom: 1px solid #232c40;
    padding: 6px 9px;
}

/* ---------- 日志 ---------- */
QTextEdit#log {
    background: #0f1522;
    border: 1px solid #232c40;
    border-radius: 10px;
    padding: 8px 10px;
    color: #c3ccdd;
    font-size: 12px;
    selection-background-color: #2c518a;
}

/* ---------- 分栏分隔条 ---------- */
QSplitter::handle {
    background: transparent;
}
QSplitter::handle:hover {
    background: #2e3a55;
}
QSplitter::handle:horizontal {
    width: 3px;
    margin: 8px 1px;
    border-radius: 1px;
}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px 0;
}
QScrollBar::handle:vertical {
    background: #26314a;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #3d4b6b;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}

/* ---------- 状态栏 / 菜单 ---------- */
QStatusBar {
    background: #0b0f17;
    color: #9aa4bd;
    font-size: 12px;
    border-top: 1px solid #1a2130;
}
QStatusBar::item {
    border: none;
}
QMenu {
    background: #161d2b;
    color: #e2e8f4;
    border: 1px solid #2e3a55;
    border-radius: 8px;
    padding: 6px;
}
QMenu::item {
    padding: 6px 22px;
    border-radius: 6px;
}
QMenu::item:selected {
    background: #24406e;
}
QMenu::separator {
    height: 1px;
    background: #232c40;
    margin: 4px 8px;
}
"""


def repolish(widget: QWidget) -> None:
    """动态属性（state / locked）改动后强制重刷样式。

    Qt 不会自动感知 setProperty 后继的样式变化，必须 unpolish/polish 一次，
    否则 QFrame#card[state="running"]、QLabel#pill[state] 这类选择器不生效。
    """
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
