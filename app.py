"""Flask application — Agente de Estudio."""

from __future__ import annotations

import os
import tempfile
import json
import secrets
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, g, send_file,
)
from werkzeug.utils import secure_filename

import config
from agents import orchestrator, tutor
from storage import database
from services import email_service

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__)

# SECRET_KEY debe ser estable entre workers y reinicios.
# Fallback fijo para que funcione sin variable de entorno (NO ideal para producción).
_fallback_key = "heko-default-secret-change-me-in-production-2026"
app.secret_key = os.getenv("FLASK_SECRET_KEY") or os.getenv("SECRET_KEY") or _fallback_key

app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True  # Railway usa HTTPS
app.config["SESSION_COOKIE_HTTPONLY"] = True

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "gif", "webp"}

orchestrator.init()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("auth"))
        g.user = session["user"]
        g.uid = g.user["id"]
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session or not session["user"].get("is_admin"):
            flash("No tienes permisos de administrador.", "error")
            return redirect(url_for("home"))
        g.user = session["user"]
        g.uid = g.user["id"]
        return f(*args, **kwargs)
    return decorated


@app.context_processor
def inject_user():
    return {"current_user": session.get("user")}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.route("/auth", methods=["GET", "POST"])
def auth():
    if "user" in session:
        return redirect(url_for("home"))

    if request.method == "POST":
        action = request.form.get("action")

        # --- Login ---
        if action == "login":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if not username or not password:
                flash("Completa ambos campos.", "error")
                return redirect(url_for("auth"))

            user = database.authenticate_user(username, password)
            if not user:
                flash("Usuario o contraseña incorrectos.", "error")
                return redirect(url_for("auth"))

            if user.get("is_admin") or user.get("email_verified"):
                token = database.create_session(user["id"])
                session["user"] = user
                session["session_token"] = token
                return redirect(url_for("home"))
            else:
                code = database.create_verification_code(user["id"])
                sent, err = email_service.send_verification_email(
                    user.get("email", ""), code, user.get("display_name", "")
                )
                session["pending_verification"] = {
                    "user_id": user["id"],
                    "email": user.get("email", ""),
                    "display_name": user.get("display_name", ""),
                }
                if sent:
                    flash("Tu correo no está verificado. Se envió un nuevo código.", "info")
                else:
                    flash(f"No se pudo enviar el código. Error SMTP: {err}", "warning")
                return redirect(url_for("verify"))

        # --- Register ---
        elif action == "register":
            new_user = request.form.get("username", "").strip()
            new_email = request.form.get("email", "").strip()
            new_name = request.form.get("display_name", "").strip()
            new_pass = request.form.get("password", "")
            new_pass2 = request.form.get("password2", "")

            if not new_user or not new_email or not new_pass:
                flash("Completa usuario, correo y contraseña.", "error")
            elif "@" not in new_email or "." not in new_email.split("@")[-1]:
                flash("Ingresa un correo electrónico válido.", "error")
            elif len(new_pass) < 4:
                flash("La contraseña debe tener al menos 4 caracteres.", "error")
            elif new_pass != new_pass2:
                flash("Las contraseñas no coinciden.", "error")
            elif database.email_exists(new_email):
                flash("Ese correo electrónico ya está registrado.", "error")
            else:
                uid = database.register_user(new_user, new_pass, new_name, new_email)
                if uid is None:
                    flash("Ese nombre de usuario ya existe.", "error")
                else:
                    for s in ["Física", "Cálculo", "Programación"]:
                        database.create_subject(uid, s)
                    user = database.get_user(uid)
                    if user.get("is_admin"):
                        token = database.create_session(uid)
                        session["user"] = user
                        session["session_token"] = token
                        flash("¡Cuenta admin creada y verificada!", "success")
                        return redirect(url_for("home"))
                    else:
                        code = database.create_verification_code(uid)
                        sent, err = email_service.send_verification_email(
                            new_email, code, new_name or new_user
                        )
                        session["pending_verification"] = {
                            "user_id": uid,
                            "email": new_email,
                            "display_name": new_name or new_user,
                        }
                        if sent:
                            flash("¡Cuenta creada! Se envió un código de verificación.", "success")
                        else:
                            flash(f"Cuenta creada pero no se pudo enviar el correo. Error: {err}", "warning")
                        return redirect(url_for("verify"))

            return redirect(url_for("auth"))

    return render_template("auth.html")


@app.route("/verify", methods=["GET", "POST"])
def verify():
    pv = session.get("pending_verification")
    if not pv:
        return redirect(url_for("auth"))

    if request.method == "POST":
        action = request.form.get("action")
        if action == "verify":
            code = request.form.get("code", "").strip()
            if database.verify_email_code(pv["user_id"], code):
                user = database.get_user(pv["user_id"])
                token = database.create_session(pv["user_id"])
                session["user"] = user
                session["session_token"] = token
                session.pop("pending_verification", None)
                flash("¡Correo verificado! Bienvenido.", "success")
                return redirect(url_for("home"))
            else:
                flash("Código inválido o expirado.", "error")
        elif action == "resend":
            new_code = database.create_verification_code(pv["user_id"])
            sent, err = email_service.send_verification_email(
                pv["email"], new_code, pv.get("display_name", "")
            )
            if sent:
                flash("Se reenvió el código.", "success")
            else:
                flash(f"No se pudo enviar el correo. Error: {err}", "error")
        elif action == "back":
            session.pop("pending_verification", None)
            return redirect(url_for("auth"))

    return render_template("verify.html", pv=pv)


@app.route("/logout")
def logout():
    token = session.get("session_token")
    if token:
        database.delete_session(token)
    session.clear()
    return redirect(url_for("auth"))


# ---------------------------------------------------------------------------
# Home / Dashboard
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def home():
    stats = database.get_progress_stats(g.uid)
    units = database.get_all_units(g.uid)
    subjects = database.get_user_subjects(g.uid)

    units_data = []
    for u in units:
        mats = database.get_materials_by_unit(g.uid, u)
        units_data.append({"name": u, "materials": mats})

    return render_template("home.html", stats=stats, units_data=units_data, subjects=subjects)


@app.route("/upload-home", methods=["POST"])
@login_required
def upload_home():
    """Quick upload from home page."""
    unit_choice = request.form.get("unit_choice", "")
    new_unit = request.form.get("new_unit", "").strip()
    subject = request.form.get("subject", "")
    other_subject = request.form.get("other_subject", "").strip()

    unit_name = new_unit if unit_choice == "__new__" else unit_choice
    if subject == "Otra" and other_subject:
        subject = other_subject

    files = request.files.getlist("files")
    processed = 0
    for f in files:
        if f and _allowed_file(f.filename):
            suffix = os.path.splitext(f.filename)[1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                f.save(tmp.name)
                tmp_path = tmp.name
            try:
                if suffix.lower() == ".pdf":
                    orchestrator.process_pdf(tmp_path, user_id=g.uid, subject=subject, unit=unit_name)
                else:
                    orchestrator.process_image(tmp_path, user_id=g.uid, subject=subject, unit=unit_name)
                processed += 1
            except Exception as e:
                flash(f"Error procesando {f.filename}: {e}", "error")
            finally:
                os.unlink(tmp_path)

    if processed:
        flash(f"{processed} archivo(s) subido(s) correctamente.", "success")
    return redirect(url_for("home"))


# ---------------------------------------------------------------------------
# Subir Material
# ---------------------------------------------------------------------------

@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    subjects = database.get_user_subjects(g.uid)
    units = database.get_all_units(g.uid)

    if request.method == "POST":
        subject = request.form.get("subject", "")
        other_subject = request.form.get("other_subject", "").strip()
        if subject == "Otra" and other_subject:
            subject = other_subject

        unit_opt = request.form.get("unit_opt", "")
        new_unit = request.form.get("new_unit", "").strip()
        upload_unit = ""
        if unit_opt == "__new__":
            upload_unit = new_unit
        elif unit_opt != "__none__":
            upload_unit = unit_opt

        files = request.files.getlist("files")
        for f in files:
            if f and _allowed_file(f.filename):
                suffix = os.path.splitext(f.filename)[1]
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    f.save(tmp.name)
                    tmp_path = tmp.name
                try:
                    if suffix.lower() == ".pdf":
                        result = orchestrator.process_pdf(tmp_path, user_id=g.uid, subject=subject, unit=upload_unit)
                    else:
                        result = orchestrator.process_image(tmp_path, user_id=g.uid, subject=subject, unit=upload_unit)
                    flash(f"✅ {f.filename} procesado correctamente.", "success")
                except Exception as e:
                    flash(f"Error procesando {f.filename}: {e}", "error")
                finally:
                    os.unlink(tmp_path)

        return redirect(url_for("upload"))

    return render_template("upload.html", subjects=subjects, units=units)


# ---------------------------------------------------------------------------
# Mis Materiales
# ---------------------------------------------------------------------------

@app.route("/materials")
@login_required
def materials():
    all_materials = database.get_all_materials(g.uid)
    filter_subj = request.args.get("subject", "")
    filter_unit = request.args.get("unit", "")

    filtered = all_materials
    if filter_subj:
        filtered = [m for m in filtered if m["subject"] == filter_subj]
    if filter_unit:
        filtered = [m for m in filtered if m.get("unit", "") == filter_unit]

    subjects = sorted(set(m["subject"] for m in all_materials if m["subject"]))
    units = sorted(set(m.get("unit", "") for m in all_materials if m.get("unit", "")))

    units_map: dict[str, list] = {}
    for mat in filtered:
        u = mat.get("unit", "") or "Sin unidad"
        units_map.setdefault(u, []).append(mat)

    return render_template(
        "materials.html",
        materials=filtered,
        all_count=len(all_materials),
        subjects=subjects,
        units=units,
        units_map=units_map,
        filter_subj=filter_subj,
        filter_unit=filter_unit,
    )


@app.route("/materials/delete/<int:material_id>", methods=["POST"])
@login_required
def delete_material(material_id):
    database.delete_material(material_id)
    flash("Material eliminado.", "success")
    return redirect(url_for("materials"))


@app.route("/materials/move/<int:material_id>", methods=["POST"])
@login_required
def move_material(material_id):
    new_unit = request.form.get("new_unit", "").strip()
    database.update_material_unit(material_id, new_unit)
    flash("Material movido.", "success")
    return redirect(url_for("materials"))


@app.route("/materials/rename/<int:material_id>", methods=["POST"])
@login_required
def rename_material(material_id):
    new_name = request.form.get("new_name", "").strip()
    if new_name:
        database.update_material_filename(material_id, new_name)
        flash("Nombre actualizado.", "success")
    else:
        flash("El nombre no puede estar vacío.", "error")
    return redirect(url_for("materials"))


# ---------------------------------------------------------------------------
# Plan de Estudio
# ---------------------------------------------------------------------------

@app.route("/study-plan", methods=["GET", "POST"])
@login_required
def study_plan():
    all_materials = database.get_all_materials(g.uid)
    plans = database.get_all_study_plans(g.uid)

    if request.method == "POST":
        selected_ids_str = request.form.getlist("material_ids")
        selected_ids = [int(x) for x in selected_ids_str] if selected_ids_str else None
        days = int(request.form.get("days", 7))
        hours = float(request.form.get("hours", 3.0))
        priority = request.form.get("priority", "")
        priority_list = [t.strip() for t in priority.split(",") if t.strip()] if priority else None
        title = request.form.get("title", "").strip() or f"Plan de estudio - {days} días"

        result = orchestrator.create_study_plan(
            user_id=g.uid,
            material_ids=selected_ids,
            days=days,
            hours_per_day=hours,
            priority_topics=priority_list,
            title=title,
        )

        if "error" in result:
            flash(result["error"], "error")
        else:
            flash("Plan generado exitosamente.", "success")
            return redirect(url_for("study_plan"))

        return redirect(url_for("study_plan"))

    return render_template("study_plan.html", materials=all_materials, plans=plans)


# ---------------------------------------------------------------------------
# Quizzes
# ---------------------------------------------------------------------------

@app.route("/quizzes")
@login_required
def quizzes():
    all_materials = database.get_all_materials(g.uid)
    all_quizzes = database.get_all_quizzes(g.uid)
    quiz_results = database.get_quiz_results(g.uid)
    subjects = database.get_user_subjects(g.uid)
    return render_template(
        "quizzes.html",
        materials=all_materials,
        quizzes=all_quizzes,
        results=quiz_results,
        subjects=subjects,
    )


@app.route("/quizzes/create", methods=["POST"])
@login_required
def create_quiz():
    selected_ids_str = request.form.getlist("material_ids")
    selected_ids = [int(x) for x in selected_ids_str] if selected_ids_str else None
    num_q = int(request.form.get("num_questions", 10))
    diff = request.form.get("difficulty", "media")
    subject = request.form.get("subject", "")

    result = orchestrator.create_quiz(
        user_id=g.uid,
        material_ids=selected_ids,
        num_questions=num_q,
        difficulty=diff,
        subject=subject,
    )

    if "error" in result:
        flash(result["error"], "error")
    else:
        flash(f"Quiz generado: {result['quiz'].get('titulo', 'Quiz')}", "success")

    return redirect(url_for("quizzes"))


@app.route("/quizzes/solve/<int:quiz_id>", methods=["GET", "POST"])
@login_required
def solve_quiz(quiz_id):
    quiz = database.get_quiz(quiz_id)
    if not quiz:
        flash("Quiz no encontrado.", "error")
        return redirect(url_for("quizzes"))

    quiz_data = quiz["quiz_json"]
    preguntas = quiz_data.get("preguntas", [])

    if request.method == "POST":
        answers = {}
        for p in preguntas:
            ans = request.form.get(f"q_{p['id']}", "")
            answers[p["id"]] = ans

        results = orchestrator.submit_quiz_answers(g.uid, quiz_id, answers)

        if "error" in results:
            flash(results["error"], "error")
            return redirect(url_for("quizzes"))

        return render_template("quiz_results.html", results=results, quiz=quiz_data)

    return render_template("solve_quiz.html", quiz=quiz, quiz_data=quiz_data, preguntas=preguntas)


# ---------------------------------------------------------------------------
# Modelo de Examen
# ---------------------------------------------------------------------------

@app.route("/exam", methods=["GET", "POST"])
@login_required
def exam():
    all_materials = database.get_all_materials(g.uid)
    exams = database.get_all_exams(g.uid)

    if request.method == "POST":
        selected_ids_str = request.form.getlist("material_ids")
        selected_ids = [int(x) for x in selected_ids_str] if selected_ids_str else None
        duration = int(request.form.get("duration", 120))

        result = orchestrator.create_exam(
            user_id=g.uid,
            material_ids=selected_ids,
            duration_minutes=duration,
        )

        if "error" in result:
            flash(result["error"], "error")
        else:
            flash("Examen generado exitosamente.", "success")

        return redirect(url_for("exam"))

    return render_template("exam.html", materials=all_materials, exams=exams)


# ---------------------------------------------------------------------------
# Tutor
# ---------------------------------------------------------------------------

@app.route("/tutor")
@login_required
def tutor_page():
    subjects = database.get_user_subjects(g.uid)
    material_context = None
    material_id = request.args.get("material_id")
    if material_id:
        mat = database.get_material(int(material_id))
        if mat and str(mat.get("user_id")) == str(g.uid):
            material_context = {
                "filename": mat.get("filename", ""),
                "summary": mat.get("summary", ""),
                "subject": mat.get("subject", ""),
            }
    return render_template("tutor.html", subjects=subjects, material_context=material_context)


@app.route("/tutor/solve", methods=["POST"])
@login_required
def tutor_solve():
    problem = request.form.get("problem", "")
    subject = request.form.get("subject", "")
    if not problem:
        return jsonify({"error": "Escribe un problema."})

    solution = orchestrator.solve_problem_step_by_step(problem, subject=subject)
    return jsonify({"solution": solution})


@app.route("/tutor/solve-file", methods=["POST"])
@login_required
def tutor_solve_file():
    subject = request.form.get("subject", "")
    f = request.files.get("file")
    if not f or not _allowed_file(f.filename):
        return jsonify({"error": "Archivo no válido."})

    suffix = os.path.splitext(f.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        f.save(tmp.name)
        tmp_path = tmp.name

    try:
        if suffix.lower() == ".pdf":
            from agents import pdf_reader
            extracted = pdf_reader.extract_text_from_pdf(tmp_path)
        else:
            from agents import image_reader as ir
            extracted = ir.interpret_image_file(
                tmp_path,
                question="Lista todos los problemas o ejercicios que aparecen en esta imagen. Transcríbelos fielmente.",
            )

        solution = orchestrator.solve_problem_step_by_step(
            f"Resuelve TODOS los problemas del siguiente texto paso a paso:\n\n{extracted}",
            subject=subject,
        )
        return jsonify({"extracted": extracted, "solution": solution})
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        os.unlink(tmp_path)


@app.route("/tutor/guide", methods=["POST"])
@login_required
def tutor_guide():
    problem = request.form.get("problem", "")
    attempt = request.form.get("attempt", "")
    subject = request.form.get("subject", "")
    if not problem:
        return jsonify({"error": "Escribe el problema."})

    if attempt.strip():
        feedback = orchestrator.guided_practice(problem, attempt, subject=subject)
    else:
        feedback = orchestrator.solve_problem_step_by_step(
            f"Guía al estudiante paso a paso para resolver este problema. "
            f"No des la respuesta directa, haz preguntas orientadoras y da pistas:\n\n{problem}",
            subject=subject,
        )
    return jsonify({"feedback": feedback})


@app.route("/tutor/chat", methods=["POST"])
@login_required
def tutor_chat():
    data = request.get_json(silent=True) or {}
    messages = data.get("messages", [])
    subject = data.get("subject", "General")

    if not messages:
        return jsonify({"error": "Sin mensajes."})

    response = tutor.chat_tutor(messages, subject=subject)
    return jsonify({"response": response})


# ---------------------------------------------------------------------------
# Mi Progreso
# ---------------------------------------------------------------------------

@app.route("/progress")
@login_required
def progress():
    stats = database.get_progress_stats(g.uid)
    all_materials = database.get_all_materials(g.uid)

    subjects_count = {}
    for m in all_materials:
        subj = m["subject"] or "Sin materia"
        subjects_count[subj] = subjects_count.get(subj, 0) + 1

    return render_template("progress.html", stats=stats, subjects_count=subjects_count)


# ---------------------------------------------------------------------------
# Mis Materias
# ---------------------------------------------------------------------------

@app.route("/subjects", methods=["GET", "POST"])
@login_required
def subjects():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            name = request.form.get("name", "").strip()
            if name:
                r = database.create_subject(g.uid, name)
                if r is not None:
                    flash(f"Materia «{name}» creada.", "success")
                else:
                    flash("Esa materia ya existe.", "warning")
        elif action == "delete":
            name = request.form.get("name", "")
            database.delete_subject(g.uid, name)
            flash(f"Materia «{name}» eliminada.", "success")

        return redirect(url_for("subjects"))

    subj_list = database.get_user_subjects(g.uid)
    return render_template("subjects.html", subjects=subj_list)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

@app.route("/admin")
@admin_required
def admin_panel():
    all_users = database.get_all_users()
    return render_template("admin.html", users=all_users)


@app.route("/admin/edit/<int:user_id>", methods=["POST"])
@admin_required
def admin_edit_user(user_id):
    display_name = request.form.get("display_name", "")
    email = request.form.get("email", "")
    is_admin = request.form.get("is_admin") == "on"
    new_pass = request.form.get("new_password", "")

    database.update_user_admin(user_id, display_name, email, is_admin)
    if new_pass:
        database.reset_user_password(user_id, new_pass)

    flash("Usuario actualizado.", "success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/delete/<int:user_id>", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    if user_id == g.uid:
        flash("No puedes eliminarte a ti mismo.", "error")
    else:
        database.delete_user(user_id)
        flash("Usuario eliminado.", "success")
    return redirect(url_for("admin_panel"))


# ---------------------------------------------------------------------------
# Study Plan exports (PDF & Audio)
# ---------------------------------------------------------------------------

def _md_to_plain(md_text) -> str:
    """Convert markdown to plain text for TTS. Falls back to regex strip."""
    if not md_text:
        return ""
    text = str(md_text)
    try:
        import markdown as md_lib
        from bs4 import BeautifulSoup
        html = md_lib.markdown(text)
        return BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
    except Exception:
        import re as _re
        text = _re.sub(r"#{1,6}\s*", "", text)
        text = _re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
        text = _re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
        return text


def _sanitize_latin1(text: str) -> str:
    """Replace common Unicode chars that Helvetica/latin-1 can't render."""
    _MAP = {
        "\u2014": "-", "\u2013": "-", "\u2018": "'", "\u2019": "'",
        "\u201c": '"', "\u201d": '"', "\u2022": "-", "\u2026": "...",
        "\u2192": "->", "\u2190": "<-", "\u2713": "v", "\u2714": "v",
        "\u2716": "x", "\u25cf": "*", "\u25cb": "o", "\u00b7": "-",
        "\u2003": " ", "\u2002": " ", "\u200b": "",
    }
    for old, new in _MAP.items():
        text = text.replace(old, new)
    return text.encode("latin-1", "replace").decode("latin-1")


@app.route("/study-plan/<int:plan_id>/pdf")
@login_required
def study_plan_pdf(plan_id):
    import io
    import re
    try:
        from fpdf import FPDF
    except ImportError:
        app.logger.error("fpdf2 not installed")
        return "PDF no disponible: falta fpdf2", 500

    plan = database.get_study_plan(plan_id)
    if not plan or plan["user_id"] != g.uid:
        flash("Plan no encontrado.", "error")
        return redirect(url_for("study_plan"))

    try:
        plan_markdown = plan.get("plan_markdown") or ""
        plain = _md_to_plain(plan_markdown)
        lines = plain.split("\n")

        pdf = FPDF()
        pdf.set_margins(15, 15, 15)
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()
        # Usable width para multi_cell
        usable_w = pdf.w - pdf.l_margin - pdf.r_margin

        # Title
        pdf.set_font("Helvetica", "B", 18)
        title_str = _sanitize_latin1(str(plan.get("title") or "Plan de estudio"))
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(usable_w, 12, title_str)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(120, 120, 120)
        created = plan.get("created_at") or ""
        if hasattr(created, "strftime"):
            created = created.strftime("%Y-%m-%d")
        else:
            created = str(created)[:10]
        days_val = plan.get("days") or ""
        hrs_val = plan.get("hours_per_day") or ""
        meta = _sanitize_latin1(f"{created}  |  {days_val} dias  |  {hrs_val}h/dia")
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(usable_w, 8, meta)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(6)

        for line in lines:
            stripped = line.strip()
            if not stripped:
                pdf.ln(3)
                continue

            safe = _sanitize_latin1(stripped)
            pdf.set_x(pdf.l_margin)  # siempre resetear X antes de renderizar

            if re.match(r"^D[ií]a\s+\d+", stripped, re.IGNORECASE):
                pdf.ln(4)
                pdf.set_font("Helvetica", "B", 14)
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(usable_w, 9, safe)
                y_line = pdf.get_y()
                pdf.set_draw_color(15, 118, 110)
                pdf.line(pdf.l_margin, y_line, pdf.l_margin + usable_w, y_line)
                pdf.ln(3)
                pdf.set_font("Helvetica", "", 11)
            elif re.match(r"^(Agenda|Material de estudio|Repaso|Autoevaluaci[oó]n)", stripped, re.IGNORECASE):
                pdf.ln(2)
                pdf.set_font("Helvetica", "B", 12)
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(usable_w, 8, safe)
                pdf.set_font("Helvetica", "", 11)
            else:
                pdf.set_font("Helvetica", "", 10)
                pdf.set_x(pdf.l_margin)
                try:
                    pdf.multi_cell(usable_w, 6, safe)
                except Exception:
                    pass  # saltar lineas que no se puedan renderizar

        pdf_bytes = bytes(pdf.output())
        buf = io.BytesIO(pdf_bytes)
        buf.seek(0)

        raw_title = plan.get("title") or "plan"
        safe_title = re.sub(r"[^\w\s-]", "", str(raw_title)).strip().replace(" ", "_")[:50] or "plan"
        return send_file(
            buf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"{safe_title}.pdf",
        )
    except Exception as exc:
        app.logger.exception("PDF generation failed for plan %s: %s", plan_id, exc)
        return f"Error generando PDF: {type(exc).__name__}: {exc}", 500


@app.route("/study-plan/<int:plan_id>/audio-text")
@login_required
def study_plan_audio_text(plan_id):
    """Return plain text of the plan for browser-based TTS."""
    plan = database.get_study_plan(plan_id)
    if not plan or plan["user_id"] != g.uid:
        return jsonify({"error": "Plan no encontrado."}), 404

    plain = _md_to_plain(plan["plan_markdown"])
    return jsonify({"title": plan["title"], "text": plain})


@app.route("/study-plan/<int:plan_id>/audio-download")
@login_required
def study_plan_audio_download(plan_id):
    """Generate and download MP3 via gTTS."""
    import io
    import re

    plan = database.get_study_plan(plan_id)
    if not plan or plan["user_id"] != g.uid:
        flash("Plan no encontrado.", "error")
        return redirect(url_for("study_plan"))

    try:
        from gtts import gTTS
    except ImportError as exc:
        app.logger.error("gTTS not installed: %s", exc)
        return f"Error: gTTS no instalado ({exc})", 500

    try:
        plain = _md_to_plain(plan.get("plan_markdown") or "")
        text_for_tts = re.sub(r"\n{2,}", ". ", plain)
        text_for_tts = re.sub(r"\n", ". ", text_for_tts).strip()
        # Limitar a ~3000 chars para evitar timeout en Railway
        if len(text_for_tts) > 3000:
            text_for_tts = text_for_tts[:3000] + "... Fin del resumen."
        if not text_for_tts:
            text_for_tts = "Plan de estudio sin contenido."

        tts = gTTS(text=text_for_tts, lang="es", slow=False)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)

        raw_title = plan.get("title") or "plan"
        safe_title = re.sub(r"[^\w\s-]", "", str(raw_title)).strip().replace(" ", "_")[:50] or "plan"
        return send_file(
            buf,
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name=f"{safe_title}.mp3",
        )
    except Exception as exc:
        app.logger.exception("Audio generation failed for plan %s: %s", plan_id, exc)
        return f"Error generando MP3: {type(exc).__name__}: {exc}", 500


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
