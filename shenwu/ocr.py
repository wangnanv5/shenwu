from rapidocr_onnxruntime import RapidOCR

class Ocr:
    def __init__(self):
        self.engine = RapidOCR()
        # self.engine = RapidOCR(det_use_cuda=True, cls_use_cuda=True, rec_use_cuda=True)
    def get_ocr_from_image(self, img, target_texts,return_all=False):
        """
        :param img: 输入图像
        :param target_texts: 目标文本列表，如 ['姓名', '年龄', '地址']；也兼容单字符串输入
        """
        # 兼容单字符串传入
        if isinstance(target_texts, str):
            target_texts = [target_texts]

        ocr_results, _ = self.engine(img)
        if not ocr_results:
            return []

        # 只要包含 target_texts 中的任意一个，就加入结果
        found = [
            (box, text, score) 
            for box, text, score in ocr_results 
            if any(target in text for target in target_texts)
        ]

        if return_all:
            return found,ocr_results
        else:
            return found