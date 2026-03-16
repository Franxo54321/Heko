"""Agente resumidor de contenido académico."""

from __future__ import annotations

import anthropic

import config

SYSTEM_PROMPT = """\
Eres un asistente académico experto en Física, Cálculo y Programación.
Tu tarea es resumir material de estudio de forma clara, estructurada y precisa.

Reglas:
- Usa español.
- Organiza el resumen con encabezados claros (##, ###).
- Destaca fórmulas y ecuaciones importantes usando notación LaTeX entre $...$ o $$...$$.
- Incluye definiciones clave, teoremas, propiedades y ejemplos relevantes.
- Si hay código, preséntalo en bloques de código con el lenguaje indicado.
- Al final, lista los conceptos clave como bullet points.
- Sé conciso pero no omitas información importante.
"""


def _generate(user_msg: str) -> str:
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        system=SYSTEM_PROMPT,
        max_tokens=4096,
        messages=[{"role": "user", "content": user_msg}],
    )
    return response.content[0].text


def summarize_content(content: str, subject_hint: str = "") -> str:
    """Resume contenido académico extraído de PDFs/imágenes."""
    user_msg = "Resume el siguiente material de estudio de forma clara y estructurada:\n\n"
    if subject_hint:
        user_msg += f"[Materia: {subject_hint}]\n\n"
    user_msg += content
    return _generate(user_msg)


def summarize_multiple(contents: list[dict]) -> str:
    """Resume múltiples materiales combinándolos en un resumen integrado.

    Cada elemento de `contents` es un dict con keys: 'text', 'source', 'subject'.
    """
    combined = ""
    for i, item in enumerate(contents, 1):
        combined += f"\n\n=== Material {i} (Fuente: {item.get('source', 'N/A')}, Materia: {item.get('subject', 'General')}) ===\n"
        combined += item["text"]

    return _generate(
        "Crea un resumen integrado y organizado por temas del siguiente "
        "conjunto de materiales de estudio:\n" + combined
    )
