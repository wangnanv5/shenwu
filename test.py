import time
from shenwu.controller import GameController

if __name__ == '__main__':
    game_controller = GameController()

    # while True:
    #     try:
    #         # run_auto_reset_round  run_xun_you run_auto_task
    #         game_controller.run_auto_reset_round()
    #         # game_controller.run_auto_task('法宝引导')
    #         time.sleep(game_controller.human_delay(5, sigma=0.15))
    #     except Exception as e:
    #         print(e)

    game_controller.run_xiu_ye()