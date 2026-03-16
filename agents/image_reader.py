"""Interpretación de imágenes usando Claude Vision de Anthropic."""

from __future__ import annotations

import base64
from pathlib import Path

import anthropic

import config


def _encode_image(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


def _build_prompt(question: str = "") -> str:
    prompt = (
        "Analiza esta imagen en detalle. Si contiene ecuaciones, fórmulas, gráficos, "
        "diagramas o problemas de física/cálculo/programación, descríbelos con precisión "
        "y extrae toda la información relevante en español."
    )
    if question:
        prompt += f"\n\nPregunta específica: {question}"
    return prompt


def _detect_mime(image_path: str) -> str:
    ext = Path(image_path).suffix.lower()
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
    return mime_map.get(ext, "image/png")


def _call_vision(b64: str, mime: str, question: str = "") -> str:
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
                {"type": "text", "text": _build_prompt(question)},
            ],
        }],
    )
    return response.content[0].text


def interpret_image_file(image_path: str, question: str = "") -> str:
    """Interpreta una imagen desde un archivo."""
    b64 = _encode_image(Path(image_path).read_bytes())
    mime = _detect_mime(image_path)
    return _call_vision(b64, mime, question)


def interpret_image_bytes(image_bytes: bytes, question: str = "") -> str:
    """Interpreta una imagen desde bytes en memoria."""
    b64 = _encode_image(image_bytes)
    return _call_vision(b64, "image/png", question)
