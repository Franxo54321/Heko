"""Generador de quizzes y modelos de examen."""

from __future__ import annotations

import json
import re

import anthropic

import config

QUIZ_SYSTEM_PROMPT = """\
Eres un profesor experto en Física, Cálculo y Programación.
Generas preguntas de evaluación precisas basadas en material de estudio.

SIEMPRE responde con un JSON válido con esta estructura exacta:
{
  "titulo": "Título del quiz",
  "preguntas": [
    {
      "id": 1,
      "tipo": "opcion_multiple",
      "enunciado": "texto de la pregunta",
      "opciones": ["A) ...", "B) ...", "C) ...", "D) ..."],
      "respuesta_correcta": "A",
      "explicacion": "Explicación de por qué es correcta",
      "dificultad": "media"
    }
  ]
}

Tipos de preguntas soportados:
- "opcion_multiple": 4 opciones (A, B, C, D)
- "verdadero_falso": respuesta "Verdadero" o "Falso"
- "desarrollo": respuesta abierta (respuesta_correcta es la solución modelo)

Usa notación matemática cuando sea necesario.
"""

EXAM_SYSTEM_PROMPT = """\
Eres un profesor universitario experto en Física, Cálculo y Programación.
Creas exámenes rigurosos y representativos basados en material de estudio.

SIEMPRE responde con un JSON válido con esta estructura:
{
  "titulo": "Examen de ...",
  "duracion_minutos": 120,
  "instrucciones": "Instrucciones generales",
  "secciones": [
    {
      "nombre": "Sección 1: ...",
      "puntaje_total": 30,
      "preguntas": [
        {
          "id": 1,
          "tipo": "opcion_multiple | desarrollo | verdadero_falso",
          "enunciado": "...",
          "puntaje": 5,
          "opciones": ["A) ...", "B) ...", "C) ...", "D) ..."],
          "respuesta_correcta": "...",
          "criterios_evaluacion": "Qué se espera en la respuesta",
          "dificultad": "facil | media | dificil"
        }
      ]
    }
  ]
}
"""


def _parse_json_response(text: str) -> dict:
    """Extrae y parsea un bloque JSON de la respuesta del modelo."""
    # Intentar encontrar JSON en bloques de código
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    # Intentar parsear directamente
    # Buscar el primer { y último }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        return json.loads(text[start : end + 1])
    raise ValueError("No se pudo extraer JSON de la respuesta")


def generate_quiz(
    content: str,
    num_questions: int = 10,
    difficulty: str = "media",
    question_types: list[str] | None = None,
    subject: str = "",
) -> dict:
    """Genera un quiz basado en contenido de estudio.

    Returns:
        Dict con estructura del quiz (titulo, preguntas).
    """
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    qtypes = question_types or ["opcion_multiple", "verdadero_falso"]
    types_str = ", ".join(qtypes)

    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        system=QUIZ_SYSTEM_PROMPT,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": (
                f"Genera un quiz con {num_questions} preguntas de dificultad '{difficulty}'.\n"
                f"Tipos de preguntas: {types_str}\n"
                f"Materia: {subject or 'General'}\n\n"
                f"Basado en este material:\n{content[:6000]}"
            ),
        }],
    )

    raw = response.content[0].text
    return _parse_json_response(raw)


def generate_exam(
    contents: list[dict],
    duration_minutes: int = 120,
    difficulty_distribution: dict | None = None,
) -> dict:
    """Genera un modelo de examen completo basado en múltiples materiales.

    Args:
        contents: Lista de dicts con 'text', 'subject', 'source'.
        duration_minutes: Duración del examen.
        difficulty_distribution: Ej.: {"facil": 30, "media": 50, "dificil": 20}.
    """
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    dist = difficulty_distribution or {"facil": 30, "media": 50, "dificil": 20}

    material_text = ""
    for i, c in enumerate(contents, 1):
        material_text += f"\n=== Material {i}: {c.get('subject', 'General')} ===\n"
        material_text += c["text"][:3000] + "\n"

    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        system=EXAM_SYSTEM_PROMPT,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": (
                f"Crea un examen completo con las siguientes especificaciones:\n"
                f"- Duración: {duration_minutes} minutos\n"
                f"- Distribución de dificultad: {json.dumps(dist)}\n"
                f"- Incluir secciones de opción múltiple, verdadero/falso y desarrollo\n"
                f"- Incluir al menos 1 problema de resolución paso a paso\n\n"
                f"Material de referencia:\n{material_text}"
            ),
        }],
    )

    raw = response.content[0].text
    return _parse_json_response(raw)


def grade_quiz(quiz: dict, user_answers: dict[int, str]) -> dict:
    """Califica las respuestas de un quiz.

    Args:
        quiz: El quiz original (dict con 'preguntas').
        user_answers: Dict {id_pregunta: respuesta_usuario}.

    Returns:
        Dict con resultados: correctas, incorrectas, puntaje, detalle.
    """
    results = {"correctas": 0, "incorrectas": 0, "total": 0, "detalle": []}

    for pregunta in quiz.get("preguntas", []):
        pid = pregunta["id"]
        correct = pregunta.get("respuesta_correcta", "")
        user_ans = user_answers.get(pid, "")
        is_correct = user_ans.strip().upper() == correct.strip().upper()

        results["total"] += 1
        if is_correct:
            results["correctas"] += 1
        else:
            results["incorrectas"] += 1

        results["detalle"].append(
            {
                "id": pid,
                "enunciado": pregunta["enunciado"],
                "tu_respuesta": user_ans,
                "respuesta_correcta": correct,
                "correcto": is_correct,
                "explicacion": pregunta.get("explicacion", ""),
            }
        )

    results["puntaje"] = round(results["correctas"] / max(results["total"], 1) * 100, 1)
    return results
