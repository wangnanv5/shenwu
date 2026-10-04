from pathlib import Path

root_dir = Path(__file__).parent.parent
image_dir = root_dir / "resource"

# 判断是否在战斗中
is_in_fight_path = image_dir / "Common" / "is_in_fight.png"

# 巡游 对话框开始战斗
xun_you_start_fight_path = image_dir / "XunYou" / "start_fight.png"
xun_you_finish_path = image_dir / "XunYou" / "xun_you_end.png"

# 钓鱼相关
you_yu_path = image_dir / "Fish" / "you_yu.png"

# 通用
pet_shop_path = image_dir / "Common" / "pet_shop.png"
pet_shop_buy_button_path = image_dir / "Common" / "pet_shop_buy_button.png"
item_shop_path = image_dir / "Common" / "item_shop.png"
item_buy_button_path = image_dir / "Common" / "item_shop_buy_button.png"
item_has_buy_path = image_dir / "Common" / "item_shop_alread_buy.png"
close_talk_path = image_dir / "Common" / "close_talk.png"
xun_lu_path = image_dir / "Common" / "xun_lu.png"
item_xu_qiu_path = image_dir / "Common" / "item_xu_qiu.png"
ri_cheng_path = image_dir / "Common" / "ri_cheng.png"

# 修业相关
xiu_ye_path = image_dir / "XiuYe" / "xiu_ye.png"
xiu_ye_wu_zi_path = image_dir / "XiuYe" / "task_wu_zi.png"
xiu_ye_chong_wu_path = image_dir / "XiuYe" / "task_chong_wu.png"
xiu_ye_tiao_zhan_path = image_dir / "XiuYe" / "task_tiao_zhan.png"