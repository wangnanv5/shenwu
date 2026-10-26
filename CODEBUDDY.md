# CODEBUDDY.md

This file provides guidance to CodeBuddy Code when working with code in this repository.

# shenwu

Windows 桌面游戏自动化脚本，针对游戏《幻唐志》。通过 OpenCV 模板匹配识别界面元素，配合 win32 消息级键鼠输入（仅少量游戏热键走 keybd_event 真实注入）操作窗口，支持多窗口并行。

## 运行环境

- Windows 11，Python 3.12，依赖用 uv 管理（`uv.lock`、`.venv`）
- 必须在**游戏窗口已打开**的情况下运行：`GameController.__init__` 会枚举窗口并 `assert`，找不到窗口直接失败。`GameController` 通过 `get_controller()`（`lru_cache` 懒加载）获取，命令体内才构造，所以 `--help` 不需要先开游戏窗口
- 命令行任务执行时才设置 `SetProcessDpiAwareness(2)`（`main.py` 的 `_cli_controller()`：先设 DPI 再导入 `controller_cv`），坐标一律按屏幕绝对像素处理；**模块导入阶段不碰 DPI** —— Windows 一个进程只允许设置一次，`gui` 命令和打包器入口（pystand 等）提前设置会让 Qt 创建 `QApplication` 时打印「SetProcessDpiAwarenessContext() failed: 拒绝访问」。GUI 里的 `controller_cv` 导入全部延后到 `QApplication` 创建之后，由 Qt 自己设成 `PER_MONITOR_AWARE_V2`（实测 radio / roi 与命令行模式完全一致）

## 常用命令

```bash
uv run python main.py run-xun-you            # 巡游
uv run python main.py run-xiu-ye             # 修业
uv run python main.py run-xiu-lian           # 修炼
uv run python main.py run-auto-reset-round   # 自动重置回合
uv run python main.py check-qu-mo            # 检查驱魔状态
uv run python main.py run-fish               # 钓鱼
uv run python main.py run-auto-task 法宝引导  # OCR 找任务并点击
uv run python main.py gui                    # 启动 PyQt 图形界面（推荐）
# 界面流程：执行队列面板选/建队列 → 任务卡片「加入队列」 → 窗口列表多选 hwnd「绑定队列」 → 「执行」
# Ctrl+Alt+Q 紧急停止；标题栏「开发/测试」开关显示诊断功能
uv run python main.py gui                    # 诊断功能在 GUI 的「开发/测试」开关里
uv run python main.py test-get-color --color blue  # 诊断：实时可视化 get_color 检测
```

`main.py` 是 click 命令组。没有测试和 lint 配置；调试靠两个 `test-*` 诊断命令（实时预览窗口，按 q 退出）。

## 结构

| 文件 | 职责 |
| --- | --- |
| `main.py` | click CLI 入口 |
| `shenwu/controller_cv.py` | `GameController`：窗口管理 + 公共能力（`grab_frame` / `find` / `wait_until` / `click_match` / `is_open_*`）+ 任务 Mixin 组合 |
| `shenwu/tasks/` | 按任务拆分的单窗口流程（Mixin）：`bao_ta.py`（帧间差分找动态目标 + 层循环）、`bao_tu.py`（司南 → 右键 → YOLO 挖宝） |
| `shenwu/timing.py` | 终止信号（全局 + 行级）与 `human_delay` / `rand_secs` / `is_stopped` |
| `shenwu/game_window.py` | 游戏窗口识别（`parse_game_title`、壳窗口排除）、客户区几何、`make_region` |
| `shenwu/vision.py` | 模板匹配（`find_best_match` / `find_all_match`）、颜色与格子识别（纯计算，无 IO） |
| `shenwu/win_input.py` | 键鼠输入：消息级 PostMessage 与真实注入两条通道 |
| `shenwu/capture.py` | WGC 客户区截图（`capture_client_only`），窗口可被遮挡 |
| `shenwu/utils.py` | **兼容层**：重导出上述能力（旧 import 路径不变）+ 少量通用杂项（`get_abs_x_y*`、legacy 截图） |
| `shenwu/resource.py` | `GameResource`，集中加载 33 个模板图标 |
| `shenwu/config.py` | 图标文件路径（`resource/` 下的 PNG） |
| `shenwu/ocr.py` | `Ocr`，RapidOCR 封装，`get_ocr_from_image(img, target_texts)` 按目标文本过滤 |
| `shenwu/gui/` | PyQt6 界面：`main_window.py`(装配/队列面板/窗口表/托盘) / `tasks.py`(任务卡片与清单) / `workers.py`(行线程与任务派发) / `theme.py`(QSS + repolish) / `settings.py`(json 配置) / `app_icon.py`(Pillow 现画的应用图标) |
| `shenwu/windows_utils.py` | `Win32BorderWithLabel`：给指定 hwnd 画彩色边框 + 文字标签（需外部循环调 `update_position()` 泵消息）；另有 `enumerate_windows()` / `get_render_color()` |
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

**游戏窗口识别**：只认标题严格匹配 `幻唐志 - <服务器名>` 的窗口（`GAME_TITLE_PATTERN` / `parse_game_title`，服务器名动态、可多开）。三重排除：`RENDER` 渲染窗口、壳窗口类名（`CabinetWClass` 等，打开名为「幻唐志」的文件夹时标题会是「幻唐志 - 文件资源管理器」，格式完全一样）、以及**本进程的窗口**（GUI 自身，靠标题排除不可靠，用 `GetWindowThreadProcessId` 比对 pid）。`refresh_hwnds()` 会重建列表并剔除已关闭/标题不再匹配的窗口（保留原完成状态），`window_infos()` 给 GUI 提供 `(序号, hwnd, 标题, 服务器名)`。

**GUI 执行模型（队列 -> 绑定 -> 执行）**：任务卡片没有单独启停，只负责「编辑参数 + 加入队列」。队列在「执行队列」面板定义（可多个、可增删任务/排序），持久化在 `gui_settings.json` 的 `queues`（`{队列名: [{key, params}, ...]}`）；窗口绑定持久化为 `bindings`（`{服务器名: 队列名}`，用服务器名做键是因为 hwnd 每次启动都变，运行时由 `_rebind_from_settings` 解析回 hwnd）。执行时 `_build_plan_items()` 生成 `[(hwnd, 队列名, tasks), ...]`（hwnd 升序），`TaskWorker` 逐窗口 `set_selected_hwnds([hwnd])` 后按该窗口绑定的队列顺序跑，结束恢复 `set_selected_hwnds([])`；三个 `all(...)` 完成判断只看 `hwnd_list`。开发/测试类卡片（`TaskSpec.dev_only`）默认隐藏，标题栏「开发/测试」开关控制。窗口列表按 hwnd 升序、颜色由 `windows_utils.assign_colors` 唯一分配；每个绑定窗口挂一个 `Win32BorderWithLabel`（Qt 定时器泵 `update_position()`）。

日志「自动滚动」勾选时插入后置 `scroll_bar.setValue(maximum())`（`ensureCursorVisible` 只保证光标可见，末尾空行时不会真正贴底）；未勾选时记录插入前的 `scroll_bar.value()`，插完还原，保证用户当前位置不动 —— 不能先 `moveCursor(End)` 再插入，它会把视口一起滚到底。

⚠️ `Win32BorderWithLabel` 的窗口类名必须是**每实例唯一**（`..._{id(self)}`）：pywin32 的 `WNDCLASS` 注册后绑定的是那一个 `wnd_proc`，共用类名会让所有覆盖层的消息都派发到第一个实例（内容画错 + `WM_DESTROY` 重复 `DeleteObject` 报错）。

**立即终止**：`timing.terminate_event` 是全局终止信号；`human_delay` 按 ≤0.1s 分片睡眠并在每片检查，置位后立刻抛 `TaskTerminated`（继承 **BaseException**，专门绕过业务里 `except Exception` 的逐窗口兜底）。GUI 单行「停止」走行级事件（`bind_thread_terminate`），只打断该线程；「全部停止」额外置全局信号。`RowWorker.run()` 开头 `clear_terminate()`，否则上一次紧急停止会让后续任务刚启动就退出。代价：终止会把任务留在中间状态（背包可能没关等），这是「立即终止」的固有语义。

**单窗口容错**：巡游 / 修业 / 修炼的每个窗口处理都包了 try/except，出错只记 `window_fail_counts`，连续失败 `MAX_WINDOW_FAILS`(3) 次才标记该窗口完成并跳过，任务结束汇总失败窗口；`check_qu_mo` / `run_auto_task` 同样逐窗口容错。这样坏窗口不会拖死整个任务，也不会因为一次抖动就放弃。`reset_finish_status()` 会顺带清空失败计数，`controller.current_hwnd` 记录正在处理哪个窗口（GUI 用它把边框文字改成 `▶ 当前任务`）。

**GUI 配置持久化**：`shenwu/gui/settings.py` 用 json 存项目根的 `gui_settings.json`（队列顺序、各任务参数、轮次/间隔/出错继续、定时、日志开关、上次选中的服务器名、OCR 任务名历史、诊断阈值）。窗口列表按**服务器名**恢复多选，避免 hwnd 每次都变。

**GUI 停止机制**：循环类方法（`run_xun_you` / `run_xiu_ye` / `run_xiu_lian` / `run_fish` / `run_auto_reset_round` / `test_*`）都接受可选 `stop_event`（`threading.Event`），不传时行为与命令行完全一致；GUI 用它在下一次循环检查点中断。重复执行同一任务前先调 `reset_finish_status()` 清空 `is_finish_*` 标记，否则第二次会直接跳过。`get_controller()` 的 `lru_cache` 单例已移到 `controller_cv.py`，main.py 与 GUI 共用。

**任务类型用 Enum + 顺序匹配**：`XiuYeTaskType` / `XiuLianTaskType` 定义在 `controller_cv.py`，`_task_type(frame, icons, task_enum)` 按 icons 列表顺序匹配，**icons 顺序必须和 `GameResource` 里图标含义对应**。修业战斗类任务（挑战/收悉/同门）走同一分支。

**模块级调参常量**在 `controller_cv.py` 顶部：`ROI`(0,0,800,600)、`THRESHOLD`(0.7)、钓鱼区域 `fish_*` 常量。

**图标颜色空间必须和帧一致**：绝大多数图标在 `GameResource` 里转成灰度（`_load_gray`）；4 个例外用 `_load_rgb`：`xiu_ye_give_item_icon`、`xiu_ye_item_que_ding_icon`（在 BGRA2RGB 帧上匹配）、`xiu_ye_finish_icon`、`xiu_lian_finish_icon`（在 `grab_frame(region, "bgr")` 帧上匹配）。新增图标时先确定它在哪种帧上用。

**多窗口状态**存在 `self.hwnd_status[hwnd]`，是 `DefaultMunch`（可用属性访问），按 `is_finish_*` 标记每个窗口的任务完成情况，主循环靠 `all(...)` 判断是否全部结束。

**流程写法**：业务流程 = 一串 `wait_until` 调用。每个页面判断方法（`is_has_talk` 等）都是一行 `self.find(...) is not None`，它们既用于 `if`，也作为 predicate 传给 `wait_until`。

**延迟有两个函数**（`timing.py`，`utils` 兼容重导出）：`human_delay(x)` 只睡眠（绝大多数场景）；`rand_secs(x)` 只返回随机秒数（给需要具体秒数的参数用，如动画/等待时长）。别把 `human_delay` 的返回值当数字用。

**OCR 是懒加载的**：`self.ocr` 是 `cached_property`，构造 `Ocr()` 会加载 ONNX 模型，别挪进 `__init__`。

## 已知问题

- `run_auto_task` 目前是占位实现（只遍历 `hwnd_list`，未接 OCR）；`run_fish` 用 WGC 截图 + cv2 模板匹配，且只用第一个窗口
- `get_color` 里裁剪比例（0.66/0.27 ~ 0.95/0.38）是硬编码的（虽然按帧宽高比例计算，但绑定修炼任务面板布局）；`generate_grid_mask` 的比例切片（0.478/0.191 ~ 0.783/0.830）和 800~3000 像素面积过滤同样绑定当前分辨率，换窗口尺寸要一起调
- `utils.py` 中 `check_is_frozen` / `get_abs_x_y` / `get_hwnd_image` 主链路已不用，只为 `legacy/` 保留（其余能力已迁至 timing / game_window / vision / win_input / capture）


## 约定

- 注释和日志用中文，带 emoji 前缀（✅ / ❌ / 🔍）
- 命名混用拼音（修业 `xiu_ye`、修炼 `xiu_lian`、日程 `ri_cheng`、驱魔 `qu_mo`），沿用现有风格
- 项目 `package = false`（`pyproject.toml`），不打包安装，直接以脚本运行
