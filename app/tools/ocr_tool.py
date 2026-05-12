"""
文件: tools/ocr_tool.py | 图片 OCR 工具
职责: 对图片进行文字识别，提取文本内容

使用: pytesseract (Google Tesseract OCR 的 Python 封装)

OCRC 技术原理:
  图片 → 预处理(灰度/二值化) → 字符分割 → 特征提取 → 模式匹配 → 文本

限制:
  - Tesseract 需要系统级安装（pip 只装客户端不行）
  - 对复杂排版(多栏/表格/手写体)效果一般
  - 中英文混合识别需要指定 chi_sim+eng 语言包

替代方案:
  - EasyOCR: 深度学习驱动，准确率更高，但需要 PyTorch(~1GB)
  - PaddleOCR: 中文识别最强，但部署复杂
  - 云服务(阿里云/腾讯云 OCR): 准确率高，但有网络延迟和费用
"""

import os
try:
    from PIL import Image    # Python 图像处理标准库
except ImportError:
    Image = None

try:
    import pytesseract       # Tesseract OCR 的 Python 接口
except ImportError:
    pytesseract = None

from .registry import registry


def ocr_image(file_path: str, lang: str = "chi_sim+eng") -> dict:
    """
    对图片进行 OCR 文字识别

    参数:
      file_path: 图片文件路径
      lang: 识别语言，默认中英文混合
            chi_sim = 简体中文, eng = 英文
            "+" 表示多语言同时识别

    返回:
      {"text": 识别出的文本, "metadata": {图片信息}}
    """
    # 防御性检查: 依赖未安装时给出明确提示
    if pytesseract is None:
        return {"text": "[pytesseract 未安装，无法 OCR]", "metadata": {}}
    if Image is None:
        return {"text": "[Pillow 未安装，无法处理图片]", "metadata": {}}

    try:
        # Pillow 读取图片 → Tesseract 识别文字
        img = Image.open(file_path)
        text = pytesseract.image_to_string(img, lang=lang)
        return {
            "text": text.strip(),
            "metadata": {
                "format": img.format,     # PNG/JPEG/GIF
                "size": img.size,         # (宽度, 高度) 像素
                "mode": img.mode,         # RGB/RGBA/L(灰度)
                "lang": lang,
            },
        }
    except Exception as e:
        return {"text": "", "metadata": {}, "error": str(e)}


# === 注册工具 ===
registry.register(
    ocr_image, "ocr_image",
    "对图片进行 OCR 文字识别，支持中英文",
    {"file_path": "图片文件路径", "lang": "识别语言（默认 chi_sim+eng）"},
    agent="parser",
)
