"""YOLOv8 ONNX 目标检测器（end2end 输出 (N, 6)，NMS 已在图内完成）。

职责边界：只做「一帧 BGR 图 -> 检测结果 / 目标中心坐标」的纯计算，
不涉及窗口枚举、截屏、绘制、显示 —— 那些由调用方负责（yolo_test.py
做实时预览，controller_cv 在业务流程里取中心坐标）。

输入：BGR 3 通道 ndarray（用 grab_frame(region, "bgr") 抓帧；灰度帧能跑
——cv2 会自动复制成 3 通道——但会丢失颜色信息，检测精度下降，别这么传）
输出：
    detect(frame)        -> [(x1, y1, x2, y2, conf, class_id), ...]  帧内像素坐标
    detect_centers(frame)-> [(cx, cy), ...]                          目标中心点，帧内像素坐标

无目标时两个方法都返回空列表 []。
"""

from __future__ import annotations

import cv2
import numpy as np
import onnxruntime as ort

from shenwu import config


def default_onnx_model() -> str:
    """默认模型路径：固定在 resource/Common/YOLO/ 下，与游戏主题无关"""
    return str(config.yolo_model_path)


class YoloDetector:
    """YOLOv8 目标检测器，推理 session 只在构造时加载一次。"""

    classes = ["icon"]

    def __init__(self, onnx_model: str | None = None, confidence_thres: float = 0.5):
        # 不传模型路径时使用当前主题的默认模型
        onnx_model = onnx_model or default_onnx_model()
        self.onnx_model = onnx_model
        self.confidence_thres = confidence_thres

        available = ort.get_available_providers()
        providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in available]
        self.session = ort.InferenceSession(onnx_model, providers=providers or available)
        msg = f"✅ YOLO 模型加载完成，推理后端：{self.session.get_providers()}"
        try:
            print(msg)
        except UnicodeEncodeError:  # GBK 控制台打不出 emoji 时降级输出，不中断初始化
            print("YOLO model loaded, providers: " + ", ".join(self.session.get_providers()))

        model_inputs = self.session.get_inputs()
        self.input_name = model_inputs[0].name  # 缓存输入名，避免每帧查询
        _, _, height, width = model_inputs[0].shape
        self.input_height = height if isinstance(height, int) else 640
        self.input_width = width if isinstance(width, int) else 640

    def letterbox(self, img: np.ndarray, new_shape: tuple[int, int]) -> tuple[np.ndarray, tuple[int, int]]:
        """保持长宽比缩放并补边，返回 (图, (top, left) padding)。"""
        shape = img.shape[:2]

        r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])

        new_unpad = round(shape[1] * r), round(shape[0] * r)
        dw, dh = (new_shape[1] - new_unpad[0]) / 2, (new_shape[0] - new_unpad[1]) / 2

        if shape[::-1] != new_unpad:
            img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)
        top, bottom = round(dh - 0.1), round(dh + 0.1)
        left, right = round(dw - 0.1), round(dw + 0.1)
        img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114))

        return img, (top, left)

    def detect(self, frame: np.ndarray) -> list[tuple[float, float, float, float, float, int]]:
        """对一帧 BGR 图做检测，返回 [(x1, y1, x2, y2, conf, class_id), ...]（帧内像素坐标）。"""
        h0, w0 = frame.shape[:2]

        img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img, pad = self.letterbox(img, (self.input_height, self.input_width))

        image_data = np.asarray(img) / 255.0
        image_data = np.transpose(image_data, (2, 0, 1))  # Channel first
        image_data = image_data[None].astype(np.float32)

        outputs = self.session.run(None, {self.input_name: image_data})
        return self._postprocess(outputs, pad, (w0, h0))

    def detect_centers(self, frame: np.ndarray) -> list[tuple[int, int]]:
        """返回帧内所有目标的中心坐标 [(cx, cy), ...]；无目标返回 []。"""
        return [(int((x1 + x2) / 2), int((y1 + y2) / 2))
                for x1, y1, x2, y2, _, _ in self.detect(frame)]

    def _postprocess(self, output: list[np.ndarray], pad: tuple[int, int],
                     orig_size: tuple[int, int]) -> list[tuple[float, float, float, float, float, int]]:
        """(1, 300, 6) end2end 输出：[x1, y1, x2, y2, conf, cls]，还原到原图坐标。"""
        w0, h0 = orig_size
        det = np.squeeze(output[0])                  # (300, 6)，不要 transpose！
        if det.ndim != 2 or det.shape[1] != 6:
            raise RuntimeError(f"预期 (N, 6) 输出，实际 {det.shape}")

        # 1) 按置信度过滤
        det = det[det[:, 4] >= self.confidence_thres]
        if det.size == 0:
            return []

        boxes = det[:, :4].astype(np.float32)        # xyxy，letterbox 640 空间
        confs = det[:, 4]
        cls_ids = det[:, 5].astype(int)

        # 2) letterbox 坐标 → 原图坐标（扣 padding，再除以缩放比）
        gain = min(self.input_height / h0, self.input_width / w0)
        boxes[:, [0, 2]] = (boxes[:, [0, 2]] - pad[1]) / gain
        boxes[:, [1, 3]] = (boxes[:, [1, 3]] - pad[0]) / gain

        # 3) 裁剪到图像范围内
        boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, w0 - 1)
        boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, h0 - 1)

        return [(x1, y1, x2, y2, float(c), int(cid))
                for (x1, y1, x2, y2), c, cid in zip(boxes, confs, cls_ids)]
