import ctypes
ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

from shenwu.controller_cv import GameController
from shenwu.utils import *

if __name__ == '__main__':
    game_controller = GameController()
    # game_controller.run_xiu_ye()
    game_controller.run_xiu_lian()
    # game_controller.bao_ta(1,count=50)
    # game_controller.reset_round()