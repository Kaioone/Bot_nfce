import os
import pytesseract
from PIL import Image

os.environ["TESSDATA_PREFIX"] = r"C:\Program Files\Tesseract-OCR\tessdata"

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

print(pytesseract.get_languages())

texto = pytesseract.image_to_string(Image.open("teste.jpg"), lang="por")

print(texto)