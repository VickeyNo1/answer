"""文档解析器：支持 PDF、Word、TXT 文件解析与文本切分"""
import os
from pypdf import PdfReader
from docx import Document


def parse_file(file_path: str) -> str:
    """解析文件，提取全部文本内容"""
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        return _parse_pdf(file_path)
    elif ext == ".docx":
        return _parse_docx(file_path)
    elif ext == ".txt":
        return _parse_txt(file_path)
    else:
        raise ValueError(f"不支持的文件格式: {ext}")


def _parse_pdf(file_path: str) -> str:
    reader = PdfReader(file_path)
    texts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            texts.append(text)
    return "\n".join(texts)


def _parse_docx(file_path: str) -> str:
    doc = Document(file_path)
    return "\n".join(para.text for para in doc.paragraphs if para.text.strip())


def _parse_txt(file_path: str) -> str:
    # 尝试多种编码
    for encoding in ["utf-8", "gbk", "gb2312", "utf-16"]:
        try:
            with open(file_path, "r", encoding=encoding) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError("无法识别文件编码")


def chunk_text(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[str]:
    """将文本切分为固定大小的片段，带重叠"""
    if not text or not text.strip():
        return []

    # 清理多余空白
    text = text.strip()
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        # 如果不是最后一个片段，尝试在句号/换行处断开
        if end < len(text):
            # 在 chunk_size 范围内寻找最佳断点
            best_break = -1
            for sep in ["\n\n", "\n", "。", "！", "？", ".", "!", "?", "；", ";"]:
                idx = text.rfind(sep, start + chunk_size // 2, end)
                if idx > best_break:
                    best_break = idx

            if best_break > start:
                end = best_break + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # 移动起始位置（减去重叠部分）
        start = end - chunk_overlap
        if start <= (end - chunk_size) and start < len(text):
            start = end  # 防止死循环

    return chunks
