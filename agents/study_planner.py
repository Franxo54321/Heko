"""Generador de planes de estudio personalizados."""

from __future__ import annotations

import anthropic

import config

SYSTEM_PROMPT = """\
Eres un planificador académico experto en Física, Cálculo y Programación.
Tu trabajo es crear planes de estudio detallados y realistas.

Reglas:
- Usa español.
- Estructura el plan en sesiones/días con objetivos claros.
- Incluye tiempos estimados para cada bloque de estudio.
- Prioriza temas según dificultad y dependencias (prerequisitos primero).
- Incluye pausas y repasos espaciados.
- Sugiere momentos para hacer quizzes de autoevaluación.
- Adapta el plan a la cantidad de material proporcionado.
- Usa formato Markdown con tablas cuando sea útil.
"""


def generate_study_plan(
    summaries: list[dict],
    available_days: int = 7,
    hours_per_day: float = 3.0,
    priority_topics: list[str] | None = None,
) -> str:
    """Genera un plan de estudio basado en los resúmenes de materiales.

    Args:
        summaries: Lista de dicts con 'title', 'summary', 'subject'.
        available_days: Días disponibles para estudiar.
        hours_per_day: Horas de estudio por día.
        priority_topics: Temas con mayor prioridad.
    """
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    material_desc = ""
    for i, s in enumerate(summaries, 1):
        material_desc += f"\n### Material {i}: {s.get('title', 'Sin título')} ({s.get('subject', 'General')})\n"
        material_desc += s.get("summary", "")[:2000] + "\n"

    user_msg = f"""Crea un plan de estudio con las siguientes condiciones:

**Días disponibles:** {available_days}
**Horas por día:** {hours_per_day}
**Temas prioritarios:** {', '.join(priority_topics) if priority_topics else 'Ninguno en particular'}

**Materiales disponibles:**
{material_desc}

El plan debe incluir:
1. Calendario día por día con bloques de estudio
2. Objetivos específicos por sesión
3. Momentos de repaso y autoevaluación (quizzes)
4. Orden óptimo basado en dependencias entre temas
5. Resumen de conceptos clave a dominar por día
"""

    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        system=SYSTEM_PROMPT,
        max_tokens=4096,
        messages=[{"role": "user", "content": user_msg}],
    )
    return response.content[0].text
