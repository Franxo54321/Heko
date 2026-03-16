"""Tutor paso a paso para resolución de problemas."""

from __future__ import annotations

import anthropic

import config

SYSTEM_PROMPT = """\
Eres un tutor experto en Física, Cálculo y Programación. Tu misión es guiar al
estudiante paso a paso en la resolución de problemas, explicando cada paso con
claridad y profundidad.

Reglas:
- Usa español.
- Descompón cada problema en pasos claros y numerados.
- Explica el "por qué" de cada paso, no solo el "cómo".
- Usa notación LaTeX para fórmulas: $inline$ y $$block$$.
- Si es un problema de programación, muestra código con explicaciones línea a línea.
- Relaciona los pasos con conceptos teóricos cuando sea relevante.
- Al final, haz un resumen de la estrategia usada.
- Si el estudiante comete un error, explica amablemente por qué está mal y cómo corregirlo.
- Usa analogías y ejemplos cuando ayuden a la comprensión.
"""


def _call(user_msg: str, system: str = SYSTEM_PROMPT) -> str:
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        system=system,
        max_tokens=4096,
        messages=[{"role": "user", "content": user_msg}],
    )
    return response.content[0].text


def solve_problem(problem: str, subject: str = "") -> str:
    """Resuelve un problema paso a paso con explicaciones detalladas."""
    user_msg = ""
    if subject:
        user_msg += f"[Materia: {subject}]\n\n"
    user_msg += f"Resuelve el siguiente problema paso a paso, explicando cada paso detalladamente:\n\n{problem}"
    return _call(user_msg)


def explain_concept(concept: str, context: str = "") -> str:
    """Explica un concepto específico en detalle."""
    user_msg = f"Explica en detalle el siguiente concepto:\n\n**{concept}**"
    if context:
        user_msg += f"\n\nContexto adicional: {context}"
    return _call(user_msg)


def guided_solution(problem: str, student_attempt: str, subject: str = "") -> str:
    """Evalúa el intento del estudiante y lo guía hacia la solución correcta."""
    user_msg = f"""El estudiante intenta resolver este problema:

**Problema:**
{problem}

**Intento del estudiante:**
{student_attempt}

Analiza su intento:
1. Identifica qué pasos hizo correctamente.
2. Señala errores específicos y explica por qué están mal.
3. Guíalo para que complete/corrija la solución paso a paso.
4. No le des la respuesta directamente, sino pistas y guía."""

    if subject:
        user_msg = f"[Materia: {subject}]\n\n" + user_msg
    return _call(user_msg)


def chat_tutor(messages: list[dict], subject: str = "") -> str:
    """Chat interactivo con el tutor. Mantiene historial de conversación.

    Args:
        messages: Lista de dicts con 'role' ('user'/'assistant') y 'content'.
        subject: Materia del contexto.
    """
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    system = SYSTEM_PROMPT
    if subject:
        system += f"\n\nContexto: estás ayudando con un tema de {subject}."

    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        system=system,
        max_tokens=4096,
        messages=messages,
    )
    return response.content[0].text
