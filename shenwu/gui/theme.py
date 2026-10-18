"""GUI 的深色主题样式表（QSS）。

状态通过动态属性切换：
- QLabel#pill[state]  : idle / ok / err / run
- QFrame#card[state]  : idle / running / stopping，locked="true" 表示被其它任务占用
- QLabel#dot[state]   : 卡片右上角的状态圆点
"""

QSS = """
QWidget#root {
    background: #0e1116;
}

QScrollArea#taskArea, QWidget#taskContainer {
    background: transparent;
    border: none;
}

QLabel#appTitle {
    font-size: 20px;
    font-weight: 600;
    color: #eef2fa;
}
QLabel#appSub {
    font-size: 12px;
    color: #8b94a8;
}

QLabel#pill {
    padding: 5px 12px;
    border-radius: 11px;
    font-size: 12px;
    background: #1d2230;
    color: #8b94a8;
    border: 1px solid #262d3b;
}
QLabel#pill[state="ok"] {
    background: #142a20;
    color: #4ede9c;
    border: 1px solid #1f5138;
}
QLabel#pill[state="err"] {
    background: #2c1719;
    color: #ff8a8a;
    border: 1px solid #5a262b;
}
QLabel#pill[state="run"] {
    background: #14243d;
    color: #6ba8ff;
    border: 1px solid #24456f;
}

QFrame#card {
    background: #151a23;
    border: 1px solid #242c3a;
    border-radius: 14px;
}
QFrame#card[state="running"] {
    background: #161d2b;
    border: 1px solid #2f6bff;
}
QFrame#card[state="stopping"] {
    background: #1d1a15;
    border: 1px solid #ffb454;
}
QFrame#card[state="queued"] {
    background: #141c28;
    border: 1px solid #2a4470;
}
QFrame#card[locked="true"] {
    background: #12161d;
    border: 1px solid #1e2530;
}

QLabel#queueBadge {
    font-size: 11px;
    color: #6ba8ff;
    background: #14243d;
    border: 1px solid #24456f;
    border-radius: 8px;
    padding: 1px 6px;
}

QListWidget#queueList {
    background: #10141c;
    border: 1px solid #242c3a;
    border-radius: 8px;
    font-size: 12px;
    color: #dfe5f0;
}
QListWidget#queueList::item {
    padding: 4px 8px;
}
QListWidget#queueList::item:selected {
    background: #24456f;
    color: #eaf1ff;
}

QFrame#queueBar {
    background: #151a23;
    border: 1px solid #242c3a;
    border-radius: 12px;
}
QLabel#queueText {
    font-size: 12px;
    color: #8b94a8;
}
QLabel#queueProgress {
    font-size: 12px;
    font-weight: 600;
    color: #6ba8ff;
}

QLabel#cardTitle {
    font-size: 15px;
    font-weight: 600;
    color: #eef2fa;
}
QLabel#cardDesc {
    font-size: 12px;
    color: #8b94a8;
}
QLabel#cardTip {
    font-size: 11px;
    color: #6c7689;
}
QLabel#paramLabel {
    font-size: 12px;
    color: #a3acc0;
}
QLabel#dot {
    font-size: 12px;
    color: #3d4557;
}
QLabel#dot[state="running"] {
    color: #2f6bff;
}
QLabel#dot[state="stopping"] {
    color: #ffb454;
}
QLabel#dot[state="queued"] {
    color: #6ba8ff;
}

QLabel#sectionLabel {
    font-size: 13px;
    font-weight: 600;
    color: #c9d1e0;
}

QPushButton {
    background: #232a36;
    border: 1px solid #2e374a;
    border-radius: 8px;
    padding: 6px 16px;
    font-size: 12px;
    color: #e8ecf4;
}
QPushButton:hover {
    background: #2b3342;
    border-color: #3b4761;
}
QPushButton[primary="true"] {
    background: #2f6bff;
    border: 1px solid #2f6bff;
    color: #ffffff;
}
QPushButton[primary="true"]:hover {
    background: #4380ff;
    border-color: #4380ff;
}
QPushButton[danger="true"] {
    background: #33202450;
    border: 1px solid #5a262b;
    color: #ff9a9a;
}
QPushButton[danger="true"]:hover {
    background: #3d2429;
    border-color: #7b3239;
}
QPushButton:disabled {
    background: #191e27;
    border: 1px solid #222836;
    color: #5c6478;
}

QCheckBox {
    font-size: 12px;
    color: #c9d1e0;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border-radius: 4px;
    border: 1px solid #39435a;
    background: #10141c;
}
QCheckBox::indicator:checked {
    background: #2f6bff;
    border: 1px solid #2f6bff;
}
QCheckBox:disabled {
    color: #5c6478;
}

QComboBox, QLineEdit {
    background: #10141c;
    border: 1px solid #262d3b;
    border-radius: 8px;
    padding: 5px 8px;
    font-size: 12px;
    color: #dfe5f0;
}
QComboBox:focus, QLineEdit:focus {
    border: 1px solid #2f6bff;
}
QComboBox::drop-down {
    border: none;
    width: 18px;
}
QComboBox QAbstractItemView {
    background: #151a23;
    color: #dfe5f0;
    border: 1px solid #262d3b;
    selection-background-color: #2f6bff;
}

QTextEdit#log {
    background: #11151c;
    border: 1px solid #242c3a;
    border-radius: 10px;
    padding: 8px 10px;
    color: #c3ccdd;
    font-size: 12px;
}

QTableWidget#windowTable {
    background: #10141c;
    border: 1px solid #242c3a;
    border-radius: 8px;
    gridline-color: #232b39;
    font-size: 12px;
    color: #dfe5f0;
}
QTableWidget#windowTable::item {
    padding: 3px 6px;
}
QTableWidget#windowTable::item:selected {
    background: #24456f;
    color: #eaf1ff;
}
QHeaderView::section {
    background: #171c26;
    color: #8b94a8;
    font-size: 12px;
    border: none;
    padding: 5px 8px;
}

QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #2a3242;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #39435a;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}

QStatusBar {
    background: #0e1116;
    color: #8b94a8;
    font-size: 12px;
    border-top: 1px solid #1c222d;
}
QStatusBar::item {
    border: none;
}
"""
