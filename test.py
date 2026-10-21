import ctypes
ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

from shenwu.controller_cv import GameController

if __name__ == '__main__':
    game_controller = GameController()
<<<<<<< HEAD
    game_controller.bao_ta_windows()
=======
    game_controller.bao_ta(count=40)
>>>>>>> 06db0c4e808ab483e7b888f5e219a37dcdbd669f
    # game_controller.run_xiu_ye()
    # game_controller.run_xiu_lian()
    # game_controller.bao_ta()
    # game_controller.test_resources()
