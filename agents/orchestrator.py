"""Orquestador principal: coordina todos los agentes del sistema."""

from __future__ import annotations

import os
import shutil

import config
from agents import image_reader, pdf_reader, quiz_generator, study_planner, summarizer, tutor
from storage import database


def init() -> None:
    """Inicializa el sistema (base de datos, directorios)."""
    database.init_db()


def process_pdf(file_path: str, user_id: int, subject: str = "", unit: str = "") -> dict:
    """Procesa un PDF: extrae texto, imágenes, resume y guarda."""
    metadata = pdf_reader.get_pdf_metadata(file_path)
    raw_text = pdf_reader.extract_text_from_pdf(file_path)

    images = pdf_reader.extract_images_from_pdf(file_path)
    image_descriptions = []
    for img_bytes in images[:5]:
        try:
            desc = image_reader.interpret_image_bytes(img_bytes)
            image_descriptions.append(desc)
        except Exception:
            continue

    full_text = raw_text
    if image_descriptions:
        full_text += "\n\n=== Contenido de imágenes ===\n"
        full_text += "\n---\n".join(image_descriptions)

    summary = summarizer.summarize_content(full_text, subject_hint=subject)

    filename = os.path.basename(file_path)
    dest = os.path.join(config.UPLOADS_DIR, filename)
    if os.path.abspath(file_path) != os.path.abspath(dest):
        shutil.copy2(file_path, dest)

    material_id = database.save_material(
        user_id=user_id,
        filename=filename,
        file_type="pdf",
        subject=subject,
        raw_text=full_text,
        summary=summary,
        unit=unit,
    )

    return {
        "id": material_id,
        "filename": filename,
        "metadata": metadata,
        "summary": summary,
        "images_processed": len(image_descriptions),
    }


def process_image(file_path: str, user_id: int, subject: str = "", question: str = "", unit: str = "") -> dict:
    """Procesa una imagen: interpreta y guarda."""
    description = image_reader.interpret_image_file(file_path, question=question)
    summary = summarizer.summarize_content(description, subject_hint=subject)

    filename = os.path.basename(file_path)
    dest = os.path.join(config.UPLOADS_DIR, filename)
    if os.path.abspath(file_path) != os.path.abspath(dest):
        shutil.copy2(file_path, dest)

    material_id = database.save_material(
        user_id=user_id,
        filename=filename,
        file_type="image",
        subject=subject,
        raw_text=description,
        summary=summary,
        unit=unit,
    )

    return {
        "id": material_id,
        "filename": filename,
        "description": description,
        "summary": summary,
    }


def create_study_plan(
    user_id: int,
    material_ids: list[int] | None = None,
    days: int = 7,
    hours_per_day: float = 3.0,
    priority_topics: list[str] | None = None,
    title: str = "",
) -> dict:
    if material_ids:
        materials = [database.get_material(mid) for mid in material_ids]
        materials = [m for m in materials if m is not None]
    else:
        materials = database.get_all_materials(user_id)

    if not materials:
        return {"error": "No hay materiales cargados. Sube archivos primero."}

    summaries = [
        {"title": m["filename"], "summary": m["summary"], "subject": m["subject"]}
        for m in materials
    ]

    plan_md = study_planner.generate_study_plan(
        summaries=summaries,
        available_days=days,
        hours_per_day=hours_per_day,
        priority_topics=priority_topics,
    )

    plan_title = title or f"Plan de estudio - {days} días"
    plan_id = database.save_study_plan(user_id, plan_title, plan_md, days, hours_per_day)
    return {"id": plan_id, "title": plan_title, "plan": plan_md}


def create_quiz(
    user_id: int,
    material_ids: list[int] | None = None,
    num_questions: int = 10,
    difficulty: str = "media",
    subject: str = "",
) -> dict:
    if material_ids:
        materials = [database.get_material(mid) for mid in material_ids]
        materials = [m for m in materials if m is not None]
    else:
        materials = database.get_all_materials(user_id)

    if not materials:
        return {"error": "No hay materiales cargados."}

    combined_text = "\n\n".join(m["raw_text"][:3000] for m in materials)
    subject = subject or materials[0].get("subject", "")

    quiz_data = quiz_generator.generate_quiz(
        content=combined_text,
        num_questions=num_questions,
        difficulty=difficulty,
        subject=subject,
    )

    quiz_title = quiz_data.get("titulo", f"Quiz - {subject}")
    quiz_id = database.save_quiz(
        user_id=user_id,
        title=quiz_title,
        quiz_data=quiz_data,
        material_ids=[m["id"] for m in materials],
        subject=subject,
    )
    return {"id": quiz_id, "quiz": quiz_data}


def submit_quiz_answers(user_id: int, quiz_id: int, answers: dict[int, str]) -> dict:
    quiz = database.get_quiz(quiz_id)
    if not quiz:
        return {"error": "Quiz no encontrado."}

    results = quiz_generator.grade_quiz(quiz["quiz_json"], answers)
    database.save_quiz_result(
        user_id=user_id,
        quiz_id=quiz_id,
        answers=answers,
        score=results["puntaje"],
        details=results,
    )
    return results


def create_exam(
    user_id: int,
    material_ids: list[int] | None = None,
    duration_minutes: int = 120,
) -> dict:
    if material_ids:
        materials = [database.get_material(mid) for mid in material_ids]
        materials = [m for m in materials if m is not None]
    else:
        materials = database.get_all_materials(user_id)

    if not materials:
        return {"error": "No hay materiales cargados."}

    contents = [
        {"text": m["raw_text"], "subject": m["subject"], "source": m["filename"]}
        for m in materials
    ]

    exam_data = quiz_generator.generate_exam(contents, duration_minutes=duration_minutes)
    exam_title = exam_data.get("titulo", "Modelo de examen")
    exam_id = database.save_exam(
        user_id=user_id,
        title=exam_title,
        exam_data=exam_data,
        material_ids=[m["id"] for m in materials],
        duration_minutes=duration_minutes,
    )
    return {"id": exam_id, "exam": exam_data}


def solve_problem_step_by_step(problem: str, subject: str = "") -> str:
    return tutor.solve_problem(problem, subject=subject)


def explain_topic(concept: str, context: str = "") -> str:
    return tutor.explain_concept(concept, context=context)


def guided_practice(problem: str, student_attempt: str, subject: str = "") -> str:
    return tutor.guided_solution(problem, student_attempt, subject=subject)


def get_progress(user_id: int) -> dict:
    return database.get_progress_stats(user_id)
