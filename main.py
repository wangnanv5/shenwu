import time
from shenwu.controller import GameController

if __name__ == '__main__':
    game_controller = GameController()

    while True:
        game_controller.run_auto_reset_round()
        time.sleep(game_controller.human_delay(200, sigma=0.15))