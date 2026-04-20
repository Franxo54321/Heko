"""Generador de planes de estudio personalizados."""

from __future__ import annotations

import anthropic

import config

SYSTEM_PROMPT = """\
Eres un planificador académico y profesor experto en todas las áreas del conocimiento.
Tu trabajo es crear planes de estudio completos que incluyan tanto el calendario de estudio
como el contenido real extraído y sintetizado de los materiales del alumno.

Reglas:
- Usa español siempre.
- Para cada día del plan, incluye DOS secciones:
  1. **Agenda** — bloques de tiempo con objetivos claros.
  2. **Material de estudio** — el contenido real a estudiar ese día: conceptos explicados,
     definiciones, fórmulas, ejemplos, y puntos clave extraídos directamente de los materiales.
- El contenido de cada día debe provenir de los fragmentos de texto del material proporcionado.
- Explica los conceptos con tus propias palabras cuando sea útil, pero siempre basándote
  en el material del alumno.
- Incluye pausas y repasos espaciados en la agenda.
- Sugiere momentos para hacer quizzes de autoevaluación.
- Usa formato Markdown. Usa `## Día N` como encabezado de cada día (sin texto adicional
  en esa línea, ej: `## Día 1`, `## Día 2`, etc.).
- Dentro de cada día usa `### Agenda` y `### Material de estudio` como sub-secciones.
- Dentro de Material de estudio usa `#### [Tema]` para organizar por concepto.
"""


def generate_study_plan(
    summaries: list[dict],
    available_days: int = 7,
    hours_per_day: float = 3.0,
    priority_topics: list[str] | None = None,
) -> str:
    """Genera un plan de estudio con contenido real extraído de los materiales.

    Args:
        summaries: Lista de dicts con 'title', 'summary', 'subject', 'raw_text'.
        available_days: Días disponibles para estudiar.
        hours_per_day: Horas de estudio por día.
        priority_topics: Temas con mayor prioridad.
    """
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    material_desc = ""
    for i, s in enumerate(summaries, 1):
        material_desc += (
            f"\n---\n### Material {i}: {s.get('title', 'Sin título')} "
            f"({s.get('subject', 'General')})\n"
        )
        material_desc += f"**Resumen:**\n{s.get('summary', '')[:1500]}\n\n"
        raw = s.get("raw_text", "")
        if raw:
            material_desc += f"**Texto completo (extracto):**\n{raw[:3000]}\n"

    user_msg = f"""Crea un plan de estudio COMPLETO con las siguientes condiciones:

**Días disponibles:** {available_days}
**Horas por día:** {hours_per_day}
**Temas prioritarios:** {', '.join(priority_topics) if priority_topics else 'Ninguno en particular'}

**Materiales del alumno:**
{material_desc}

IMPORTANTE: Para cada día, además de la agenda, incluye una sección "Material de estudio"
con el contenido real a estudiar ese día. Extrae y sintetiza los conceptos, definiciones,
fórmulas y ejemplos directamente del texto de los materiales. El alumno debe poder estudiar
leyendo el plan, sin necesidad de abrir los archivos originales.

Usa exactamente el formato:
## Día N
### Agenda
[tabla o lista de bloques horarios]
### Material de estudio
#### [Concepto o tema]
[explicación, definiciones, fórmulas, ejemplos del material]
"""

    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        system=SYSTEM_PROMPT,
        max_tokens=8192,
        messages=[{"role": "user", "content": user_msg}],
    )
    return response.content[0].text
