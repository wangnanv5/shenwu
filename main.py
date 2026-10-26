"""命令行入口。

DPI 设置只发生在命令行任务真正执行时（`_cli_controller()`），模块导入阶段
不再触碰 DPI：GUI 由 Qt 创建 QApplication 时设成 PER_MONITOR_AWARE_V2，而
Windows 一个进程只允许设置一次，提前设置会让 Qt 打印
「SetProcessDpiAwarenessContext() failed: 拒绝访问」。
"""

import traceback

import click


def set_dpi_awareness():
    """把进程声明为 Per-Monitor DPI Aware，脚本才能按屏幕绝对像素操作

    只在命令行任务里调用；GUI / 打包器入口（pystand 等）不要调用，
    否则会抢在 Qt 前面把进程设成 v1，导致 Qt 无法升级到 v2。
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


def _cli_controller():
    """命令行任务统一入口：先声明 DPI，再懒加载 controller 单例。

    顺序不能反：controller_cv 会导入截图/输入模块，DPR 相关坐标都依赖
    进程先处于 Per-Monitor 模式，所以「先设 DPI，再导入」。
    """
    set_dpi_awareness()
    from shenwu.controller_cv import get_controller
    return get_controller()


def _cli_delay(seconds):
    """命令行里的等待（懒加载 utils，GUI 分支不导入它）"""
    from shenwu.utils import human_delay
    human_delay(seconds)


@click.group()
def cli():
    pass


# python main.py run-auto-reset-round
@cli.command()
def run_auto_reset_round():
    click.echo("开始运行重置回合的脚本")
    controller = _cli_controller()
    while True:
        try:
            controller.run_auto_reset_round()
            _cli_delay(5)
        except Exception:
            # 出错后必须等待，否则会变成无间隔重试的死循环刷屏
            traceback.print_exc()
            _cli_delay(1)


# python main.py run-xun-you
@cli.command()
def run_xun_you():
    click.echo("开始运行巡游的脚本")
    _cli_controller().run_xun_you()


# python main.py run-xiu-ye
@cli.command()
def run_xiu_ye():
    click.echo("开始运行修业的脚本")
    _cli_controller().run_xiu_ye()


# python main.py run-xiu-lian
@cli.command()
def run_xiu_lian():
    click.echo("开始运行修炼的脚本")
    _cli_controller().run_xiu_lian()


# python main.py check-qu-mo
@cli.command()
def check_qu_mo():
    click.echo("开始检查驱魔状态")
    _cli_controller().check_qu_mo()


# python main.py run-fish
@cli.command()
def run_fish():
    click.echo("开始运行钓鱼的脚本")
    _cli_controller().run_fish()


# python main.py run-auto-task
@cli.command()
@click.argument('task_name')
def run_auto_task(task_name):
    click.echo(f"开始运行任务 {task_name} 的脚本")
    _cli_controller().run_auto_task(task_name)


# python main.py gui
@cli.command()
def gui():
    """启动 PyQt 图形界面"""
    # 这里绝对不要调 set_dpi_awareness()：Qt 自己会设成 PER_MONITOR_AWARE_V2
    from shenwu.gui import run_gui
    run_gui()


if __name__ == "__main__":
    cli()
