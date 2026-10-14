import ctypes
ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

from shenwu.controller_cv import GameController

if __name__ == '__main__':

    game_controller = GameController()
    # game_controller.check_qu_mo()
    # game_controller.run_xiu_ye()
    # game_controller.run_xiu_lian()
    game_controller.test_resources()
