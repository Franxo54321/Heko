"""Extractor de texto desde archivos PDF usando PyMuPDF."""

from __future__ import annotations

import fitz  # PyMuPDF


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extrae todo el texto de un PDF y lo devuelve como string."""
    doc = fitz.open(pdf_path)
    pages: list[str] = []
    for page_num, page in enumerate(doc, start=1):
        text = page.get_text()
        if text.strip():
            pages.append(f"--- Página {page_num} ---\n{text.strip()}")
    doc.close()
    return "\n\n".join(pages)


def extract_images_from_pdf(pdf_path: str) -> list[bytes]:
    """Extrae imágenes embebidas de un PDF como lista de bytes PNG."""
    doc = fitz.open(pdf_path)
    images: list[bytes] = []
    for page in doc:
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            base_image = doc.extract_image(xref)
            if base_image and base_image.get("image"):
                images.append(base_image["image"])
    doc.close()
    return images


def get_pdf_metadata(pdf_path: str) -> dict:
    """Devuelve metadatos básicos del PDF."""
    doc = fitz.open(pdf_path)
    metadata = {
        "titulo": doc.metadata.get("title", "Sin título"),
        "autor": doc.metadata.get("author", "Desconocido"),
        "paginas": doc.page_count,
    }
    doc.close()
    return metadata
