"""GUI 配置的读写（纯 json，不引入新依赖）。

存盘内容：队列顺序、各任务参数、运行轮次/间隔、定时任务、日志开关、
上次选中的服务器名等。
"""

from __future__ import annotations

import json
from pathlib import Path

# 项目根目录下（shenwu/gui/settings.py -> parents[2]）
SETTINGS_PATH = Path(__file__).resolve().parents[2] / "gui_settings.json"

DEFAULTS = {
    # 自定义队列：{队列名: [{"key": 任务key, "params": {...}}, ...]}，按顺序执行
    "queues": {},
    # 窗口绑定：{服务器名: 队列名}。用服务器名而不是 hwnd 做持久化键，
    # 因为 hwnd 每次启动都会变；运行时再解析成 hwnd
    "bindings": {},
    "active_queue": "",           # 当前正在编辑/绑定的队列名
    "params": {},                 # {任务key: {参数名: 值}}，卡片当前参数
    "selected_servers": [],       # 上次在窗口列表多选的服务器名（恢复勾选用）
    "auto_scroll": True,
    "auto_refresh": True,         # 空闲时自动刷新窗口列表
    "loop": {"times": 1, "interval": 30, "continue_on_error": False},
    "schedule": {"enabled": False, "time": "12:00"},
}


def load() -> dict:
    """读取配置，缺失或损坏时回退默认值；旧版「单一队列」自动迁移成命名队列"""
    data = dict(DEFAULTS)
    try:
        if SETTINGS_PATH.exists():
            loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update(loaded)
    except Exception:
        pass

    # 旧版：queue 是一个 key 列表 -> 迁移为命名队列「默认队列」
    if data.get("queue") and not data.get("queues"):
        data["queues"] = {"默认队列": [{"key": key, "params": {}}
                                      for key in data["queue"]]}
        data["active_queue"] = "默认队列"

    # 清理已废弃的键（旧版本遗留：开发测试开关、OCR 历史、诊断面板）
    for legacy in ("show_dev_tools", "ocr_history", "diagnostic"):
        data.pop(legacy, None)
    data.pop("queue", None)

    # 嵌套字典逐层兜底，避免旧版本配置缺少新字段
    for key, default in DEFAULTS.items():
        if isinstance(default, dict):
            merged = dict(default)
            if isinstance(data.get(key), dict):
                merged.update(data[key])
            data[key] = merged
        elif key not in data:
            data[key] = default

    if not isinstance(data.get("queues"), dict):
        data["queues"] = {}
    if not isinstance(data.get("bindings"), dict):
        data["bindings"] = {}
    return data


def save(data: dict) -> bool:
    """写回配置；失败返回 False（不弹窗，由调用方决定是否提示）"""
    try:
        SETTINGS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True
    except Exception:
        return False
