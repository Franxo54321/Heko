"""Base de datos PostgreSQL para persistencia del agente de estudio."""

from __future__ import annotations

import hashlib
import json
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras
import psycopg2.errors

import config


def _get_connection():
    return psycopg2.connect(config.DATABASE_URL)


@contextmanager
def _db():
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _cur(conn):
    """Cursor que devuelve filas como dict."""
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def init_db() -> None:
    """Crea las tablas si no existen."""
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL DEFAULT '',
                email_verified INTEGER NOT NULL DEFAULT 0,
                is_admin INTEGER NOT NULL DEFAULT 0,
                password_hash TEXT NOT NULL,
                display_name TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS verification_codes (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                code TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS subjects (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, name)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS materials (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL DEFAULT 0 REFERENCES users(id),
                filename TEXT NOT NULL,
                file_type TEXT NOT NULL,
                subject TEXT DEFAULT '',
                unit TEXT DEFAULT '',
                raw_text TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS study_plans (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL DEFAULT 0 REFERENCES users(id),
                title TEXT NOT NULL,
                plan_markdown TEXT NOT NULL,
                days INTEGER,
                hours_per_day REAL,
                created_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS quizzes (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL DEFAULT 0 REFERENCES users(id),
                title TEXT NOT NULL,
                quiz_json TEXT NOT NULL,
                material_ids TEXT DEFAULT '[]',
                subject TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS quiz_results (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL DEFAULT 0 REFERENCES users(id),
                quiz_id INTEGER NOT NULL REFERENCES quizzes(id),
                answers_json TEXT NOT NULL,
                score REAL NOT NULL,
                details_json TEXT NOT NULL,
                completed_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS exams (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL DEFAULT 0 REFERENCES users(id),
                title TEXT NOT NULL,
                exam_json TEXT NOT NULL,
                material_ids TEXT DEFAULT '[]',
                duration_minutes INTEGER,
                created_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                token TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)


# ===================== Users =====================

def register_user(username: str, password: str, display_name: str = "", email: str = "") -> int | None:
    """Registra un usuario. Devuelve id o None si ya existe."""
    try:
        with _db() as conn:
            cur = _cur(conn)
            cur.execute(
                "INSERT INTO users (username, email, email_verified, password_hash, display_name, created_at) VALUES (%s, %s, 0, %s, %s, %s) RETURNING id",
                (username.strip().lower(), email.strip().lower(), _hash_password(password), display_name or username, datetime.now().isoformat()),
            )
            return cur.fetchone()["id"]
    except psycopg2.errors.UniqueViolation:
        return None


def email_exists(email: str) -> bool:
    """Verifica si un correo ya está registrado."""
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("SELECT id FROM users WHERE email = %s", (email.strip().lower(),))
        return cur.fetchone() is not None


def create_verification_code(user_id: int) -> str:
    """Genera un código de 6 dígitos con expiración de 15 minutos."""
    code = f"{secrets.randbelow(1000000):06d}"
    expires = (datetime.now() + timedelta(minutes=15)).isoformat()
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("UPDATE verification_codes SET used = 1 WHERE user_id = %s AND used = 0", (user_id,))
        cur.execute(
            "INSERT INTO verification_codes (user_id, code, expires_at, used, created_at) VALUES (%s, %s, %s, 0, %s)",
            (user_id, code, expires, datetime.now().isoformat()),
        )
    return code


def verify_email_code(user_id: int, code: str) -> bool:
    """Valida el código y marca el correo como verificado."""
    with _db() as conn:
        cur = _cur(conn)
        cur.execute(
            "SELECT id, expires_at FROM verification_codes WHERE user_id = %s AND code = %s AND used = 0",
            (user_id, code.strip()),
        )
        row = cur.fetchone()
        if not row:
            return False
        if datetime.fromisoformat(row["expires_at"]) < datetime.now():
            return False
        cur.execute("UPDATE verification_codes SET used = 1 WHERE id = %s", (row["id"],))
        cur.execute("UPDATE users SET email_verified = 1 WHERE id = %s", (user_id,))
    return True


def is_email_verified(user_id: int) -> bool:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("SELECT email_verified FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        return bool(row and row["email_verified"])


# ===================== Sessions (persistent login) =====================

def create_session(user_id: int, days: int = 30) -> str:
    """Crea un token de sesión que dura 'days' días."""
    token = secrets.token_urlsafe(48)
    expires = (datetime.now() + timedelta(days=days)).isoformat()
    with _db() as conn:
        cur = _cur(conn)
        cur.execute(
            "INSERT INTO sessions (user_id, token, expires_at, created_at) VALUES (%s, %s, %s, %s)",
            (user_id, token, expires, datetime.now().isoformat()),
        )
    return token


def get_user_by_session(token: str) -> dict | None:
    """Devuelve el usuario asociado al token si es válido y no expiró."""
    if not token:
        return None
    with _db() as conn:
        cur = _cur(conn)
        cur.execute(
            "SELECT user_id, expires_at FROM sessions WHERE token = %s",
            (token,),
        )
        row = cur.fetchone()
        if not row:
            return None
        if datetime.fromisoformat(row["expires_at"]) < datetime.now():
            cur.execute("DELETE FROM sessions WHERE token = %s", (token,))
            return None
        return get_user(row["user_id"])


def delete_session(token: str) -> None:
    """Elimina un token de sesión (logout)."""
    if token:
        with _db() as conn:
            cur = _cur(conn)
            cur.execute("DELETE FROM sessions WHERE token = %s", (token,))


def authenticate_user(username: str, password: str) -> dict | None:
    """Autentica y devuelve el usuario o None. Acepta username o email."""
    uname = username.strip().lower()
    with _db() as conn:
        cur = _cur(conn)
        cur.execute(
            "SELECT * FROM users WHERE (username = %s OR email = %s) AND password_hash = %s",
            (uname, uname, _hash_password(password)),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_user(user_id: int) -> dict | None:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None


# ===================== Admin =====================

def get_all_users() -> list[dict]:
    """Devuelve todos los usuarios."""
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("SELECT id, username, email, email_verified, is_admin, display_name, created_at FROM users ORDER BY created_at DESC")
        return [dict(r) for r in cur.fetchall()]


def update_user_admin(user_id: int, display_name: str, email: str, is_admin: bool) -> None:
    """Actualiza datos de un usuario (desde admin)."""
    with _db() as conn:
        cur = _cur(conn)
        cur.execute(
            "UPDATE users SET display_name = %s, email = %s, is_admin = %s WHERE id = %s",
            (display_name, email.strip().lower(), int(is_admin), user_id),
        )


def delete_user(user_id: int) -> None:
    """Elimina un usuario y todos sus datos asociados."""
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM verification_codes WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM subjects WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM quiz_results WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM quizzes WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM exams WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM study_plans WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM materials WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))


def set_admin(user_id: int, is_admin: bool) -> None:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("UPDATE users SET is_admin = %s WHERE id = %s", (int(is_admin), user_id))


def reset_user_password(user_id: int, new_password: str) -> None:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (_hash_password(new_password), user_id))


# ===================== Subjects (per user) =====================

def create_subject(user_id: int, name: str) -> int | None:
    try:
        with _db() as conn:
            cur = _cur(conn)
            cur.execute(
                "INSERT INTO subjects (user_id, name, created_at) VALUES (%s, %s, %s) RETURNING id",
                (user_id, name.strip(), datetime.now().isoformat()),
            )
            return cur.fetchone()["id"]
    except psycopg2.errors.UniqueViolation:
        return None


def get_user_subjects(user_id: int) -> list[str]:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("SELECT name FROM subjects WHERE user_id = %s ORDER BY name", (user_id,))
        return [r["name"] for r in cur.fetchall()]


def delete_subject(user_id: int, name: str) -> None:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("DELETE FROM subjects WHERE user_id = %s AND name = %s", (user_id, name))


# ===================== Materials =====================

def save_material(user_id: int, filename: str, file_type: str, subject: str, raw_text: str, summary: str, unit: str = "") -> int:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute(
            "INSERT INTO materials (user_id, filename, file_type, subject, unit, raw_text, summary, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (user_id, filename, file_type, subject, unit, raw_text, summary, datetime.now().isoformat()),
        )
        return cur.fetchone()["id"]


def get_all_materials(user_id: int) -> list[dict]:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("SELECT * FROM materials WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
        return [dict(r) for r in cur.fetchall()]


def get_material(material_id: int) -> dict | None:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("SELECT * FROM materials WHERE id = %s", (material_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def delete_material(material_id: int) -> None:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("DELETE FROM materials WHERE id = %s", (material_id,))


def get_all_units(user_id: int) -> list[str]:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("SELECT DISTINCT unit FROM materials WHERE user_id = %s AND unit != '' ORDER BY unit", (user_id,))
        return [r["unit"] for r in cur.fetchall()]


def get_materials_by_unit(user_id: int, unit: str) -> list[dict]:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("SELECT * FROM materials WHERE user_id = %s AND unit = %s ORDER BY created_at DESC", (user_id, unit))
        return [dict(r) for r in cur.fetchall()]


def update_material_unit(material_id: int, unit: str) -> None:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("UPDATE materials SET unit = %s WHERE id = %s", (unit, material_id))


def update_material_filename(material_id: int, new_name: str) -> None:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("UPDATE materials SET filename = %s WHERE id = %s", (new_name, material_id))


def get_user_subjects_from_materials(user_id: int) -> list[str]:
    """Devuelve materias únicas usadas en materiales del usuario."""
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("SELECT DISTINCT subject FROM materials WHERE user_id = %s AND subject != '' ORDER BY subject", (user_id,))
        return [r["subject"] for r in cur.fetchall()]


# ===================== Study Plans =====================

def save_study_plan(user_id: int, title: str, plan_markdown: str, days: int, hours_per_day: float) -> int:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute(
            "INSERT INTO study_plans (user_id, title, plan_markdown, days, hours_per_day, created_at) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (user_id, title, plan_markdown, days, hours_per_day, datetime.now().isoformat()),
        )
        return cur.fetchone()["id"]


def get_all_study_plans(user_id: int) -> list[dict]:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("SELECT * FROM study_plans WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
        return [dict(r) for r in cur.fetchall()]


def get_study_plan(plan_id: int) -> dict | None:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("SELECT * FROM study_plans WHERE id = %s", (plan_id,))
        row = cur.fetchone()
        return dict(row) if row else None


# ===================== Quizzes =====================

def save_quiz(user_id: int, title: str, quiz_data: dict, material_ids: list[int], subject: str) -> int:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute(
            "INSERT INTO quizzes (user_id, title, quiz_json, material_ids, subject, created_at) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (user_id, title, json.dumps(quiz_data, ensure_ascii=False), json.dumps(material_ids), subject, datetime.now().isoformat()),
        )
        return cur.fetchone()["id"]


def get_all_quizzes(user_id: int) -> list[dict]:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("SELECT * FROM quizzes WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
        results = []
        for r in cur.fetchall():
            d = dict(r)
            d["quiz_json"] = json.loads(d["quiz_json"])
            d["material_ids"] = json.loads(d["material_ids"])
            results.append(d)
        return results


def get_quiz(quiz_id: int) -> dict | None:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("SELECT * FROM quizzes WHERE id = %s", (quiz_id,))
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["quiz_json"] = json.loads(d["quiz_json"])
        d["material_ids"] = json.loads(d["material_ids"])
        return d


# ===================== Quiz Results =====================

def save_quiz_result(user_id: int, quiz_id: int, answers: dict, score: float, details: dict) -> int:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute(
            "INSERT INTO quiz_results (user_id, quiz_id, answers_json, score, details_json, completed_at) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (user_id, quiz_id, json.dumps(answers, ensure_ascii=False), score, json.dumps(details, ensure_ascii=False), datetime.now().isoformat()),
        )
        return cur.fetchone()["id"]


def get_quiz_results(user_id: int, quiz_id: int | None = None) -> list[dict]:
    with _db() as conn:
        cur = _cur(conn)
        if quiz_id:
            cur.execute("SELECT * FROM quiz_results WHERE user_id = %s AND quiz_id = %s ORDER BY completed_at DESC", (user_id, quiz_id))
        else:
            cur.execute("SELECT * FROM quiz_results WHERE user_id = %s ORDER BY completed_at DESC", (user_id,))
        results = []
        for r in cur.fetchall():
            d = dict(r)
            d["answers_json"] = json.loads(d["answers_json"])
            d["details_json"] = json.loads(d["details_json"])
            results.append(d)
        return results


# ===================== Exams =====================

def save_exam(user_id: int, title: str, exam_data: dict, material_ids: list[int], duration_minutes: int) -> int:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute(
            "INSERT INTO exams (user_id, title, exam_json, material_ids, duration_minutes, created_at) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (user_id, title, json.dumps(exam_data, ensure_ascii=False), json.dumps(material_ids), duration_minutes, datetime.now().isoformat()),
        )
        return cur.fetchone()["id"]


def get_all_exams(user_id: int) -> list[dict]:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("SELECT * FROM exams WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
        results = []
        for r in cur.fetchall():
            d = dict(r)
            d["exam_json"] = json.loads(d["exam_json"])
            d["material_ids"] = json.loads(d["material_ids"])
            results.append(d)
        return results


def get_exam(exam_id: int) -> dict | None:
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("SELECT * FROM exams WHERE id = %s", (exam_id,))
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["exam_json"] = json.loads(d["exam_json"])
        d["material_ids"] = json.loads(d["material_ids"])
        return d


# ===================== Stats =====================

def get_progress_stats(user_id: int) -> dict:
    """Devuelve estadísticas generales de progreso para un usuario."""
    with _db() as conn:
        cur = _cur(conn)
        cur.execute("SELECT COUNT(*) AS n FROM materials WHERE user_id = %s", (user_id,))
        total_materials = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM quizzes WHERE user_id = %s", (user_id,))
        total_quizzes = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM quiz_results WHERE user_id = %s", (user_id,))
        total_results = cur.fetchone()["n"]
        cur.execute("SELECT AVG(score) AS avg FROM quiz_results WHERE user_id = %s", (user_id,))
        avg_row = cur.fetchone()
        avg_score = round(avg_row["avg"], 1) if avg_row["avg"] is not None else 0.0
        cur.execute(
            "SELECT qr.score, q.title, qr.completed_at FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE qr.user_id = %s ORDER BY qr.completed_at DESC LIMIT 10",
            (user_id,),
        )
        recent_results = cur.fetchall()
        return {
            "total_materiales": total_materials,
            "total_quizzes": total_quizzes,
            "quizzes_completados": total_results,
            "puntaje_promedio": avg_score,
            "resultados_recientes": [dict(r) for r in recent_results],
        }


