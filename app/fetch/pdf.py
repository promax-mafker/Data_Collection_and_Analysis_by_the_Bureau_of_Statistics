import io

import pdfplumber


def is_pdf_bytes(data: bytes) -> bool:
    return data[:4] == b"%PDF"


def extract_pdf_text(data: bytes) -> str:
    """从 PDF 字节提取逐页文字（文字型 PDF；扫描版返回空或极少文字）。"""
    pages = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                pages.append(t)
    return "\n".join(pages)
