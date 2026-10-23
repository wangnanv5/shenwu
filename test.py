import ctypes
ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

from shenwu.controller_cv import GameController
from shenwu.utils import *

if __name__ == '__main__':
    game_controller = GameController()
    # game_controller.run_xiu_ye(run_all=True)
    # game_controller.run_xiu_lian(run_all=True)
    game_controller.bao_ta(0,count=50)
    # game_controller.run_xun_you(run_all=True)

    # game_controller.reset_round()