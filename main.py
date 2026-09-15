import time
from shenwu.controller import GameController

if __name__ == '__main__':
    game_controller = GameController()

    while True:
<<<<<<< HEAD
        game_controller.run_auto_reset_round()
        time.sleep(game_controller.human_delay(200, sigma=0.15))
=======
        try:
            game_controller.run_fish()
            time.sleep(game_controller.human_delay(10, sigma=0.15))
        except Exception as e:
            print(e)
>>>>>>> f0f1551e9b450ce18fea6a93abaa9d66025bd49d
