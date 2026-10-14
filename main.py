try:
    import ctypes
    try:
        # Per-Monitor DPI Aware
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

import functools
import click

from shenwu.controller_cv import GameController
from shenwu.utils import human_delay


@functools.lru_cache(maxsize=1)
def get_controller():
    """懒加载：__init__ 会枚举窗口并加载图标，放到导入期会导致 --help 也必须开游戏"""
    return GameController()


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

# python main.py test-resources
@cli.command()
def test_resources():
    click.echo("开始检测 resource 图标")
    get_controller().test_resources()

# python main.py test-get-color --color blue
@cli.command()
@click.option('--color', type=click.Choice(['blue', 'yellow', 'red']),
              default='blue', help='要可视化的颜色，默认 blue')
def test_get_color(color):
    click.echo(f"开始可视化 get_color({color}) 的检测结果")
    get_controller().test_get_color(color)

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

if __name__ == "__main__":
    cli()
