from rapidocr_onnxruntime import RapidOCR

class Ocr:
    def __init__(self):
        self.engine = RapidOCR()

    def get_ocr_from_image(self, img,target_text):
        text, boxes = self.engine(img)
        found = [(box, text, score) for box, text, score in text if target_text in text]
        return found