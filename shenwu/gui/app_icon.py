"""用 Pillow 现画一个应用图标（蓝底 + 靶心准星），不额外引入依赖、也不需要二进制资源文件。

图标同时用于窗口标题栏和任务栏：run_gui() 里 app.setWindowIcon(build_app_icon())。
"""

from __future__ import annotations

from PIL import Image, ImageDraw
from PyQt6.QtGui import QIcon, QImage, QPixmap

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)

_ACCENT = (255, 90, 0, 255)  # 与游戏窗口边框同色系的橙色
_TOP = (47, 107, 255, 255)  # 渐变顶：主题蓝
_BOTTOM = (18, 30, 54, 255)  # 渐变底：深色


def _render(size: int) -> Image.Image:
    """画一张 size x size 的图标：圆角渐变底 + 白色靶环 + 橙色准星 + 四角定位框"""
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # 1. 竖直渐变底（蓝 → 深蓝）
    gradient = Image.new("RGBA", (size, size))
    band = ImageDraw.Draw(gradient)
    for y in range(size):
        ratio = y / max(1, size - 1)
        band.line(
            [(0, y), (size, y)],
            fill=tuple(round(_TOP[i] + (_BOTTOM[i] - _TOP[i]) * ratio) for i in range(4)),
        )

    # 2. 裁成圆角矩形
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=round(size * 0.24), fill=255
    )
    icon.paste(gradient, (0, 0), mask)

    draw = ImageDraw.Draw(icon)
    line_w = max(1, round(size * 0.075))

    # 3. 白色靶环 + 橙色准星（对应「给目标窗口描边」这个用途）
    margin = size * 0.24
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        outline=(235, 242, 255, 255),
        width=line_w,
    )
    dot = size * 0.10
    center = size / 2
    draw.ellipse(
        [center - dot, center - dot, center + dot, center + dot],
        fill=_ACCENT,
    )

    # 4. 四角定位框（橙色）
    corner = size * 0.12
    arm = size * 0.20
    for left, top, dx, dy in (
        (corner, corner, 1, 1),
        (size - corner, corner, -1, 1),
        (corner, size - corner, 1, -1),
        (size - corner, size - corner, -1, -1),
    ):
        draw.line([(left, top), (left + dx * arm, top)], fill=_ACCENT, width=line_w)
        draw.line([(left, top), (left, top + dy * arm)], fill=_ACCENT, width=line_w)

    return icon


def build_app_icon() -> QIcon:
    """生成多尺寸 QIcon（16~256），保证标题栏和任务栏都是清晰的图标"""
    icon = QIcon()
    for size in ICON_SIZES:
        image = _render(size)
        qimage = QImage(
            image.tobytes("raw", "RGBA"), size, size, QImage.Format.Format_RGBA8888
        )
        # copy() 一份，避免 QImage 只是引用 PIL 的临时缓冲区
        icon.addPixmap(QPixmap.fromImage(qimage.copy()))
    return icon
