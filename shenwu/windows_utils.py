import ctypes
from ctypes import wintypes
import time
import win32gui
import win32con
import win32api
import win32ui

# 开启 DPI 感知，防止高分屏下字体模糊和坐标偏移
# 包一层：该调用一个进程只允许成功一次（GUI 下 Qt 可能已经设置过），失败不能影响导入
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

# 渲染颜色：未配置的窗口用默认色，游戏窗口用专用色
DEFAULT_COLOR_RGB = (0, 170, 255)
GAME_WINDOW_COLOR_RGB = (255, 90, 0)

# 已配置的渲染颜色：hwnd -> (r, g, b)，GUI 可通过 set_render_color 写入
RENDER_COLOR_CONFIG: dict[int, tuple[int, int, int]] = {}


def get_render_color(hwnd, is_game_window=False):
    """取得窗口的渲染颜色：已配置 > 游戏窗口专用色 > 默认色"""
    try:
        configured = RENDER_COLOR_CONFIG.get(int(hwnd))
    except Exception:
        configured = None
    if configured:
        return configured
    return GAME_WINDOW_COLOR_RGB if is_game_window else DEFAULT_COLOR_RGB


# 区分度高的调色板：按序号分配，保证同一批窗口颜色互不重复且好分辨
DISTINCT_COLOR_PALETTE = (
    (255, 90, 0),    # 橙
    (0, 176, 240),   # 天蓝
    (76, 209, 55),   # 绿
    (255, 205, 0),   # 黄
    (198, 76, 255),  # 紫
    (255, 82, 140),  # 玫红
    (0, 209, 178),   # 青绿
    (96, 130, 255),  # 靛蓝
    (255, 143, 64),  # 浅橙
    (140, 255, 120), # 浅绿
    (255, 110, 220), # 粉
    (110, 220, 255), # 浅蓝
)


def _next_distinct_color(used):
    """调色板用完后，按黄金角继续生成色相，尽量远离已有颜色"""
    import colorsys

    for step in range(1, 721):
        hue = (step * 0.381966) % 1.0  # 黄金角，保证相邻色相差异最大
        rgb = tuple(round(channel * 255) for channel in colorsys.hsv_to_rgb(hue, 0.82, 0.96))
        if rgb not in used:
            return rgb
    return DEFAULT_COLOR_RGB


def assign_colors(hwnds, assigned=None):
    """给一组 hwnd 分配互不重复的渲染颜色，已分配过的保持原色（窗口增减时不串色）。

    hwnds   : 当前这批窗口的 hwnd（建议按升序传入）
    assigned: 上一次的分配结果 {hwnd: (r, g, b)}
    返回     : {hwnd: (r, g, b)}，只包含当前这批窗口
    """
    hwnds = [int(hwnd) for hwnd in hwnds]
    assigned = {int(hwnd): tuple(color) for hwnd, color in (assigned or {}).items()}

    # 只保留「还在列表里」的旧颜色，关掉的窗口释放颜色给新窗口复用
    result = {}
    used = set()
    for hwnd in hwnds:
        color = assigned.get(hwnd)
        if color is not None:
            result[hwnd] = color
            used.add(color)

    for hwnd in hwnds:
        if hwnd in result:
            continue
        color = None
        for candidate in DISTINCT_COLOR_PALETTE:
            if tuple(candidate) not in used:
                color = tuple(candidate)
                break
        if color is None:
            color = _next_distinct_color(used)
        result[hwnd] = color
        used.add(color)

    return {int(hwnd): result[int(hwnd)] for hwnd in hwnds}


def set_render_color(hwnd, color_rgb):
    """为某个 hwnd 配置渲染颜色；传 None 删除配置，回退到默认色"""
    key = int(hwnd)
    if color_rgb is None:
        RENDER_COLOR_CONFIG.pop(key, None)
    else:
        RENDER_COLOR_CONFIG[key] = tuple(color_rgb)


def enumerate_windows(color_resolver=None, skip_empty_title=True):
    """枚举当前所有可枚举到的顶层窗口，按 hwnd 数值升序返回。

    color_resolver: 可选回调 (hwnd, title) -> (r, g, b)，由调用方按业务规则决定颜色；
                    不给则用 DEFAULT_COLOR_RGB。
    返回: [{"hwnd","title","class_name","visible","color_rgb"}, ...]
    """
    collected = []

    def _collect(hwnd, _extra):
        try:
            if not win32gui.IsWindow(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if skip_empty_title and not title.strip():
                return
            class_name = win32gui.GetClassName(hwnd)
            visible = bool(win32gui.IsWindowVisible(hwnd))

            color_rgb = DEFAULT_COLOR_RGB
            if color_resolver is not None:
                try:
                    color_rgb = color_resolver(hwnd, title) or DEFAULT_COLOR_RGB
                except Exception:
                    color_rgb = DEFAULT_COLOR_RGB

            collected.append({
                "hwnd": int(hwnd),
                "title": title,
                "class_name": class_name,
                "visible": visible,
                "color_rgb": tuple(color_rgb),
            })
        except Exception:
            # 单个窗口取信息失败不影响整体枚举
            pass

    win32gui.EnumWindows(_collect, None)
    collected.sort(key=lambda item: item["hwnd"])
    return collected

def get_true_window_rect(hwnd):
    """获取不含 Windows 隐形阴影的真实窗口边界"""
    rect = wintypes.RECT()
    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    ctypes.windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd),
        wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS),
        ctypes.byref(rect),
        ctypes.sizeof(rect)
    )
    return rect.left, rect.top, rect.right, rect.bottom

class Win32BorderWithLabel:
    def __init__(self, target_hwnd, label_text="🎯 目标窗口", border_width=5, color_rgb=(255, 90, 0)):
        self.target_hwnd = target_hwnd
        self.label_text = label_text
        self.border_width = border_width
        self.tag_height = 28  # 顶部文字标签的高度
        
        # 状态缓存：用于判断窗口位置或大小是否真的发生了变化
        self._last_rect = None
        self._last_size = (0, 0)
        self._is_hidden = False

        self.border_color = win32api.RGB(*color_rgb)
        self.text_color = win32api.RGB(255, 255, 255)    # 白色文字
        self.transparent_key = win32api.RGB(255, 0, 255) # 品红色作为透明穿透色

        # 预先创建画刷和字体（避免在 WM_PAINT 中频繁创建销毁）
        self.brush_border = win32gui.CreateSolidBrush(self.border_color)
        self.brush_trans = win32gui.CreateSolidBrush(self.transparent_key)

        lf = win32gui.LOGFONT()
        lf.lfHeight = -16
        lf.lfWeight = win32con.FW_BOLD
        lf.lfQuality = win32con.CLEARTYPE_QUALITY
        lf.lfFaceName = "Microsoft YaHei"
        self.hfont = win32gui.CreateFontIndirect(lf)

        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = self.wnd_proc
        # 每个实例用独立类名：pywin32 的 WNDCLASS 一旦注册就绑定了那一个 wnd_proc，
        # 多个覆盖层共用一个类名会让所有窗口的消息都派发到第一个实例（画错内容、
        # 销毁时重复 DeleteObject）。单实例行为与原先完全一致。
        wc.lpszClassName = f"Win32BorderLabelOverlay_{id(self)}"
        # 不设置默认背景画刷，彻底交给双缓冲处理
        wc.hbrBackground = 0
        try:
            win32gui.RegisterClass(wc)
        except Exception:
            pass

        ex_style = (
            win32con.WS_EX_LAYERED | 
            win32con.WS_EX_TRANSPARENT | 
            win32con.WS_EX_TOPMOST | 
            win32con.WS_EX_TOOLWINDOW |
            win32con.WS_EX_NOACTIVATE
        )
        self.hwnd = win32gui.CreateWindowEx(
            ex_style, wc.lpszClassName, "", win32con.WS_POPUP,
            0, 0, 0, 0, 0, 0, 0, None
        )
        win32gui.SetLayeredWindowAttributes(
            self.hwnd, self.transparent_key, 0, win32con.LWA_COLORKEY
        )

    def close(self):
        """关闭覆盖层（新增接口：GUI 切换/清除目标时调用，不影响原有绘制行为）"""
        try:
            if win32gui.IsWindow(self.hwnd):
                win32gui.DestroyWindow(self.hwnd)
        except Exception:
            pass

    def set_text(self, new_text):
        """动态更新标签文字（仅在文字确实改变时触发重绘）"""
        if self.label_text != new_text:
            self.label_text = new_text
            win32gui.InvalidateRect(self.hwnd, None, False)  # False 表示不擦除背景

    def update_position(self):
        if not win32gui.IsWindow(self.target_hwnd):
            win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
            return False

        # 如果目标窗口最小化或不可见，隐藏覆盖层
        if win32gui.IsIconic(self.target_hwnd) or not win32gui.IsWindowVisible(self.target_hwnd):
            if not self._is_hidden:
                win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
                self._is_hidden = True
            return True

        current_rect = get_true_window_rect(self.target_hwnd)

        # 【关键优化】如果目标窗口位置和大小完全没变，且当前已显示，则什么都不做！
        if current_rect == self._last_rect and not self._is_hidden:
            return True

        left, top, right, bottom = current_rect
        bw = self.border_width
        th = self.tag_height
        new_w = (right - left) + bw * 2
        new_h = (bottom - top) + bw * 2 + th

        # 移动/缩放覆盖层窗口
        win32gui.SetWindowPos(
            self.hwnd,
            win32con.HWND_TOPMOST,
            left - bw,
            top - bw - th,
            new_w,
            new_h,
            win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW
        )

        # 只有当窗口宽高发生改变时，才需要强制重新绘制边框矩形；单纯平移位置无需重绘内容
        if (new_w, new_h) != self._last_size or self._is_hidden:
            win32gui.InvalidateRect(self.hwnd, None, False)
            self._last_size = (new_w, new_h)

        self._last_rect = current_rect
        self._is_hidden = False
        return True

    def wnd_proc(self, hwnd, msg, wparam, lparam):
        # 【关键优化 1】拦截背景擦除消息，直接返回 1 防止系统闪烁擦除
        if msg == win32con.WM_ERASEBKGND:
            return 1

        if msg == win32con.WM_PAINT:
            hdc_screen, ps = win32gui.BeginPaint(hwnd)
            rect = win32gui.GetClientRect(hwnd)
            w, h = rect[2], rect[3]

            if w > 0 and h > 0:
                bw = self.border_width
                th = self.tag_height

                # 【关键优化 2】创建内存 DC 和兼容位图，实现双缓冲绘图
                hdc_mem = win32gui.CreateCompatibleDC(hdc_screen)
                hbmp = win32gui.CreateCompatibleBitmap(hdc_screen, w, h)
                old_bmp = win32gui.SelectObject(hdc_mem, hbmp)

                # 1. 在内存中先把整个画布填满透明色（品红）
                win32gui.FillRect(hdc_mem, (0, 0, w, h), self.brush_trans)

                # 2. 在内存中绘制下半部分的边框并挖空中心
                win32gui.FillRect(hdc_mem, (0, th, w, h), self.brush_border)
                if w > bw * 2 and h > th + bw * 2:
                    win32gui.FillRect(hdc_mem, (bw, th + bw, w - bw, h - bw), self.brush_trans)

                # 3. 在内存中计算文字宽度并绘制左上角标签底座
                old_font = win32gui.SelectObject(hdc_mem, self.hfont)
                _, calc_rect = win32gui.DrawText(
                    hdc_mem,
                    self.label_text,
                    -1,
                    (0, 0, 0, 0),
                    win32con.DT_CALCRECT | win32con.DT_SINGLELINE
                )
                text_pixel_width = calc_rect[2] - calc_rect[0]
                tag_width = max(110, text_pixel_width + 24)
                tag_rect = (0, 0, min(tag_width, w), th)
                win32gui.FillRect(hdc_mem, tag_rect, self.brush_border)

                # 4. 在内存中绘制文字
                win32gui.SetBkMode(hdc_mem, win32con.TRANSPARENT)
                win32gui.SetTextColor(hdc_mem, self.text_color)
                win32gui.DrawText(
                    hdc_mem,
                    self.label_text,
                    -1,
                    tag_rect,
                    win32con.DT_CENTER | win32con.DT_VCENTER | win32con.DT_SINGLELINE
                )

                # 5. 将画好的内存图像一次性拷贝到屏幕 DC 上（彻底消除闪烁）
                win32gui.BitBlt(hdc_screen, 0, 0, w, h, hdc_mem, 0, 0, win32con.SRCCOPY)

                # 清理内存 DC 资源
                win32gui.SelectObject(hdc_mem, old_font)
                win32gui.SelectObject(hdc_mem, old_bmp)
                win32gui.DeleteObject(hbmp)
                win32gui.DeleteDC(hdc_mem)

            win32gui.EndPaint(hwnd, ps)
            return 0

        if msg == win32con.WM_DESTROY:
            win32gui.DeleteObject(self.brush_border)
            win32gui.DeleteObject(self.brush_trans)
            win32gui.DeleteObject(self.hfont)
            return 0

        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

# if __name__ == "__main__":
#     target = win32gui.GetForegroundWindow()
#     overlay = Win32BorderWithLabel(
#         12388510, 
#         label_text=f"⚡ AI 正在操作此窗口 [HWND: {target}]",
#         border_width=6,
#         color_rgb=(0, 170, 255)
#     )
    
#     while overlay.update_position():
#         win32gui.PumpWaitingMessages()
#         time.sleep(0.016)