import ctypes
ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

from shenwu.controller_cv import GameController

# 修炼任务 当购买的物品是去药店购买时，会卡住
if __name__ == '__main__':
    game_controller = GameController()
    # game_controller.check_qu_mo()
    game_controller.run_xiu_ye()
    game_controller.run_xiu_lian()
    # game_controller.test_resources()

# import cv2
# import numpy as np
# import mss
# hwnd_list = []
# import win32gui
# import win32con
# import time
# from shenwu.utils import make_mss_region,human_delay

# ROI = None

# def get_hwnd(hwnd, extra):
#     title = win32gui.GetWindowText(hwnd)
#     if ("幻唐志" in title) and ("RENDER" not in title):
#         hwnd_list.append(hwnd)


# def build_ring_template(template_bgr):
#     """
#     从单张标记小图（如蓝色1号图标）构建 V 通道模板与水滴环形掩膜 (Ring Mask)
#     """
#     th, tw = template_bgr.shape[:2]
#     tpl_hsv = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2HSV)
#     tpl_v = tpl_hsv[:, :, 2]  # 提取明度通道（跨颜色不变）

#     # 1. 提取模板中水滴图标的外轮廓（此处以蓝色模板为例提取初始形状，也可直接用几何绘制）
#     base_mask = cv2.inRange(tpl_hsv, np.array([95, 100, 120]), np.array([120, 255, 255]))
#     cnts, _ = cv2.findContours(base_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
#     outer_mask = np.zeros((th, tw), dtype=np.uint8)
#     cv2.drawContours(outer_mask, cnts, -1, 255, -1)

#     # 2. 向外膨胀 1 像素，把图标外圈 1px 的深色描边过渡带纳入特征区（大幅提升跨颜色区分度）
#     ring_mask = cv2.dilate(outer_mask, np.ones((3, 3), np.uint8), iterations=1)

#     # 3. 挖空内部数字区域（圆心位于宽度的 1/2、高度约 42% 处，挖空半径 5px）
#     digit_cx, digit_cy = tw // 2, int(th * 0.48)
#     cv2.circle(ring_mask, (digit_cx, digit_cy), 5, 0, -1)

#     return tpl_v, ring_mask

# def build_ring_template_fixed(template_bgr, pad=2):
#     """
#     修复版：
#     1. 自动向外扩充 pad=2 像素，确保紧贴裁剪的模板也能包含水滴外圈的深色描边带
#     2. 将水滴环内部強制抹平为 255，外圈 2px 描边设为 0，彻底消除“内亮外暗 vs 外亮内暗”的纹理冲突
#     """
#     # 1. 给紧贴裁剪的模板四周扩充 pad 个像素（保证外圈有空间容纳 2px 的描边掩膜）
#     padded_bgr = cv2.copyMakeBorder(template_bgr, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
#     th, tw = padded_bgr.shape[:2]
    
#     tpl_hsv = cv2.cvtColor(padded_bgr, cv2.COLOR_BGR2HSV)

#     # 2. 提取模板中水滴的实心外轮廓（不直接膨胀进有效环，而是严格区分“水滴内”与“水滴外”）
#     # 若你的模板是蓝标用 [95, 80, 120]~[120, 255, 255]；若用通用高饱和度提取可用 [0, 80, 120]~[180, 255, 255]
#     base_mask = cv2.inRange(tpl_hsv, np.array([95, 100, 120]), np.array([120, 255, 255]))
#     # 把四周刚 pad 出来的边缘清零，防止贴边像素干扰外轮廓提取
#     base_mask[:pad, :] = 0; base_mask[-pad:, :] = 0
#     base_mask[:, :pad] = 0; base_mask[:, -pad:] = 0

#     cnts, _ = cv2.findContours(base_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
#     body_mask = np.zeros((th, tw), dtype=np.uint8)
#     if cnts:
#         max_cnt = max(cnts, key=cv2.contourArea)
#         cv2.drawContours(body_mask, [max_cnt], -1, 255, -1)

#     # 3. 挖空中心数字区域（圆心位于宽度的 1/2，高度约 41% 处，半径设为 6px 以兼容偏大的数字）
#     hole_mask = np.zeros((th, tw), dtype=np.uint8)
#     digit_cx, digit_cy = tw // 2, int(round(th * 0.41))
#     cv2.circle(hole_mask, (digit_cx, digit_cy), 6, 255, -1)

#     # 水滴纯净亮环 = 水滴实心体 - 中心数字孔洞
#     ring_body = cv2.subtract(body_mask, hole_mask)

#     # 4. 生成水滴外围 2 像素的深色描边参考带 (outer_border)
#     kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
#     dilated_body = cv2.dilate(body_mask, kernel, iterations=1)
#     outer_border = cv2.subtract(dilated_body, body_mask)

#     # 5. 组合最终的 ring_mask = 水滴亮环 + 外圈2px描边带（中心数字与四角远处背景为 0）
#     ring_mask = cv2.bitwise_or(ring_body, outer_border)

#     # 6. 【核心修复】不要用原图的 tpl_v！构造抹平内部纹理的理想阶跃模板：
#     # 水滴亮环内统一设为 255.0，外圈 2px 描边统一设为 0.0
#     tpl_ideal = np.zeros((th, tw), dtype=np.float32)
#     tpl_ideal[ring_body > 0] = 255.0
#     tpl_ideal[outer_border > 0] = 0.0

#     return tpl_ideal, ring_mask

# def detect_markers_color_agnostic(target_bgr, tpl_v, ring_mask, threshold=0.68):
#     """
#     跨颜色、跨数字检测水滴标记（已修复 float32 类型对齐与 mss 4通道兼容）
#     """
#     # 兼容 mss 截取的 BGRA 4通道图像，直接切片取前3通道 BGR
#     if target_bgr.shape[2] == 4:
#         target_bgr = target_bgr[:, :, :3]

#     th, tw = tpl_v.shape[:2]
#     hsv = cv2.cvtColor(target_bgr, cv2.COLOR_BGR2HSV)

#     # 融合 70% 明度(V) + 30% 饱和度(S)，并在最后显式转为 np.float32（防止变成 float64）
#     target_feat = (0.7 * hsv[:, :, 2] + 0.3 * hsv[:, :, 1]).astype(np.float32)
#     tpl_v = tpl_v.astype(np.float32)
#     ring_mask = ring_mask.astype(np.uint8)

#     # 执行带掩膜的归一化互相关匹配
#     res = cv2.matchTemplate(target_feat, tpl_v, cv2.TM_CCOEFF_NORMED, mask=ring_mask)
#     res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)

#     loc_y, loc_x = np.where(res >= threshold)
#     scores = res[loc_y, loc_x]

#     boxes = [[int(x), int(y), int(tw), int(th)] for x, y in zip(loc_x, loc_y)]
#     indices = cv2.dnn.NMSBoxes(boxes, scores.tolist(), score_threshold=threshold, nms_threshold=0.3)

#     detections = []
#     if len(indices) > 0:
#         for idx in indices.flatten():
#             x, y, w, h = boxes[idx]
#             detections.append({
#                 "bbox": (x, y, w, h),
#                 "center": (x + w // 2, y + h // 2),
#                 "score": round(float(scores[idx]), 3)
#             })

#     detections.sort(key=lambda d: d["score"], reverse=True)
#     return detections


# def extract_template_outer_contour(template_bgr, pad=3):
#     """
#     步骤1：从裁剪的水滴模板中仅提取【最外层水滴轮廓】，彻底剔除内部数字！
#     返回：
#       - tpl_edge_soft: 柔化后的模板纯净外轮廓图 (float32)
#       - contour_band_mask: 仅包裹水滴外轮廓线的窄带掩膜 (uint8)，内部数字区为0
#       - tpl_cnt: 模板的外轮廓点集（可用于后续画图或 matchShapes）
#     """
#     if template_bgr.shape[2] == 4:
#         template_bgr = template_bgr[:, :, :3]

#     # 先给紧贴边缘的模板(如23x27)四周补一圈黑边，防止外轮廓贴边断裂
#     th_raw, tw_raw = template_bgr.shape[:2]
#     hsv_raw = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2HSV)
    
#     # 提取水滴主体（利用高饱和度+高明度，兼容蓝/黄/红/绿任意颜色水滴）
#     binary = cv2.inRange(hsv_raw, np.array([0, 70, 110]), np.array([180, 255, 255]))
    
#     # 形态学闭运算填平内部数字造成的缝隙，确保外轮廓完整闭合
#     kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
#     binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
    
#     # 四周补黑边 pad 像素
#     binary_padded = cv2.copyMakeBorder(binary, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
#     th, tw = binary_padded.shape[:2]

#     # 【核心】使用 RETR_EXTERNAL 仅提取最外层水滴轮廓，100% 忽略内部数字轮廓！
#     cnts, _ = cv2.findContours(binary_padded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
#     if not cnts:
#         raise ValueError("未能从模板中提取到水滴外轮廓，请检查模板图片！")
#     tpl_cnt = max(cnts, key=cv2.contourArea)

#     # 在纯黑画布上仅绘制最外层水滴轮廓（线宽为 1）
#     tpl_edge = np.zeros((th, tw), dtype=np.uint8)
#     cv2.drawContours(tpl_edge, [tpl_cnt], -1, 255, thickness=1)

#     # 对模板轮廓做 3x3 高斯柔化，转化为 float32 柔性轮廓特征
#     tpl_edge_soft = cv2.GaussianBlur(tpl_edge, (3, 3), 0).astype(np.float32)

#     # 生成“轮廓走廊掩膜”（线宽设为 5，仅计算水滴边界内外各2像素的重合度，内部数字区全为0）
#     contour_band_mask = np.zeros((th, tw), dtype=np.uint8)
#     cv2.drawContours(contour_band_mask, [tpl_cnt], -1, 255, thickness=5)

#     return tpl_edge_soft, contour_band_mask, tpl_cnt


# def image_to_contour_map(img_bgr):
#     """
#     步骤2：将游戏大图处理成轮廓图（边缘强度图）
#     使用 BGR 三通道最大 Canny 边缘 + 3x3 高斯柔化，确保任何颜色的水滴外框都能清晰提取
#     """
#     if img_bgr.shape[2] == 4:
#         img_bgr = img_bgr[:, :, :3]

#     # 分别计算 B、G、R 三个通道的 Canny 边缘并取最大值（比转灰度图更能保留彩色图标边缘）
#     b, g, r = cv2.split(img_bgr)
#     edge_b = cv2.Canny(b, 50, 150)
#     edge_g = cv2.Canny(g, 50, 150)
#     edge_r = cv2.Canny(r, 50, 150)
#     edge_max = cv2.bitwise_or(cv2.bitwise_or(edge_b, edge_g), edge_r)

#     # 同样做 3x3 高斯柔化，容忍 1 像素的位置抖动
#     target_edge_soft = cv2.GaussianBlur(edge_max, (3, 3), 0).astype(np.float32)
#     return target_edge_soft, edge_max


# def match_by_contour_map(frame_bgr, tpl_edge_soft, contour_band_mask, threshold=0.55):
#     """
#     步骤3：在大图轮廓图上匹配模板的外轮廓，并用水滴内部鲜艳度过滤复杂背景线条
#     """
#     if frame_bgr.shape[2] == 4:
#         frame_bgr = frame_bgr[:, :, :3]

#     th, tw = tpl_edge_soft.shape[:2]
#     target_edge_soft, raw_edge_vis = image_to_contour_map(frame_bgr)

#     # 在轮廓走廊掩膜内计算模板轮廓与大图轮廓的相似度
#     res = cv2.matchTemplate(target_edge_soft, tpl_edge_soft, cv2.TM_CCOEFF_NORMED, mask=contour_band_mask)
#     res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)

#     loc_y, loc_x = np.where(res >= threshold)
#     hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)

#     boxes, scores = [], []
#     for y, x in zip(loc_y, loc_x):
#         # 轻量校验：水滴内部应该是有颜色的高亮图标（排除地图上刚好围成圆形的灰暗石头边缘）
#         patch_hsv = hsv[y+4:y+th-4, x+4:x+tw-4]
#         if np.mean(patch_hsv[:, :, 1]) > 70 and np.mean(patch_hsv[:, :, 2]) > 140:
#             boxes.append([int(x), int(y), int(tw), int(th)])
#             scores.append(float(res[y, x]))

#     indices = cv2.dnn.NMSBoxes(boxes, scores, score_threshold=threshold, nms_threshold=0.3)
#     detections = []
#     if len(indices) > 0:
#         for idx in indices.flatten():
#             x, y, w, h = boxes[idx]
#             detections.append({
#                 "bbox": (x, y, w, h),
#                 "center": (x + w // 2, y + h // 2),
#                 "score": round(scores[idx], 3)
#             })

#     detections.sort(key=lambda d: d["score"], reverse=True)
#     return detections, raw_edge_vis

# import cv2
# import numpy as np
# import mss

# def load_template_contour_from_png(png_path):
#     """
#     1. 读取你的 3.png，仅提取最外层水滴轮廓（自动丢弃中间的黑洞内轮廓）
#     """
#     # 以灰度模式读取 3.png 并二值化
#     tpl_gray = cv2.imread(png_path, cv2.IMREAD_GRAYSCALE)
#     if tpl_gray is None:
#         raise FileNotFoundError(f"找不到模板文件: {png_path}")
    
#     _, binary = cv2.threshold(tpl_gray, 127, 255, cv2.THRESH_BINARY)
#     th, tw = binary.shape[:2]

#     # 【关键】使用 RETR_EXTERNAL：只提取水滴最外圈轮廓，完全忽略中间挖空的黑洞！
#     cnts, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
#     outer_cnt = max(cnts, key=cv2.contourArea)

#     # 在纯黑画布上画出 1 像素宽的纯净水滴外轮廓
#     tpl_contour_img = np.zeros((th, tw), dtype=np.uint8)
#     cv2.drawContours(tpl_contour_img, [outer_cnt], -1, 255, thickness=1)

#     # 轻微高斯模糊转为 float32（让 1px 轮廓线具有 1~2px 的容错缓冲）
#     tpl_contour_soft = cv2.GaussianBlur(tpl_contour_img, (3, 3), 0).astype(np.float32)

#     # 生成“外轮廓窄带掩膜”：仅沿着水滴外轮廓线取 5px 宽的区域参与计算，内部数字区域全为 0
#     contour_mask = np.zeros((th, tw), dtype=np.uint8)
#     cv2.drawContours(contour_mask, [outer_cnt], -1, 255, thickness=5)

#     return tpl_contour_soft, contour_mask, outer_cnt


# def detect_by_contour_matching(frame_bgr, tpl_contour_soft, contour_mask, threshold=0.52):
#     """
#     2. 将游戏画面处理成轮廓图，并用 3.png 的外轮廓进行匹配
#     """
#     if frame_bgr.shape[2] == 4:
#         frame_bgr = frame_bgr[:, :, :3]

#     th, tw = tpl_contour_soft.shape[:2]

#     # 对 B、G、R 三通道分别提取 Canny 轮廓并合并（确保蓝、黄、红、绿任何颜色的水滴边缘都不丢失）
#     b, g, r = cv2.split(frame_bgr)
#     edge_b = cv2.Canny(b, 50, 150)
#     edge_g = cv2.Canny(g, 50, 150)
#     edge_r = cv2.Canny(r, 50, 150)
#     frame_contour_img = cv2.bitwise_or(cv2.bitwise_or(edge_b, edge_g), edge_r)

#     # 同样做 3x3 高斯柔化并转为 float32
#     frame_contour_soft = cv2.GaussianBlur(frame_contour_img, (3, 3), 0).astype(np.float32)

#     # 用模板外轮廓在大图轮廓图上滑窗匹配
#     res = cv2.matchTemplate(frame_contour_soft, tpl_contour_soft, cv2.TM_CCOEFF_NORMED, mask=contour_mask)
#     res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)

#     loc_y, loc_x = np.where(res >= threshold)
#     boxes = [[int(x), int(y), int(tw), int(th)] for x, y in zip(loc_x, loc_y)]
#     scores = res[loc_y, loc_x].tolist()

#     # 非极大值抑制 (NMS) 去除重叠框
#     indices = cv2.dnn.NMSBoxes(boxes, scores, score_threshold=threshold, nms_threshold=0.3)

#     detections = []
#     if len(indices) > 0:
#         for idx in indices.flatten():
#             x, y, w, h = boxes[idx]
#             detections.append({
#                 "bbox": (x, y, w, h),
#                 "center": (x + w // 2, y + h // 2),
#                 "score": round(scores[idx], 3)
#             })

#     detections.sort(key=lambda d: d["score"], reverse=True)
#     return detections, frame_contour_img

# def detect_by_match_shapes(frame_bgr, outer_cnt, max_dist=0.15):
#     """
#     使用 cv2.matchShapes 直接比对大图中候选外轮廓与 3.png 外轮廓的几何形状
#     """
#     if frame_bgr.shape[2] == 4:
#         frame_bgr = frame_bgr[:, :, :3]

#     _, _, tw, th = cv2.boundingRect(outer_cnt)

#     # 1. 提取画面中所有高饱和度、高明度的鲜艳图标区域（不限颜色 H: 0~180）
#     hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
#     mask = cv2.inRange(hsv, np.array([0, 80, 130]), np.array([180, 255, 255]))

#     # 闭运算填平内部数字空隙，提取所有候选物体的最外层轮廓
#     kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
#     mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
#     cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

#     detections = []
#     for cnt in cnts:
#         x, y, w, h = cv2.boundingRect(cnt)
#         # 过滤掉尺寸与 3.png 差距过大的轮廓（允许 ±30% 尺寸浮动）
#         if not (0.7 * tw <= w <= 1.3 * tw and 0.7 * th <= h <= 1.3 * th):
#             continue

#         # 计算与 3.png 外轮廓的 Hu 矩形状距离（返回值越小代表形状越一致，0 为完全相同）
#         dist = cv2.matchShapes(cnt, outer_cnt, cv2.CONTOURS_MATCH_I1, 0.0)
#         if dist <= max_dist:
#             detections.append({
#                 "bbox": (x, y, w, h),
#                 "center": (x + w // 2, y + h // 2),
#                 "dist": round(dist, 4)  # 越小越好
#             })

#     detections.sort(key=lambda d: d["dist"])
#     return detections

# if __name__ == "__main__":
#     hwnd_list.clear()
#     win32gui.EnumWindows(get_hwnd, None)
#     tpl_contour_soft, contour_mask, outer_cnt = load_template_contour_from_png(r"C:\Users\27321\Desktop\3.png")

#     if not hwnd_list:
#         raise RuntimeError("没有找到目标窗口：幻唐志")

#     hwnd = hwnd_list[0]

#     try:
#         win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
#         win32gui.SetForegroundWindow(hwnd)
#     except Exception as e:
#         print("置前窗口失败，继续尝试截图：", e)

#     human_delay(1)

#     tpl_patch_1 = cv2.imread(r"C:\Users\27321\Desktop\1.png")
#     tpl_patch_2 = cv2.imread(r"C:\Users\27321\Desktop\2.png")
#     # tpl_patch_3 = cv2.imread(r"C:\Users\27321\Desktop\3.png")

#     with mss.mss() as sct:
#         while True:
#             try:
#                 # 每帧重新获取窗口区域，窗口移动也能跟上
#                 region = make_mss_region(hwnd, ROI)
#             except Exception as e:
#                 print(e)
#                 time.sleep(1)
#                 continue

#             # 只捕获指定窗口区域
#             shot = sct.grab(region)

#             frame = np.array(shot)
#             frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

#             # results_a, edge_map = detect_by_match_shapes(frame, tpl_contour_soft, contour_mask, threshold=0.4)
#             results_b = detect_by_match_shapes(frame, outer_cnt, max_dist=0.15)
#             # 在图像上绘制结果
#             vis_img = frame.copy()
#             for idx, det in enumerate(results_b, 1):
#                 x, y, w, h = det["bbox"]
#                 cx, cy = det["center"]
#                 # score = det["score"]

#                 # 绘制外接矩形框
#                 cv2.rectangle(vis_img, (x, y), (x + w, y + h), (0, 255, 0), 2)
#                 # 绘制中心定位点
#                 cv2.circle(vis_img, (cx, cy), 4, (0, 0, 255), -1)
#                 # 绘制标签文字（编号、置信度、中心坐标）
#                 # label = f"#{idx} ({score}) [{cx},{cy}]"
#                 # cv2.putText(vis_img, label, (x, max(18, y - 6)),
#                 #             cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)

#             # 使用 OpenCV 窗口展示
#             cv2.imshow("Waterdrop Marker Detection", vis_img)

#             # 检测到按键 'q' 时退出循环
#             if cv2.waitKey(1) & 0xFF == ord('q'):
#                 break

#             # tpl_v, ring_mask = build_ring_template_fixed(tpl_patch_1)
#             # results = detect_markers_color_agnostic(frame, tpl_v, ring_mask, threshold=0.7)

#             # vis = frame.copy()
#             # for i, det in enumerate(results, 1):
#             #     x, y, w, h = det["bbox"]
#             #     score = det["score"]
#             #     cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 255, 0), 2)
#             #     cv2.putText(vis, f"Marker_{i:02d} ({int(score*100)}%)", (x, max(15, y - 6)),
#             #                 cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA)
                
#             # cv2.imshow("Cross-Color Detection", vis)

#             # key = cv2.waitKey(1) & 0xFF
#             # if key == ord("q"):
#             #     break

#     cv2.destroyAllWindows()    