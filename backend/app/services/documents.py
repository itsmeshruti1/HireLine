"""Bounded text extraction. Scanned documents deliberately require correction."""

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from pypdf import PdfReader

MAX_BYTES = 5 * 1024 * 1024
MAX_PAGES = 30
MAX_TEXT = 100_000


def extract_document(filename: str, content: bytes) -> list[dict]:
    if not content or len(content) > MAX_BYTES:
        raise ValueError("Upload a non-empty PDF or DOCX smaller than 5 MB.")
    extension = Path(filename).suffix.lower()
    try:
        if extension == ".pdf":
            if not content.startswith(b"%PDF-"):
                raise ValueError("This file is not a valid PDF.")
            reader = PdfReader(BytesIO(content), strict=False)
            if reader.is_encrypted:
                raise ValueError("Password-protected PDFs are not supported. Upload an unlocked copy.")
            if len(reader.pages) > MAX_PAGES:
                raise ValueError("Resume PDFs may contain at most 30 pages.")
            segments = [{"id": f"page-{index + 1}", "text": page.extract_text() or ""}
                        for index, page in enumerate(reader.pages)]
        elif extension == ".docx":
            with ZipFile(BytesIO(content)) as archive:
                infos = archive.infolist()
                if len(infos) > 1000 or sum(item.file_size for item in infos) > 20 * 1024 * 1024:
                    raise ValueError("The DOCX expands beyond the supported document size.")
                if "word/document.xml" not in archive.namelist():
                    raise ValueError("This file is not a valid DOCX.")
            document = Document(BytesIO(content))
            texts = [paragraph.text for paragraph in document.paragraphs]
            for table in document.tables:
                texts.extend(" | ".join(cell.text for cell in row.cells) for row in table.rows)
            segments = [{"id": f"paragraph-{index + 1}", "text": text}
                        for index, text in enumerate(texts) if text.strip()]
        else:
            raise ValueError("Only PDF and DOCX resume files are supported.")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("The document could not be read. Upload a valid, unlocked PDF or DOCX.") from exc
    segments = [{"id": segment["id"], "text": segment["text"].replace("\x00", "").strip()}
                for segment in segments if segment["text"].strip()]
    if sum(len(segment["text"]) for segment in segments) > MAX_TEXT:
        raise ValueError("The extracted resume exceeds 100,000 characters.")
    if sum(len(segment["text"].strip()) for segment in segments) < 30:
        raise ValueError("No readable resume text was found. Scanned PDFs need a text-based replacement; OCR is not enabled.")
    return segments
