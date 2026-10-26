"""卡密验证（GUI 客户端）：对接 license_admin 的 HTTP 校验接口。

服务端：项目根 `license_admin/`（Python 标准库，内置 Web 管理后台）
    POST {LICENSE_URL}
    {"key": "SW-XXXX-XXXX-XXXX-XXXX", "hwid": "设备标识"}
    ← {"ok": true,  "reason": "", "message": "激活成功",
       "expires_at": 1799999999, "expires_text": "2027-01-01 00:00", ...}
    ← {"ok": false, "reason": "invalid|expired|revoked|bound|format|rate_limited",
       "message": "..."}

地址配置（按优先级）：
    SHENWU_LICENSE_URL    完整校验地址，默认 http://<LICENSE_HOST>:<PORT>/api/v1/verify
    SHENWU_LICENSE_HOST   服务器地址（默认 111.228.12.100）
    SHENWU_LICENSE_PORT   服务器端口（默认 8443）
    SHENWU_LICENSE_PATH   校验路径（默认 /api/v1/verify）

默认用 HTTP 而不是 HTTPS：license_admin 首次启动会生成自签证书，客户端系统
信任库里没有它，直连 HTTPS 必定 CERTIFICATE_VERIFY_FAILED。确实要 HTTPS 时：
    SHENWU_LICENSE_CA      自签证书/私有 CA 的 PEM 路径（推荐，证书校验仍然开启）
    SHENWU_LICENSE_INSECURE=1  跳过证书校验（仅内网/调试，会打印提示）

本模块只负责「验证 + 弹窗 + 会话状态」，不碰任务逻辑；MainWindow 在真正
执行任务前调用 ensure_activated()，返回 True 才继续。
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid

from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


# 服务器地址：默认走 HTTP（license_admin 默认是自签证书，客户端没有信任链，
# 直接用 HTTPS 会 CERTIFICATE_VERIFY_FAILED）。需要 HTTPS 时用
# SHENWU_LICENSE_URL 覆盖，并配置 SHENWU_LICENSE_CA 或（仅调试）INSECURE=1。
LICENSE_HOST = os.environ.get("SHENWU_LICENSE_HOST", "111.228.12.100")
LICENSE_PORT = _env_int("SHENWU_LICENSE_PORT", 8443)
LICENSE_PATH = os.environ.get("SHENWU_LICENSE_PATH", "/api/v1/verify")
LICENSE_URL = os.environ.get(
    "SHENWU_LICENSE_URL",
    f"http://{LICENSE_HOST}:{LICENSE_PORT}{LICENSE_PATH}")
LICENSE_TIMEOUT = 5.0
LICENSE_CA = os.environ.get("SHENWU_LICENSE_CA", "")
LICENSE_INSECURE = os.environ.get("SHENWU_LICENSE_INSECURE", "").strip().lower() in (
    "1", "true", "yes", "on")


class CertVerifyError(ConnectionError):
    """HTTPS 证书校验失败（自签证书 / 域名不匹配 / 系统缺少 CA）"""

# 失败原因 -> 是否属于「卡密不可用」，用于统一追加购买提示
_BAD_KEY_REASONS = {"format", "invalid", "expired", "revoked", "bound"}

_KEY_BODY_LEN = 16
_PREFIX = "SW"

# 会话级状态：进程内有效，重启 GUI 需重新验证（与「当前会话保持」一致）
_LOCK = threading.Lock()
_SESSION = {"key": "", "expires_at": 0, "expires_text": ""}


# ---------- 会话状态 ----------

def is_activated() -> bool:
    """当前会话是否已通过卡密验证"""
    with _LOCK:
        return bool(_SESSION["key"])


def session_info() -> dict:
    with _LOCK:
        return dict(_SESSION)


def reset_session():
    """测试/退出登录用：清空会话状态（不影响已记住的卡密）"""
    with _LOCK:
        _SESSION.update({"key": "", "expires_at": 0, "expires_text": ""})


def _mark_activated(key: str, data: dict):
    with _LOCK:
        _SESSION["key"] = key
        _SESSION["expires_at"] = int(data.get("expires_at") or 0)
        _SESSION["expires_text"] = str(data.get("expires_text") or "长期")


def activate_session(key: str, data: dict) -> None:
    """把已通过服务端校验的卡密写入会话（供 GUI「验证卡密」按钮直接调用）"""
    _mark_activated(key, data)


def failure_message(result: dict) -> str:
    """对外暴露的失败文案：卡密类失败自动补「请购买卡密」"""
    return _failure_message(result)


# ---------- 协议工具 ----------

def normalize_key(raw: str) -> str | None:
    """用户输入 -> SW-XXXX-XXXX-XXXX-XXXX；不合法返回 None

    仅用于本地预校验与持久化规范化；服务端会按自己的 prefix/groups 再校验一次。
    """
    body = "".join(ch for ch in str(raw or "").upper() if ch.isalnum())
    if body.startswith(_PREFIX):
        body = body[len(_PREFIX):]
    if len(body) != _KEY_BODY_LEN:
        return None
    return f"{_PREFIX}-" + "-".join(body[i:i + 4] for i in range(0, _KEY_BODY_LEN, 4))


def machine_id() -> str:
    """本机标识：网卡 MAC + 计算机名，取哈希前 16 位（服务端用于设备绑定）"""
    raw = f"{uuid.getnode()}-{socket.gethostname()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _ssl_context(url: str):
    """HTTPS 用的 SSL 上下文；HTTP 返回 None"""
    if not url.lower().startswith("https"):
        return None
    if LICENSE_INSECURE:
        print("⚠️ 已跳过卡密服务器的证书校验（SHENWU_LICENSE_INSECURE=1）")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if LICENSE_CA:
        return ssl.create_default_context(cafile=LICENSE_CA)
    return ssl.create_default_context()


def _failure_message(result: dict) -> str:
    """服务端消息统一成用户可读文案；卡密类失败补「请购买卡密」"""
    message = str(result.get("message") or "").strip()
    if str(result.get("reason") or "") in _BAD_KEY_REASONS:
        if "购买" not in message:
            message = f"{message}，请购买卡密" if message else "卡密无效或已过期，请购买卡密"
    return message or "卡密验证失败，请稍后重试"


def _http_suggestion(url: str) -> str:
    """把 https 地址换成同主机端口的 http 地址，用于提示里的可执行方案"""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() != "https":
        return url
    return urllib.parse.urlunsplit(("http", parts.netloc, parts.path, parts.query, ""))


def _connection_error(url: str, error: Exception) -> ConnectionError:
    """把底层网络异常翻译成可操作的提示；证书类单独成 CertVerifyError"""
    reason = getattr(error, "reason", error)
    text = str(reason)
    if isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in text:
        return CertVerifyError(
            f"HTTPS 证书校验失败（{url}）：服务端证书不受信任（license_admin 默认是"
            f"自签证书）或证书里的域名/IP 不匹配。可任选一种修复：\n"
            f"  1) 改用 HTTP：SHENWU_LICENSE_URL={_http_suggestion(url)}\n"
            f"  2) 指定服务端证书：SHENWU_LICENSE_CA=<server.crt 路径>\n"
            f"  3) 仅本机调试：SHENWU_LICENSE_INSECURE=1（跳过校验，勿用于生产）")
    return ConnectionError(f"无法连接卡密服务器 {url}（{text}）")


def verify_license(key: str, url: str | None = None,
                   timeout: float | None = None) -> dict:
    """把卡密发给 license_admin 校验，返回响应 dict。

    网络层失败抛 ConnectionError（证书失败抛其子类 CertVerifyError），调用方据此
    区分「卡密错误」与「连不上服务器」；HTTP 4xx/5xx 只要响应体是 JSON
    （如 429 限流）就照常返回，交给业务判断。
    """
    url = url or LICENSE_URL
    timeout = LICENSE_TIMEOUT if timeout is None else timeout
    payload = json.dumps({"key": key, "hwid": machine_id()},
                         ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "shenwu-gui-license/2"})

    try:
        with urllib.request.urlopen(request, timeout=timeout,
                                    context=_ssl_context(url)) as response:
            raw = response.read()
    except urllib.error.HTTPError as e:
        raw = e.read()  # 429 等带 JSON 响应体，继续往下解析
        if not raw:
            raise ConnectionError(f"卡密服务器返回 HTTP {e.code}（{url}）") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise _connection_error(url, e) from e

    try:
        return json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ConnectionError("卡密服务器返回了无法解析的数据") from e


# ---------- 激活对话框 ----------

class ActivationDialog(QDialog):
    """卡密输入框：验证成功写入会话状态并关闭，失败原地提示"""

    def __init__(self, parent=None, initial_key: str = "", initial_message: str = ""):
        super().__init__(parent)
        self.setWindowTitle("卡密激活")
        self.setModal(True)
        self.setMinimumWidth(440)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        tip = QLabel("请输入卡密后点击「激活」，激活成功后本会话内无需重复验证。")
        tip.setWordWrap(True)
        tip.setObjectName("cardTip")
        root.addWidget(tip)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText("SW-XXXX-XXXX-XXXX-XXXX")
        self.edit.setMaxLength(24)
        self.edit.setToolTip(f"校验地址：{LICENSE_URL}")
        self.edit.returnPressed.connect(self._on_activate)
        if initial_key:
            self.edit.setText(initial_key)
            self.edit.selectAll()  # 记住的卡密直接选中，方便过期后整段替换
        root.addWidget(self.edit)

        self.status = QLabel(initial_message or "")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #ff6b6b;")
        root.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_activate = QPushButton("激活")
        self.btn_activate.setProperty("primary", True)
        self.btn_activate.setDefault(True)
        self.btn_activate.clicked.connect(self._on_activate)
        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_activate)
        root.addLayout(buttons)

    def _set_busy(self, busy: bool, text: str = ""):
        self.btn_activate.setEnabled(not busy)
        self.edit.setEnabled(not busy)
        self.btn_activate.setText("验证中…" if busy else "激活")
        if text:
            self.status.setText(text)

    def _on_activate(self):
        key = normalize_key(self.edit.text())
        if key is None:
            self._set_busy(False, "卡密格式不正确，应形如 SW-XXXX-XXXX-XXXX-XXXX")
            return

        self._set_busy(True, "正在连接卡密服务器…")
        try:
            result = verify_license(key)
        except ConnectionError as e:
            self._set_busy(False, f"{e}，请检查网络后重试")
            return
        except Exception:
            self._set_busy(False, "验证失败，请稍后重试")
            return

        if result.get("ok"):
            _mark_activated(key, result)
            expires = result.get("expires_text") or "长期"
            QMessageBox.information(self, "激活成功", f"卡密已激活，有效期至：{expires}")
            self.accept()
            return

        # 卡密不存在 / 过期 / 被吊销 / 超出设备上限 / 限流
        self._set_busy(False, _failure_message(result))


def ensure_activated(parent=None, saved_key: str = "", on_saved=None) -> bool:
    """确保本会话已激活，返回 True 表示可以使用功能。

    - 会话已激活：直接放行；
    - 传了 saved_key（记住的卡密）：先静默向服务端验证，通过就直接激活、不弹窗；
      失败则带着失败原因打开对话框，并把卡密预填好，方便用户换新卡；
    - 没有记忆卡密 / 静默验证失败且用户取消：返回 False，调用方放弃本次操作。

    on_saved(key)：验证成功后的回调，由调用方决定怎么持久化（GUI 写 gui_settings.json）。
    """
    if is_activated():
        return True

    saved_key = normalize_key(saved_key) or ""
    hint = ""
    if saved_key:
        try:
            result = verify_license(saved_key)
        except ConnectionError as e:
            result = None
            hint = f"已保存的卡密未能自动验证：{e}"
        except Exception:
            result = None
            hint = "已保存的卡密自动验证失败，请重新输入"

        if result and result.get("ok"):
            _mark_activated(saved_key, result)
            return True
        if result:
            hint = f"已保存的卡密验证失败：{_failure_message(result)}"

    dialog = ActivationDialog(parent, initial_key=saved_key, initial_message=hint)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    if on_saved is not None:
        on_saved(session_info().get("key", ""))
    return True
