import sys

import click

def set_dpi_awareness():
    """把进程声明为 Per-Monitor DPI Aware，脚本才能按屏幕绝对像素操作。

    必须在导入 controller_cv 之前调用：pyautogui 导入时会把进程设成
    SYSTEM_DPI_AWARE(1)，晚于它设置就会失败，坐标精度反而更差。
    """
    import ctypes
    try:
        # Per-Monitor DPI Aware
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

# gui 命令走另一套：Qt6 创建 QApplication 时会把进程设成 PER_MONITOR_AWARE_V2
# （比上面的 v1 更完整），而一个进程只允许设置一次，抢先设置会让 Qt 失败并打印
# 「SetProcessDpiAwarenessContext() failed: 拒绝访问」。
# 所以启动 GUI 时既不设置 DPI，也不导入下面两个模块 —— 它们会连带导入 pyautogui，
# 而 pyautogui 导入时就会把进程设成 SYSTEM_DPI_AWARE(1)，同样会抢在 Qt 前面。
_IS_GUI = len(sys.argv) > 1 and sys.argv[1] == "gui"

if not _IS_GUI:
    set_dpi_awareness()
    from shenwu.controller_cv import get_controller  # noqa: E402
    from shenwu.utils import human_delay  # noqa: E402

@click.group()
def cli():
    pass

# python main.py run-auto-reset-round
@cli.command()
def run_auto_reset_round():
    click.echo("开始运行重置回合的脚本")
    while True:
        try:
            get_controller().run_auto_reset_round()
            human_delay(5)
        except Exception as e:
            print(e)

# python main.py run-xun-you
@cli.command()
def run_xun_you():
    click.echo("开始运行巡游的脚本")
    get_controller().run_xun_you()

# python main.py run-xiu-ye
@cli.command()
def run_xiu_ye():
    click.echo("开始运行修业的脚本")
    get_controller().run_xiu_ye()

# python main.py run-xiu-lian
@cli.command()
def run_xiu_lian():
    click.echo("开始运行修炼的脚本")
    get_controller().run_xiu_lian()

# python main.py check-qu-mo
@cli.command()
def check_qu_mo():
    click.echo("开始检查驱魔状态")
    get_controller().check_qu_mo()
# python main.py run-fish
@cli.command()
def run_fish():
    click.echo("开始运行钓鱼的脚本")
    get_controller().run_fish()

# python main.py run-auto-task
@cli.command()
@click.argument('task_name')
def run_auto_task(task_name):
    click.echo(f"开始运行任务 {task_name} 的脚本")
    get_controller().run_auto_task(task_name)

# python main.py gui
@cli.command()
def gui():
    """启动 PyQt 图形界面"""
    from shenwu.gui import run_gui
    run_gui()

if __name__ == "__main__":
    cli()
