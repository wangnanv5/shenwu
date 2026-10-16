# CODEBUDDY.md

This file provides guidance to CodeBuddy Code when working with code in this repository.

# shenwu

Windows 桌面游戏自动化脚本，针对游戏《幻唐志》。通过 OpenCV 模板匹配识别界面元素，配合 pyautogui / win32 模拟键鼠操作，支持多窗口并行。

## 运行环境

- Windows 11，Python 3.12，依赖用 uv 管理（`uv.lock`、`.venv`）
- 必须在**游戏窗口已打开**的情况下运行：`GameController.__init__` 会枚举窗口并 `assert`，找不到窗口直接失败。`GameController` 通过 `get_controller()`（`lru_cache` 懒加载）获取，命令体内才构造，所以 `--help` 不需要先开游戏窗口
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
uv run python main.py test-resources         # 诊断：实时可视化所有图标匹配情况
uv run python main.py test-get-color --color blue  # 诊断：实时可视化 get_color 检测
```

`main.py` 是 click 命令组。没有测试和 lint 配置；调试靠两个 `test-*` 诊断命令（实时预览窗口，按 q 退出）。

## 结构

| 文件 | 职责 |
| --- | --- |
| `main.py` | click CLI 入口 |
| `shenwu/controller_cv.py` | `GameController`，业务流程编排（当前主力实现） |
| `shenwu/resource.py` | `GameResource`，集中加载 33 个模板图标 |
| `shenwu/config.py` | 图标文件路径（`resource/` 下的 PNG） |
| `shenwu/utils.py` | 窗口/截图/模板匹配/键盘/颜色检测等底层工具 |
| `shenwu/ocr.py` | `Ocr`，RapidOCR 封装，`get_ocr_from_image(img, target_texts)` 按目标文本过滤 |
| `legacy/` | 旧版 OCR 实现 `controller.py` 和几个临时脚本，**只读参考，不再维护** |

`resource/` 按业务分子目录：`Common`、`XiuLian`、`XiuYe`、`XunYou`、`Fish`（另有 `ChuMo`、`FengYao` 备用）。

## 核心机制

**DPI 缩放（`set_radio`）**：`__init__` 里对第一个窗口调用 `set_radio`，按「窗口客户区高度 / `ROI[3]`」算出 `self.radio`，并生成缩放后的 `self.roi`。模板匹配时把 `self.radio` 作为模板缩放比例传给 `find_best_match`，以此适配不同分辨率的窗口。换算链路：`make_mss_region(hwnd, self.roi)` → `self.grab_frame(region)` → `self.find(frame, icon)` → `get_abs_x_y_cv(bbox, left, top)` → `self.mouse.click_on([x, y])`。

**四个底层 helper**（`controller_cv.py` 顶部，业务流程全靠它们）：
- `grab_frame(region, mode)` —— `mode` 取 `gray`(默认) / `bgr` / `raw`。不要绕过它手写抓帧三连
- `find(frame, icon)` —— 固定用模块级 `THRESHOLD`(0.7) 和 `self.radio` 缩放，不要自己调 `find_best_match` 手写缩放
- `wait_until(region, predicate, want, action, action_first, lead, gap, mode)` —— 轮询直到 `predicate(frame) == want`，**返回命中的那一帧**
- `close_talk(region, lead, gap)` / `wait_shop_buy_button(...)` / `click_match(match, left, top, delay)` —— 基于 `wait_until` 的组合

**`action_first` 是语义性的，别随手改**：开背包、点购买、点击进入战斗属于「目标状态还不存在，必须先操作一次」，用 `True`；f9、alt+y(日历) 是**开关键**，用默认的 `False`，否则第一轮就会把已打开的面板关掉。

**任务类型用 Enum + 顺序匹配**：`XiuYeTaskType` / `XiuLianTaskType` 定义在 `controller_cv.py`，`_task_type(frame, icons, task_enum)` 按 icons 列表顺序匹配，**icons 顺序必须和 `GameResource` 里图标含义对应**。修业战斗类任务（挑战/收悉/同门）走同一分支。

**模块级调参常量**在 `controller_cv.py` 顶部：`ROI`(0,0,800,600)、`THRESHOLD`(0.7)、钓鱼区域 `fish_*` 常量。

**图标颜色空间必须和帧一致**：绝大多数图标在 `GameResource` 里转成灰度（`_load_gray`）；4 个例外用 `_load_rgb`：`xiu_ye_give_item_icon`、`xiu_ye_item_que_ding_icon`（在 BGRA2RGB 帧上匹配）、`xiu_ye_finish_icon`、`xiu_lian_finish_icon`（在 `grab_frame(region, "bgr")` 帧上匹配）。新增图标时先确定它在哪种帧上用。

**多窗口状态**存在 `self.hwnd_status[hwnd]`，是 `DefaultMunch`（可用属性访问），按 `is_finish_*` 标记每个窗口的任务完成情况，主循环靠 `all(...)` 判断是否全部结束。

**流程写法**：业务流程 = 一串 `wait_until` 调用。每个页面判断方法（`is_has_talk` 等）都是一行 `self.find(...) is not None`，它们既用于 `if`，也作为 predicate 传给 `wait_until`。

**延迟有两个函数**（`utils.py`）：`human_delay(x)` 只睡眠（绝大多数场景）；`rand_secs(x)` 只返回随机秒数（给 `pyautogui.moveTo(duration=...)` 这类要值的参数用）。别把 `human_delay` 的返回值当数字用。

**OCR 是懒加载的**：`self.ocr` 是 `cached_property`，构造 `Ocr()` 会加载 ONNX 模型，别挪进 `__init__`。

## 已知问题

- `run_xiu_ye` 和 `run_xiu_lian` 的主循环没有 try/except（只有 `run_xun_you` 有），单个窗口匹配失败会中断整个循环
- `get_color` 里裁剪比例（0.66/0.27 ~ 0.95/0.38）是硬编码的（虽然按帧宽高比例计算，但绑定修炼任务面板布局）；`generate_grid_mask` 的比例切片（0.478/0.191 ~ 0.783/0.830）和 800~3000 像素面积过滤同样绑定当前分辨率，换窗口尺寸要一起调
- `utils.py` 中 `check_is_frozen` / `get_abs_x_y` / `get_hwnd_image` / `open_item_shop_keyboard` / `launch_game` 主链路已不用，只为 `legacy/` 保留
- `run_fish` 走的是另一套识别路径（PIL `ImageGrab` + `pyautogui.locate`，不是 mss + cv2），只用第一个窗口

## 约定

- 注释和日志用中文，带 emoji 前缀（✅ / ❌ / 🔍）
- 命名混用拼音（修业 `xiu_ye`、修炼 `xiu_lian`、日程 `ri_cheng`、驱魔 `qu_mo`），沿用现有风格
- 项目 `package = false`（`pyproject.toml`），不打包安装，直接以脚本运行
