import cv2

from shenwu.config import *


class GameResource:
    """集中加载所有模板图标资源。

    灰度图标用于 cv2.COLOR_BGRA2GRAY 转换后的帧,
    彩色图标用于 cv2.COLOR_BGRA2BGR 转换后的帧。
    """

    def __init__(self):
        # 巡游
        self.xun_you_start_fight_icon = self._load_gray(xun_you_start_fight_path)
        self.xun_you_finish_icon = self._load_gray(xun_you_finish_path)

        # 通用
        self.is_in_fight_icon = self._load_gray(is_in_fight_path)
        # 日历
        self.ri_cheng_icon = self._load_gray(ri_cheng_path)
        # 宠物商店
        self.pet_shop_icon = self._load_gray(pet_shop_path)
        # 宠物商店购买按钮
        self.pet_shop_button_icon = self._load_gray(pet_shop_buy_button_path)
        # 寄售商店页面
        self.item_shop_icon = self._load_gray(item_shop_path)
        # 寄售商店购买按钮
        self.item_shop_buy_button_icon = self._load_gray(item_buy_button_path)
        # 寄售商店的需求物资图标
        self.item_xu_qiu_icon = self._load_gray(item_xu_qiu_path)
        # 商品寄售价格确认按钮
        self.item_xu_que_ren_icon = self._load_gray(item_que_ren_path)
        # npc对话弹框
        self.has_talk_icon = self._load_gray(close_talk_path)
        # 寻路图标
        self.has_xun_lu_icon = self._load_gray(xun_lu_path)
        # 驱魔相关
        self.qu_mo_small_icon = self._load_gray(qu_mo_small_path)
        self.qu_mo_icon = self._load_gray(qu_mo_icon_path)
        # 背包
        self.bag_icon = self._load_gray(bag_icon_path)
        # f9
        self.f9_icon = self._load_gray(f9_icon_path)

        # 修业任务类型,分为捕捉宠物 查找物资 挑战
        self.has_xiu_ye_task_icon = self._load_gray(xiu_ye_path)
        # 修业的任务类型图标,分为宠物 物资 挑战
        self.xiu_ye_wu_zi_icon = self._load_gray(xiu_ye_wu_zi_path)
        self.xiu_ye_chong_wu_icon = self._load_gray(xiu_ye_chong_wu_path)
        self.xiu_ye_tiao_zhan_icon = self._load_gray(xiu_ye_tiao_zhan_path)
        self.xiu_ye_give_item_icon = self._load_gray(xiu_ye_give_item_path)
        self.xiu_ye_item_que_ding_icon = self._load_gray(xiu_ye_item_que_ding_path)

        # 修炼相关
        self.xiu_lian_no_finish_icon = self._load_gray(xiu_lian_no_finish_path)
        # 修炼完成图标在彩色帧上匹配,保持原图
        self.xiu_lian_finish_icon = self._load(xiu_lian_finish_path)
        # 修炼对话
        self.xiu_lian_talk_icon = self._load_gray(xiu_lian_talk_path)
        self.xiu_lian_task_icon = self._load_gray(xiu_lian_task_path)
        self.xiu_lian_xun_wu_icon = self._load_gray(xiu_lian_xun_wu_path)
        self.xiu_lian_zhao_ren_icon = self._load_gray(xiu_lian_zhao_ren_path)
        self.xiu_lian_feng_dao_ren_icon = self._load_gray(xiu_lian_feng_dao_ren_path)
        self.xiu_lian_bao_hu_feng_dao_ren_icon = self._load_gray(xiu_lian_bao_hu_feng_dao_ren_path)

    @staticmethod
    def _load(path):
        icon = cv2.imread(str(path))
        if icon is None:
            raise FileNotFoundError(f"无法读取图标资源: {path}")
        return icon

    @classmethod
    def _load_gray(cls, path):
        return cv2.cvtColor(cls._load(path), cv2.COLOR_BGR2GRAY)
