import cv2

from shenwu import config


class GameResource:
    """集中加载所有模板图标资源。

    灰度图标用于 cv2.COLOR_BGR2GRAY 转换后的帧,
    彩色图标用于 grab_frame(region, "bgr") 返回的 BGR 帧。

    图标路径在每次加载时从 config 现取（config.set_theme 切换主题后会重建
    路径常量），所以主题切换后调用 reload() 即可按新主题重新加载全部图标。
    """

    def __init__(self):
        cfg = config
        # 巡游
        self.xun_you_start_fight_icon = self._load_gray(cfg.xun_you_start_fight_path)
        self.xun_you_finish_icon = self._load_gray(cfg.xun_you_finish_path)

        # 通用
        self.is_in_fight_icon = self._load_gray(cfg.is_in_fight_path)
        # 日历
        self.ri_cheng_icon = self._load_gray(cfg.ri_cheng_path)
        # 日程入口小图标（屏幕按钮，替代 Alt+Y 打开日历）
        self.ri_cheng_small_icon = self._load_gray(cfg.ri_cheng_small_path)
        # 宠物商店
        self.pet_shop_icon = self._load_gray(cfg.pet_shop_path)
        # 宠物商店购买按钮
        self.pet_shop_button_icon = self._load_gray(cfg.pet_shop_buy_button_path)
        # 寄售商店页面
        self.item_shop_icon = self._load_gray(cfg.item_shop_path)
        # 寄售商店购买按钮
        self.item_shop_buy_button_icon = self._load_gray(cfg.item_buy_button_path)
        # 寄售商店的需求物资图标
        self.item_xu_qiu_icon = self._load_gray(cfg.item_xu_qiu_path)
        # 商品寄售价格确认按钮
        self.item_xu_que_ren_icon = self._load_gray(cfg.item_que_ren_path)
        # npc对话弹框
        self.has_talk_icon = self._load_gray(cfg.close_talk_path)
        # 寻路图标
        self.has_xun_lu_icon = self._load_gray(cfg.xun_lu_path)
        # 自动战斗按钮（small 为已开启状态的缩小图）
        self.zi_dong_icon = self._load_gray(cfg.zi_dong_path)
        self.zi_dong_small_icon = self._load_gray(cfg.zi_dong_small_path)
        # 星级图标（4 星）
        self.star_4_icon = self._load_gray(cfg.star_4_path)
        # 驱魔相关
        self.qu_mo_small_icon = self._load_gray(cfg.qu_mo_small_path)
        self.qu_mo_icon = self._load_gray(cfg.qu_mo_icon_path)
        # 背包
        self.bag_icon = self._load_gray(cfg.bag_icon_path)
        # 背包入口小图标（未打开状态，用于定位并点击打开背包）
        self.bag_small_icon = self._load_gray(cfg.bag_small_path)
        # f9
        self.f9_icon = self._load_gray(cfg.f9_icon_path)
        # 交易中心可能有多个版本的图标，交给 find_jiao_yi_zhong_xin 逐个匹配取最优
        self.jiao_yi_zhong_xin_icon = [self._load_gray(cfg.jiao_yi_zhong_xin_1_path),self._load_gray(cfg.jiao_yi_zhong_xin_2_path),self._load_gray(cfg.jiao_yi_zhong_xin_3_path)]


        # 修业任务类型,分为捕捉宠物 查找物资 挑战
        self.has_xiu_ye_task_icon = self._load_gray(cfg.xiu_ye_path)
        # 修业的任务类型图标,分为宠物 物资 挑战
        self.xiu_ye_wu_zi_icon = self._load_gray(cfg.xiu_ye_wu_zi_path)
        self.xiu_ye_chong_wu_icon = self._load_gray(cfg.xiu_ye_chong_wu_path)
        self.xiu_ye_tiao_zhan_icon = self._load_gray(cfg.xiu_ye_tiao_zhan_path)
        self.xiu_ye_tong_men_icon = self._load_gray(cfg.xiu_ye_tong_men_path)
        self.xiu_ye_tiao_zhan_shou_xi_icon = self._load_gray(cfg.xiu_ye_tiao_zhan_shou_xi_path)
        self.xiu_ye_lie_hen_icon = self._load_gray(cfg.xiu_ye_lie_hen_path)
        self.xiu_ye_give_item_icon = self._load_rgb(cfg.xiu_ye_give_item_path)
        self.xiu_ye_item_que_ding_icon = self._load_rgb(cfg.xiu_ye_item_que_ding_path)
        # 修业完成图标在彩色帧上匹配,保持原图
        self.xiu_ye_finish_icon = self._load_rgb(cfg.xiu_ye_finish_path)

        # 修炼相关
        self.xiu_lian_no_finish_icon = self._load_gray(cfg.xiu_lian_no_finish_path)
        # 修炼完成图标在彩色帧上匹配,保持原图
        self.xiu_lian_finish_icon = self._load_rgb(cfg.xiu_lian_finish_path)
        # 修炼对话
        self.xiu_lian_talk_icon = self._load_gray(cfg.xiu_lian_talk_path)
        self.xiu_lian_task_icon = self._load_gray(cfg.xiu_lian_task_path)
        self.xiu_lian_xun_wu_icon = self._load_gray(cfg.xiu_lian_xun_wu_path)
        self.xiu_lian_zhao_ren_icon = self._load_gray(cfg.xiu_lian_zhao_ren_path)
        self.xiu_lian_feng_dao_ren_icon = self._load_gray(cfg.xiu_lian_feng_dao_ren_path)
        self.xiu_lian_bao_hu_feng_dao_ren_icon = self._load_gray(cfg.xiu_lian_bao_hu_feng_dao_ren_path)

        # 活动
        self.si_nan_icon = self._load_gray(cfg.si_nan_icon_path)
        # 门派论剑
        self.men_pai_lun_jian_icon = self._load_gray(cfg.men_pai_lun_jian_path)
        # 宝塔
        self.bao_ta_kai_shi_tiao_zhan_icon = self._load_gray(cfg.bao_ta_kai_shi_tiao_zhan)
        self.bao_ta_xing_ji_tiao_jian_icon = self._load_gray(cfg.bao_ta_xing_ji_tiao_jian)
        self.bao_ta_tong_guan_icon = self._load_gray(cfg.bao_ta_tong_guan)
        self.bao_ta_an_niu_icon = self._load_gray(cfg.bao_ta_an_niu)

    def reload(self):
        """游戏主题切换后重载全部图标（config.set_theme 已重建路径常量）"""
        self.__init__()

    @staticmethod
    def _load(path):
        icon = cv2.imread(str(path))
        if icon is None:
            raise FileNotFoundError(f"无法读取图标资源: {path}")
        return icon

    @classmethod
    def _load_rgb(cls, path):
        return cv2.cvtColor(cls._load(path), cv2.COLOR_BGR2RGB)

    @classmethod
    def _load_gray(cls, path):
        return cv2.cvtColor(cls._load(path), cv2.COLOR_BGR2GRAY)
