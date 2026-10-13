# shenwu

Windows 桌面游戏自动化脚本，针对游戏《幻唐志》。通过 OpenCV 模板匹配识别界面元素，配合 pyautogui / win32 模拟键鼠操作，支持多窗口并行。

## 运行环境

- Windows 11，Python 3.12，依赖用 uv 管理（`uv.lock`、`.venv`）
- 必须在**游戏窗口已打开**的情况下运行：`main.py` 在模块导入期就实例化 `GameController()`，其 `__init__` 会枚举窗口并 `assert`，找不到窗口直接失败
- 程序启动时设置了 `SetProcessDpiAwareness(2)`，坐标一律按屏幕绝对像素处理

## 常用命令

```bash
uv run python main.py run-xun-you            # 巡游
uv run python main.py run-xiu-ye             # 修业
uv run python main.py run-xiu-lian           # 修炼
uv run python main.py run-auto-reset-round   # 自动重置回合
uv run python main.py check-qu-mo            # 检查驱魔状态
uv run python main.py run-fish               # 钓鱼
uv run python main.py run-auto-task 法宝引导  # OCR 找任务并点击
```

`main.py` 是 click 命令组。`GameController` 通过 `get_controller()`（`lru_cache` 懒加载）获取，命令体内才构造，所以 `--help` 不需要先开游戏窗口。

## 结构

| 文件 | 职责 |
| --- | --- |
| `main.py` | click CLI 入口 |
| `shenwu/controller_cv.py` | `GameController`，业务流程编排（当前主力实现） |
| `shenwu/resource.py` | `GameResource`，集中加载 28 个模板图标 |
| `shenwu/config.py` | 图标文件路径（`resource/` 下的 PNG） |
| `shenwu/utils.py` | 窗口/截图/模板匹配/键盘等底层工具 |
| `shenwu/ocr.py` | `Ocr`，RapidOCR 封装 |
| `legacy/` | 旧版 OCR 实现 `controller.py` 和几个临时脚本，**只读参考，不再维护** |

`resource/` 按业务分子目录：`Common`、`XiuLian`、`XiuYe`、`XunYou`、`Fish`。

## 核心机制

**识别流程**：`make_mss_region(hwnd, ROI)` 生成截图区域 → `self.grab_frame(region)` → `self.find(frame, icon)` → `get_abs_x_y_cv(bbox, left, top)` 换算成屏幕坐标 → `self.mouse.click_on([x, y])`。

**四个底层 helper**（`controller_cv.py` 顶部，业务流程全靠它们）：
- `grab_frame(region, mode)` —— `mode` 取 `gray`(默认) / `bgr` / `raw`。不要绕过它手写抓帧三连
- `find(frame, icon)` —— 固定用模块级 `THRESHOLD` / `USE_MULTISCALE` / `SCALES`，不要再手写 `SCALES if USE_MULTISCALE else None`
- `wait_until(region, predicate, want, action, action_first, lead, gap, mode)` —— 轮询直到 `predicate(frame) == want`，**返回命中的那一帧**
- `close_talk(region, lead, gap)` / `wait_shop_buy_button(...)` / `click_match(match, left, top, delay)` —— 基于 `wait_until` 的组合

**`action_first` 是语义性的，别随手改**：开背包、点购买、点击进入战斗属于「目标状态还不存在，必须先操作一次」，用 `True`；f9、alt+y(日历) 是**开关键**，用默认的 `False`，否则第一轮就会把已打开的面板关掉。

**模块级调参常量**在 `controller_cv.py` 顶部：`ROI`、`THRESHOLD`(0.80)、`USE_MULTISCALE`、`SCALES`。

**图标颜色空间必须和帧一致**：绝大多数图标在 `GameResource` 里被转成灰度；`xiu_lian_finish_icon` 是例外，保持 BGR，因为它在 `BGRA2BGR` 帧上匹配。新增图标时先确定它在哪种帧上用。

**多窗口状态**存在 `self.hwnd_status[hwnd]`，是 `DefaultMunch`（可用属性访问），按 `is_finish_*` 标记每个窗口的任务完成情况，主循环靠 `all(...)` 判断是否全部结束。

**流程写法**：业务流程 = 一串 `wait_until` 调用。每个页面判断方法（`is_has_talk` 等）都是一行 `self.find(...) is not None`，它们既用于 `if`，也作为 predicate 传给 `wait_until`。

**延迟有两个函数**（`utils.py`）：`human_delay(x)` 只睡眠（绝大多数场景）；`rand_secs(x)` 只返回随机秒数（给 `pyautogui.moveTo(duration=...)` 这类要值的参数用）。别把 `human_delay` 的返回值当数字用。

**OCR 是懒加载的**：`self.ocr` 是 `cached_property`，构造 `Ocr()` 会加载 ONNX 模型，别挪进 `__init__`。

## 已知问题

- `run_xiu_ye` 和 `run_xiu_lian` 的主循环没有 try/except（只有 `run_xun_you` 有），单个窗口匹配失败会中断整个循环
- `get_color` 里裁剪比例（0.66/0.27 ~ 0.95/0.38）是硬编码的，和 `ROI = (0,0,1200,900)` 绑死，换窗口尺寸要一起改
- `utils.py` 中 `check_is_frozen` / `get_abs_x_y` / `get_hwnd_image` / `open_item_shop_keyboard` 主链路已不用，只为 `legacy/` 保留

## 约定

- 注释和日志用中文，带 emoji 前缀（✅ / ❌ / 🔍）
- 命名混用拼音（修业 `xiu_ye`、修炼 `xiu_lian`、日程 `ri_cheng`、驱魔 `qu_mo`），沿用现有风格
- 项目 `package = false`（`pyproject.toml`），不打包安装，直接以脚本运行