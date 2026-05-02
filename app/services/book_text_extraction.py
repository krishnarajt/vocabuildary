"""Extract plain text from uploaded books and reduce it to word counts."""

from __future__ import annotations

import re
import shutil
from collections import Counter
from pathlib import Path

import mobi
from bs4 import BeautifulSoup
from ebooklib import ITEM_DOCUMENT, epub
from pypdf import PdfReader

from app.services.book_storage_service import get_file_extension

WORD_RE = re.compile(r"[^\W\d_]+(?:['\u2019][^\W\d_]+)*", re.UNICODE)


class BookTextExtractionError(RuntimeError):
    """Raised when a source document cannot be parsed into text."""


def count_words(text: str) -> dict[str, int]:
    """Return a normalized word -> count map from arbitrary extracted text."""
    counts: Counter[str] = Counter()
    for match in WORD_RE.finditer(text):
        word = match.group(0).replace("\u2019", "'").casefold().strip("'")
        if word:
            counts[word] += 1
    return dict(counts)


def extract_text_from_book(path: Path | str, extension: str | None = None) -> str:
    source_path = Path(path)
    normalized_extension = (extension or get_file_extension(source_path.name)).lower()

    try:
        if normalized_extension == "pdf":
            return extract_text_from_pdf(source_path)
        if normalized_extension == "epub":
            return extract_text_from_epub(source_path)
        if normalized_extension == "mobi":
            return extract_text_from_mobi(source_path)
    except Exception as exc:
        raise BookTextExtractionError(
            f"Failed to extract text from {normalized_extension.upper()} book."
        ) from exc

    raise BookTextExtractionError(f"Unsupported book format: {normalized_extension}.")


def extract_text_from_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_text_from_epub(path: Path) -> str:
    book = epub.read_epub(str(path))
    chunks: list[str] = []
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        html = item.get_content()
        soup = BeautifulSoup(html, "html.parser")
        chunks.append(soup.get_text(" "))
    return "\n".join(chunks)


def extract_text_from_html(path: Path) -> str:
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    return soup.get_text(" ")


def extract_text_from_mobi(path: Path) -> str:
    tempdir: str | None = None
    try:
        tempdir, extracted_path_text = mobi.extract(str(path))
        extracted_path = Path(extracted_path_text)
        extracted_extension = get_file_extension(extracted_path.name)
        if extracted_extension == "epub":
            return extract_text_from_epub(extracted_path)
        if extracted_extension == "pdf":
            return extract_text_from_pdf(extracted_path)
        if extracted_extension in {"html", "htm"}:
            return extract_text_from_html(extracted_path)
        raise BookTextExtractionError(
            f"MOBI extraction produced unsupported content: {extracted_extension}."
        )
    finally:
        if tempdir:
            shutil.rmtree(tempdir, ignore_errors=True)
