import ctypes
ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

from shenwu.controller_cv import GameController

if __name__ == '__main__':
    # 2. 获取真实的物理像素坐标和宽高
    # left, top, right, bottom = get_physical_client_rect(67374)
    # window_width = right - left
    # window_height = bottom - top
    # ratio = window_height / 600

    # print(f"真实物理宽高: {window_width} x {window_height}, 缩放比例 ratio: {ratio}")

    game_controller = GameController()

    game_controller.check_qu_mo()
    # game_controller.run_xiu_ye()
    # game_controller.run_xiu_lian()
