import time
from shenwu.controller import GameController

if __name__ == '__main__':
    game_controller = GameController()

    # while True:
    #     try:
    #         game_controller.run_xun_you()
    #         time.sleep(game_controller.human_delay(600, sigma=0.15))
    #     except Exception as e:
    #         print(e)

    while True:
        game_controller.run_xun_you()
        time.sleep(game_controller.human_delay(2, sigma=0.15))