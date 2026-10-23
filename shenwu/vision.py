"""图像识别纯计算：模板匹配、颜色块定位、格子遮罩。

职责边界：输入 ndarray 帧，输出 bbox / 坐标；不抓屏、不点击、不延时。
所有函数都是无状态的，可直接用合成帧做单元测试。
"""

import cv2
import numpy as np


def find_best_match(image, templ, threshold, scale=None):
    """
    在 image 中模板匹配。

    返回:
        {
            "bbox": (x, y, w, h),
            "score": 匹配分数,
            "scale": 缩放比例
        }

    或 None
    """
    if scale is None:
        scale = 1.0

    best = None

    scale = float(scale)

    h = int(round(templ.shape[0] * scale))
    w = int(round(templ.shape[1] * scale))

    if h <= 0 or w <= 0:
        return None

    if h > image.shape[0] or w > image.shape[1]:
        return None

    if abs(scale - 1.0) < 1e-6:
        resized_templ = templ
    else:
        interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        resized_templ = cv2.resize(templ, (w, h), interpolation=interp)

    result = cv2.matchTemplate(
        image,
        resized_templ,
        cv2.TM_CCOEFF_NORMED
    )

    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val >= threshold:
        if best is None or max_val > best["score"]:
            best = {
                "bbox": (
                    int(max_loc[0]),
                    int(max_loc[1]),
                    w,
                    h
                ),
                "score": float(max_val),
                "scale": scale
            }

    return best


# 候选点数上限：低阈值 + 大面积平坦画面时命中点可能上万，先截断再 NMS 防卡顿
FIND_ALL_MAX_CANDIDATES = 200


def find_all_match(image, templ, threshold, scale=None, nms_iou=0.3):
    """
    在 image 中模板匹配，返回所有命中阈值的结果（同 find_best_match，但不止最佳一个）。

    同一目标周围会有一片相邻像素都超过阈值，用简单 NMS 去重，
    只保留每个目标的局部峰值；候选点按分数降序最多取 FIND_ALL_MAX_CANDIDATES 个。

    返回:
        [{"bbox": (x, y, w, h), "score": 匹配分数, "scale": 缩放比例}, ...]

    无匹配时返回空列表 []
    """
    if scale is None:
        scale = 1.0

    scale = float(scale)

    h = int(round(templ.shape[0] * scale))
    w = int(round(templ.shape[1] * scale))

    if h <= 0 or w <= 0:
        return []

    if h > image.shape[0] or w > image.shape[1]:
        return []

    if abs(scale - 1.0) < 1e-6:
        resized_templ = templ
    else:
        interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        resized_templ = cv2.resize(templ, (w, h), interpolation=interp)

    result = cv2.matchTemplate(
        image,
        resized_templ,
        cv2.TM_CCOEFF_NORMED
    )

    # 所有超过阈值的像素位置作为候选
    ys, xs = np.where(result >= threshold)
    if len(xs) == 0:
        return []

    # 按分数从高到低排序，截断候选后做 NMS 去掉同一目标的相邻重复命中
    order = np.argsort(result[ys, xs])[::-1][:FIND_ALL_MAX_CANDIDATES]
    kept = []
    for idx in order:
        x, y = int(xs[idx]), int(ys[idx])
        candidate = {"bbox": (x, y, w, h), "score": float(result[y, x]), "scale": scale}
        # 与已保留的框算 IoU，重叠大说明是同一个目标的相邻像素
        duplicate = False
        for item in kept:
            ix1, iy1 = max(x, item["bbox"][0]), max(y, item["bbox"][1])
            ix2 = min(x + w, item["bbox"][0] + w)
            iy2 = min(y + h, item["bbox"][1] + h)
            inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            iou = inter / (2 * w * h - inter) if inter > 0 else 0.0
            if iou > nms_iou:
                duplicate = True
                break
        if not duplicate:
            kept.append(candidate)

    return kept


def keep_largest_component(mask: np.ndarray) -> np.ndarray:
    """
    只保留二值mask中面积最大的连通域
    :param mask: uint8 二值图 (0/255)
    :return: 仅含最大连通域的 uint8 二值图
    """
    # 确保输入是二值图
    if mask.dtype != np.uint8:
        mask = (mask > 0).astype(np.uint8) * 255

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return np.zeros_like(mask)

    # 找面积最大的轮廓
    largest = max(contours, key=cv2.contourArea)

    # 创建纯黑mask，仅绘制最大轮廓（填充）
    result = np.zeros_like(mask)
    cv2.drawContours(result, [largest], -1, 255, thickness=cv2.FILLED)

    return result


def get_color(frame, color=None, radio=1):
    game_image_array = np.array(frame)
    h, w = game_image_array.shape[:2]

    x1, y1 = int(w * 0.66), int(h * 0.27)
    x2, y2 = int(w * 0.95), int(h * 0.38)
    frame = game_image_array[y1:y2, x1:x2]

    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)

    if color == "blue":
        lower = np.array([85, 100, 150])
        upper = np.array([130, 255, 255])
        mask = cv2.inRange(hsv, lower, upper)
    elif color == "yellow":
        lower = np.array([20, 100, 150])
        upper = np.array([45, 255, 255])
        mask = cv2.inRange(hsv, lower, upper)
    elif color == "red":
        lower_red1 = np.array([0, 120, 150])   # 红色段1: H=0~10
        upper_red1 = np.array([10, 255, 255])

        lower_red2 = np.array([170, 120, 150])   # 红色段2: H=170~180
        upper_red2 = np.array([180, 255, 255])

        mask_red1 = cv2.inRange(hsv, lower_red1, upper_red1)
        mask_red2 = cv2.inRange(hsv, lower_red2, upper_red2)
        mask = cv2.bitwise_or(mask_red1, mask_red2)  # 两段合并
    else:
        raise ValueError(f"不支持的颜色: {color}")

    mask = keep_largest_component(mask)

    # 先闭运算：连接相近的文字像素
    kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5))
    mask_closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close)

    # 再开运算：去除细小噪点
    kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask_clean = cv2.morphologyEx(mask_closed, cv2.MORPH_OPEN, kernel_open)

    contours, _ = cv2.findContours(
        mask_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    if not contours:
        return None

    x, y, cw, ch = cv2.boundingRect(contours[0])
    return x + x1, y + y1, cw, ch


# 获取提交任务的物品格子坐标
def generate_grid_mask(img, radio, template_path=None):
    h, w = img.shape[:2]

    # 2. 获取 40 个格子的矩形坐标 (x1, y1, x2, y2)
    if template_path:
        # 【方式 A：模板匹配动态定位】适合窗口位置可能发生移动的情况
        template = cv2.imread(template_path)
        res = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)

        anchor_x, anchor_y = max_loc
        # 根据“给予物品”按钮左上角的相对偏移量（根据截图分辨率微调）
        x1 = anchor_x - 32
        y1 = anchor_y + 35
        x2 = x1 + 203   # 40格区域整体宽度
        y2 = y1 + 324   # 40格区域整体高度
    else:
        # 【方式 B：直接基于原图比例/坐标切片】适合固定分辨率截图
        # 下述比例匹配你提供的游戏截图分辨率
        x1 = int(w * 0.48)
        y1 = int(h * 0.191)
        x2 = int(w * 0.778)
        y2 = int(h * 0.830)

    mask = np.zeros((h, w), dtype=np.uint8)
    mask[y1:y2, x1:x2] = 255
    masked_img = cv2.bitwise_and(img, img, mask=mask)

    # 3. 将遮罩后的图像转为 HSV 格式进行色彩和亮度提取
    hsv = cv2.cvtColor(masked_img, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)

    # 4. 提取高亮区域的条件
    # - 高亮：由于未置灰，原本的高光和浅色能够达到 V > 210
    # - 饱和度：S > 70（过滤掉 F3、数字等黄白/单色噪点）
    _, thresh_v = cv2.threshold(v, 140, 255, cv2.THRESH_BINARY)
    _, thresh_s = cv2.threshold(s, 0, 255, cv2.THRESH_BINARY)
    high_light_mask = cv2.bitwise_and(thresh_v, thresh_s)

    # 5. 形态学膨胀 (Dilation) 使碎片高光连成整体的道具块
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (11, 11))
    processed_mask = cv2.dilate(high_light_mask, kernel, iterations=1)

    # 6. 查找轮廓，定位所有高亮物品
    contours, _ = cv2.findContours(processed_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    detected_targets = []

    for cnt in contours:
        area = cv2.contourArea(cnt)
        # 过滤掉过小或过大的噪点轮廓（正常一格内高亮面积为 300 ~ 2500 像素）
        if 300 * radio < area < 3000 * radio:
            x, y, w, h = cv2.boundingRect(cnt)

            # 计算点击中心点
            cx = x + w // 2
            cy = y + h // 2

            # 保存定位数据
            target_info = {
                "x1": x, "y1": y, "x2": x + w, "y2": y + h,
                "center": (cx, cy)
            }
            detected_targets.append(target_info)

    # 8. 打印坐标，并保存结果
    print(f"检测到 {len(detected_targets)} 个高亮物品：")
    return detected_targets
