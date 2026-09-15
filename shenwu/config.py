from pathlib import Path

root_dir = Path(__file__).parent.parent
image_dir = root_dir / "resource"

# 判断是否在战斗中
hui_he_path = image_dir / "Common" / "hui_he.png"

# 巡游 对话框开始战斗
xun_you_start_fight_path = image_dir / "XunYou" / "start_fight.png"
# 巡游 任务栏，寻找npc
xun_you_npc_path = image_dir / "XunYou" / "xun_you_npc.png"