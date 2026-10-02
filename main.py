try:
    import ctypes
    try:
        # Per-Monitor DPI Aware
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

import click

from shenwu.controller_cv import GameController
from shenwu.utils import human_delay

game_controller = GameController()

@click.group()
def cli():
    pass

# python main.py run-auto-reset-round
@cli.command()
def run_auto_reset_round():
    click.echo(f"开始运行重置回合的脚本")
    while True:
        try:
            game_controller.run_auto_reset_round()
            human_delay(5)
        except Exception as e:
            print(e)

# python main.py run-xun-you
@cli.command()
def run_xun_you():
    click.echo(f"开始运行巡游的脚本")
    game_controller.run_xun_you()

# python main.py run-xiu-ye
@cli.command()
def run_xiu_ye():
    click.echo(f"开始运行修业的脚本")
    while True:
        try:
            game_controller.run_xiu_ye()
            human_delay(5)
        except Exception as e:
            print(e)

if __name__ == "__main__":
    cli()