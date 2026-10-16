import cv2
import numpy as np

def create_synthetic_bipolar_template(base_w=25, base_h=29):
    """
    无需任何截图！直接用代码合成“内亮(240) + 外暗描边(30) + 中心挖空”的标准水滴模板与掩膜
    彻底消除不同颜色图标内部渐变方向不一致的问题，并保证外圈留有充足的描边对比带。
    """
    # 1. 绘制标准水滴实心外轮廓 (预留四周 2~3px 边距给外圈黑边)
    body_mask = np.zeros((base_h, base_w), dtype=np.uint8)
    cx, cy = base_w // 2, int(round(base_h * 0.42))
    radius = int(round(base_w * 0.38))  # 约 9~10 px

    # 上半部分圆球 + 下半部分水滴尖角
    cv2.circle(body_mask, (cx, cy), radius, 255, -1)
    tip_pts = np.array([
        [cx - int(round(radius * 0.88)), cy + int(round(radius * 0.38))],
        [cx + int(round(radius * 0.88)), cy + int(round(radius * 0.38))],
        [cx, base_h - 4]
    ], dtype=np.int32)
    cv2.fillPoly(body_mask, [tip_pts], 255)

    # 2. 生成中心数字孔洞掩膜 (用于屏蔽数字 1, 2, 3... 并用于后续校验深色笔画)
    hole_mask = np.zeros((base_h, base_w), dtype=np.uint8)
    cv2.circle(hole_mask, (cx, cy), int(round(radius * 0.52)), 255, -1)

    # 水滴有效亮环区域 = 水滴实心体 - 中心数字孔洞
    ring_body_mask = cv2.subtract(body_mask, hole_mask)

    # 3. 生成外围 2px 深色描边区域
    dilated_outer = cv2.dilate(body_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)), iterations=1)
    outer_border_mask = cv2.subtract(dilated_outer, body_mask)

    # 4. 组合总匹配掩膜 (水滴亮环 + 外圈2px暗边)，中心数字和远处背景均为 0
    total_mask = cv2.bitwise_or(ring_body_mask, outer_border_mask)

    # 5. 构建合成双极性模板 (亮环设为 240，外圈暗边设为 30)
    tpl = np.zeros((base_h, base_w), dtype=np.float32)
    tpl[ring_body_mask > 0] = 240.0
    tpl[outer_border_mask > 0] = 30.0

    return tpl, total_mask, ring_body_mask, outer_border_mask, hole_mask


def verify_marker_physics(hsv_patch, ring_body_mask, outer_border_mask, hole_mask):
    """
    对候选框进行 4 项跨颜色不变的物理先验校验，彻底滤除地图建筑/雪地误检
    """
    h_ch = hsv_patch[:, :, 0].astype(np.float32)
    s_ch = hsv_patch[:, :, 1].astype(np.float32)
    v_ch = hsv_patch[:, :, 2].astype(np.float32)

    ring_v = v_ch[ring_body_mask > 0]
    ring_s = s_ch[ring_body_mask > 0]
    ring_h = h_ch[ring_body_mask > 0]
    border_v = v_ch[outer_border_mask > 0]
    hole_v = v_ch[hole_mask > 0]

    # 条件1：水滴环本身必须具备较高亮度和一定饱和度（排除纯灰白雪地与暗影）
    if np.mean(ring_v) < 150 or np.mean(ring_s) < 75:
        return False

    # 条件2：水滴环必须比外围描边明显更亮（存在清晰的图标边界）
    if (np.mean(ring_v) - np.mean(border_v)) < 28:
        return False

    # 条件3：中心孔洞内必须存在深色数字笔画（孔洞内最暗像素显著低于水滴环亮度）
    if (np.mean(ring_v) - np.percentile(hole_v, 15)) < 35:
        return False

    # 条件4：同色相一致性校验（无论图标是蓝、黄、红、绿，其环内色相角必须高度集中）
    # 将 OpenCV 的 H (0~180) 映射为 0~2*pi 弧度计算圆周平均向量长度 R (0~1，越接近1颜色越纯粹)
    angles = ring_h * (2.0 * np.pi / 180.0)
    mean_cos = np.mean(np.cos(angles))
    mean_sin = np.mean(np.sin(angles))
    hue_concentration = np.sqrt(mean_cos**2 + mean_sin**2)
    if hue_concentration < 0.82:
        return False

    return True


def detect_markers_robust(img_bgr, scales=(0.84, 0.92, 1.0, 1.08, 1.16), score_thresh=0.58):
    """
    多尺度 + S/V 融合特征 + 合成双极性模板 + 物理先验校验
    """
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    # 融合 V(明度) 与 S(饱和度) 作为特征图，转为 float32 避免 OpenCV uint8 掩膜匹配精度Bug
    feat_map = 0.65 * hsv[:, :, 2].astype(np.float32) + 0.35 * hsv[:, :, 1].astype(np.float32)

    base_tpl, base_mask, base_ring, base_border, base_hole = create_synthetic_bipolar_template(25, 29)
    base_h, base_w = base_tpl.shape[:2]

    candidate_boxes = []
    candidate_scores = []

    for scale in scales:
        sw = max(15, int(round(base_w * scale)))
        sh = max(17, int(round(base_h * scale)))

        tpl = cv2.resize(base_tpl, (sw, sh), interpolation=cv2.INTER_LINEAR)
        mask = cv2.resize(base_mask, (sw, sh), interpolation=cv2.INTER_NEAREST)
        ring_m = cv2.resize(base_ring, (sw, sh), interpolation=cv2.INTER_NEAREST)
        border_m = cv2.resize(base_border, (sw, sh), interpolation=cv2.INTER_NEAREST)
        hole_m = cv2.resize(base_hole, (sw, sh), interpolation=cv2.INTER_NEAREST)

        # 在 float32 特征图上执行带掩膜的零均值归一化互相关
        res = cv2.matchTemplate(feat_map, tpl, cv2.TM_CCOEFF_NORMED, mask=mask)
        res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)

        loc_y, loc_x = np.where(res >= score_thresh)
        for y, x in zip(loc_y, loc_x):
            hsv_patch = hsv[y:y+sh, x:x+sw]
            if verify_marker_physics(hsv_patch, ring_m, border_m, hole_m):
                candidate_boxes.append([int(x), int(y), int(sw), int(sh)])
                candidate_scores.append(float(res[y, x]))

    # 跨尺度非极大值抑制 (NMS)
    indices = cv2.dnn.NMSBoxes(candidate_boxes, candidate_scores, score_threshold=score_thresh, nms_threshold=0.25)

    detections = []
    if len(indices) > 0:
        for idx in indices.flatten():
            x, y, w, h = candidate_boxes[idx]
            detections.append({
                "bbox": (x, y, w, h),
                "center": (x + w // 2, y + h // 2),
                "score": round(candidate_scores[idx], 3)
            })

    detections.sort(key=lambda d: d["score"], reverse=True)
    return detections


if __name__ == "__main__":
    # 无需截取任何模板，直接对图1（蓝标）和图2（黄标）进行检测
    for img_path in [r"C:\Users\27321\Desktop\2.png"]:
        img = cv2.imread(img_path)
        if img is None:
            continue
        results = detect_markers_robust(img)
        print(f"=== {img_path} 检出 {len(results)} 个目标 ===")
        vis = img.copy()
        for i, det in enumerate(results, 1):
            x, y, w, h = det["bbox"]
            print(f"  目标 {i}: 中心={det['center']}, 边界框={det['bbox']}, 得分={det['score']}")
            cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(vis, f"#{i} ({det['score']})", (x, max(15, y - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
        cv2.imshow(img_path, vis)
    cv2.waitKey(0)