from pathlib import Path

root_dir = Path(__file__).parent.parent
resource_root = root_dir / "resource"

# 游戏界面主题：游戏有蓝色/绿色两套界面，同一图标的贴图不同，
# 模板资源按主题分目录存放：resource/GREEN（绿色，默认）、resource/BLUE（蓝色）。
# 切换主题调用 set_theme()（重建所有 *_path 常量），已加载的图标由
# GameResource.reload() / GameController.reload_resources() 负责重载。
DEFAULT_THEME = "GREEN"
THEMES = ("GREEN", "BLUE")
current_theme = DEFAULT_THEME
image_dir = resource_root / current_theme

# 常量名 -> 相对 resource/<主题>/ 的路径。set_theme 会按当前主题重建这些全局常量，
# 因此需要动态读取路径的模块请用 `from shenwu import config` 后访问 config.xxx_path，
# 不要依赖 `from shenwu.config import *` 的导入期快照
_RELATIVE_PATHS = {
    # 巡游
    # 巡游的npc"开始战斗"的对话框
    "xun_you_start_fight_path": "XunYou/start_fight.png",
    # 巡游结束的npc对话框
    "xun_you_finish_path": "XunYou/xun_you_end.png",
    # 钓鱼相关
    "you_yu_path": "Fish/you_yu.png",
    # 通用
    # 判断是否在战斗中
    "is_in_fight_path": "Common/is_in_fight.png",
    # 宠物商店
    "pet_shop_path": "Common/PetShop/pet_shop.png",
    # 宠物商店的购买按钮
    "pet_shop_buy_button_path": "Common/PetShop/pet_shop_buy_button.png",
    # 商店
    "item_shop_path": "Common/ItemShop/item_shop.png",
    # 商店购买按钮
    "item_buy_button_path": "Common/ItemShop/item_shop_buy_button.png",
    # 商品寄售需求的图标
    "item_xu_qiu_path": "Common/ItemShop/item_xu_qiu.png",
    # 商品寄售价格确认按钮
    "item_que_ren_path": "Common/ItemShop/item_shop_que_ren.png",
    # 关闭npc对话框的关闭按钮
    "close_talk_path": "Common/close_talk.png",
    # 自动寻路的图标
    "xun_lu_path": "Common/xun_lu.png",
    # 日程
    "ri_cheng_path": "Common/ri_cheng.png",
    # 日程入口的小图标（屏幕上的日程按钮，用于点击打开日历，替代 Alt+Y）
    "ri_cheng_small_path": "Common/ri_cheng_small.png",
    # 驱魔
    "qu_mo_small_path": "Common/qu_mo_small.png",
    # 驱魔物品的图标
    "qu_mo_icon_path": "Common/qu_mo.png",
    # 背包
    "bag_icon_path": "Common/bag.png",
    "bag_small_path": "Common/bag_small.png",
    # F9
    "f9_icon_path": "Common/f9.png",
    # 交易中心
    "jiao_yi_zhong_xin_1_path": "Common/jiao_yi_zhong_xin_1.png",  # 全部的
    "jiao_yi_zhong_xin_2_path": "Common/jiao_yi_zhong_xin_2.png",
    "jiao_yi_zhong_xin_3_path": "Common/jiao_yi_zhong_xin_3.png",
    "zi_dong_path": "Common/zi_dong.png",  # 自动按钮
    "zi_dong_small_path": "Common/zi_dong_small.png",
    # 星级图标（4 星）
    "star_4_path": "Common/star/4.png",
    # 除魔相关
    "chu_mo_finish_icon_path": "ChuMo/chu_mo_finished.png",
    # 封妖相关
    # 修业相关
    "xiu_ye_path": "XiuYe/xiu_ye_task.png",
    "xiu_ye_wu_zi_path": "XiuYe/task_wu_zi.png",
    "xiu_ye_chong_wu_path": "XiuYe/task_chong_wu.png",
    "xiu_ye_tiao_zhan_path": "XiuYe/task_tiao_zhan.png",
    "xiu_ye_tong_men_path": "XiuYe/task_tong_men.png",
    "xiu_ye_tiao_zhan_shou_xi_path": "XiuYe/xiu_ye_tiao_zhan_shou_xi.png",
    "xiu_ye_lie_hen_path": "XiuYe/xiu_ye_lie_hen.png",
    "xiu_ye_give_item_path": "XiuYe/give_item.png",
    "xiu_ye_item_que_ding_path": "XiuYe/xiu_ye_item_que_ding.png",
    "xiu_ye_finish_path": "XiuYe/xiu_ye_finish.png",
    # 修炼相关
    "xiu_lian_no_finish_path": "XiuLian/xiu_lian_no_finish.png",
    "xiu_lian_finish_path": "XiuLian/xiu_lian_finish.png",
    "xiu_lian_talk_path": "XiuLian/xiu_lian_talk.png",
    # 修炼任务
    "xiu_lian_task_path": "XiuLian/xiu_lian_task.png",
    "xiu_lian_xun_wu_path": "XiuLian/xiu_lian_xun_wu.png",
    "xiu_lian_zhao_ren_path": "XiuLian/xiu_lian_zhao_ren.png",
    "xiu_lian_feng_dao_ren_path": "XiuLian/xiu_lian_dao_ren.png",
    "xiu_lian_bao_hu_feng_dao_ren_path": "XiuLian/bao_hu_feng_dao_ren.png",
    # 活动
    "si_nan_icon_path": "HuoDong/si_nan.png",
    # 门派论剑
    "men_pai_lun_jian_path": "HuoDong/men_pailun_jian.png",
    # 宝塔
    "bao_ta_xing_ji_tiao_jian": "BaoTa/bao_ta_xing_ji_tiao_jian.png",
    "bao_ta_kai_shi_tiao_zhan": "BaoTa/bao_ta_kai_shi_tiao_zhan.png",
    "bao_ta_tong_guan": "BaoTa/bao_ta_tong_guan.png",
    "bao_ta_an_niu": "BaoTa/bao_ta_an_niu.png",
}

# Yolo 模型与游戏主题无关（蓝绿两套界面用同一个检测模型），
# 固定放在 resource/Common/YOLO/ 下，不参与 set_theme 的按主题重建
yolo_model_path = resource_root / "Common" / "YOLO" / "last.onnx"


def _saved_theme() -> str:
    """读取 GUI 上次选择的主题（gui_settings.json 的 theme 字段）。

    让命令行任务与 GUI 使用同一套主题资源；读不到或值非法时回退默认主题。
    """
    try:
        import json

        data = json.loads((root_dir / "gui_settings.json").read_text(encoding="utf-8"))
        theme = str(data.get("theme") or "").upper()
        return theme if theme in THEMES else DEFAULT_THEME
    except Exception:
        return DEFAULT_THEME


def set_theme(theme: str) -> None:
    """切换游戏主题并重建所有资源路径常量（YOLO 模型路径固定，不受主题影响）。

    只切换路径；已加载进内存的模板图标需要 GameResource.reload() 重载
    （或 GameController.reload_resources()）。
    """
    global current_theme, image_dir
    theme = str(theme).upper()
    if theme not in THEMES:
        raise ValueError(f"未知游戏主题: {theme!r}，可选 {THEMES}")
    if theme == current_theme:
        return
    current_theme = theme
    image_dir = resource_root / theme
    _init_paths()
    print(f"🎨 游戏主题已切换: {theme}")


def _init_paths() -> None:
    """按当前主题（image_dir）重建所有资源路径全局常量"""
    for name, rel in _RELATIVE_PATHS.items():
        globals()[name] = image_dir / rel


# 导入期初始化：跟随 GUI 上次选择的主题，保证命令行与界面用同一套资源
current_theme = _saved_theme()
image_dir = resource_root / current_theme
_init_paths()
