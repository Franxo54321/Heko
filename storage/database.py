"""Base de datos SQLite para persistencia del agente de estudio."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

import config


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _db():
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def init_db() -> None:
    """Crea las tablas si no existen."""
    with _db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL DEFAULT '',
                email_verified INTEGER NOT NULL DEFAULT 0,
                is_admin INTEGER NOT NULL DEFAULT 0,
                password_hash TEXT NOT NULL,
                display_name TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS verification_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, name)
            );

            CREATE TABLE IF NOT EXISTS materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                filename TEXT NOT NULL,
                file_type TEXT NOT NULL,
                subject TEXT DEFAULT '',
                unit TEXT DEFAULT '',
                raw_text TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS study_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                title TEXT NOT NULL,
                plan_markdown TEXT NOT NULL,
                days INTEGER,
                hours_per_day REAL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS quizzes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                title TEXT NOT NULL,
                quiz_json TEXT NOT NULL,
                material_ids TEXT DEFAULT '[]',
                subject TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS quiz_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                quiz_id INTEGER NOT NULL,
                answers_json TEXT NOT NULL,
                score REAL NOT NULL,
                details_json TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                FOREIGN KEY (quiz_id) REFERENCES quizzes(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS exams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                title TEXT NOT NULL,
                exam_json TEXT NOT NULL,
                material_ids TEXT DEFAULT '[]',
                duration_minutes INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            """
        )
        # Migraciones para bases existentes
        _migrate(conn)
    _ensure_admin()


def _ensure_admin() -> None:
    """Crea el usuario admin por defecto si no existe y lo marca como admin."""
    with _db() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE username = ?", (config.ADMIN_USERNAME,)
        ).fetchone()
        if row:
            conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (row["id"],))
        else:
            cursor = conn.execute(
                "INSERT INTO users (username, email, email_verified, password_hash, display_name, is_admin, created_at) VALUES (?, '', 0, ?, ?, 1, ?)",
                (config.ADMIN_USERNAME, _hash_password(config.ADMIN_PASSWORD), config.ADMIN_USERNAME, datetime.now().isoformat()),
            )


def _migrate(conn: sqlite3.Connection) -> None:
    """Añade columnas faltantes a tablas existentes."""
    migrations = [
        ("materials", "unit", "TEXT DEFAULT ''"),
        ("materials", "user_id", "INTEGER NOT NULL DEFAULT 0"),
        ("study_plans", "user_id", "INTEGER NOT NULL DEFAULT 0"),
        ("quizzes", "user_id", "INTEGER NOT NULL DEFAULT 0"),
        ("quiz_results", "user_id", "INTEGER NOT NULL DEFAULT 0"),
        ("exams", "user_id", "INTEGER NOT NULL DEFAULT 0"),
        ("users", "email", "TEXT NOT NULL DEFAULT ''"),
        ("users", "email_verified", "INTEGER NOT NULL DEFAULT 0"),
        ("users", "is_admin", "INTEGER NOT NULL DEFAULT 0"),
    ]
    for table, column, col_type in migrations:
        try:
            conn.execute(f"SELECT {column} FROM {table} LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


# ===================== Users =====================

def register_user(username: str, password: str, display_name: str = "", email: str = "") -> int | None:
    """Registra un usuario. Devuelve id o None si ya existe."""
    try:
        with _db() as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, email, email_verified, password_hash, display_name, created_at) VALUES (?, ?, 0, ?, ?, ?)",
                (username.strip().lower(), email.strip().lower(), _hash_password(password), display_name or username, datetime.now().isoformat()),
            )
            return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None


def email_exists(email: str) -> bool:
    """Verifica si un correo ya está registrado."""
    with _db() as conn:
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        return row is not None


def create_verification_code(user_id: int) -> str:
    """Genera un código de 6 dígitos con expiración de 15 minutos."""
    code = f"{secrets.randbelow(1000000):06d}"
    expires = (datetime.now() + timedelta(minutes=15)).isoformat()
    with _db() as conn:
        # Invalida códigos anteriores del mismo usuario
        conn.execute("UPDATE verification_codes SET used = 1 WHERE user_id = ? AND used = 0", (user_id,))
        conn.execute(
            "INSERT INTO verification_codes (user_id, code, expires_at, used, created_at) VALUES (?, ?, ?, 0, ?)",
            (user_id, code, expires, datetime.now().isoformat()),
        )
    return code


def verify_email_code(user_id: int, code: str) -> bool:
    """Valida el código y marca el correo como verificado."""
    with _db() as conn:
        row = conn.execute(
            "SELECT id, expires_at FROM verification_codes WHERE user_id = ? AND code = ? AND used = 0",
            (user_id, code.strip()),
        ).fetchone()
        if not row:
            return False
        if datetime.fromisoformat(row["expires_at"]) < datetime.now():
            return False
        conn.execute("UPDATE verification_codes SET used = 1 WHERE id = ?", (row["id"],))
        conn.execute("UPDATE users SET email_verified = 1 WHERE id = ?", (user_id,))
    return True


def is_email_verified(user_id: int) -> bool:
    with _db() as conn:
        row = conn.execute("SELECT email_verified FROM users WHERE id = ?", (user_id,)).fetchone()
        return bool(row and row["email_verified"])


# ===================== Sessions (persistent login) =====================

def create_session(user_id: int, days: int = 30) -> str:
    """Crea un token de sesión que dura 'days' días."""
    token = secrets.token_urlsafe(48)
    expires = (datetime.now() + timedelta(days=days)).isoformat()
    with _db() as conn:
        conn.execute(
            "INSERT INTO sessions (user_id, token, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (user_id, token, expires, datetime.now().isoformat()),
        )
    return token


def get_user_by_session(token: str) -> dict | None:
    """Devuelve el usuario asociado al token si es válido y no expiró."""
    if not token:
        return None
    with _db() as conn:
        row = conn.execute(
            "SELECT s.user_id, s.expires_at FROM sessions s WHERE s.token = ?",
            (token,),
        ).fetchone()
        if not row:
            return None
        if datetime.fromisoformat(row["expires_at"]) < datetime.now():
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None
        return get_user(row["user_id"])


def delete_session(token: str) -> None:
    """Elimina un token de sesión (logout)."""
    if token:
        with _db() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def authenticate_user(username: str, password: str) -> dict | None:
    """Autentica y devuelve el usuario o None. Acepta username o email."""
    uname = username.strip().lower()
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE (username = ? OR email = ?) AND password_hash = ?",
            (uname, uname, _hash_password(password)),
        ).fetchone()
        return dict(row) if row else None


def get_user(user_id: int) -> dict | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


# ===================== Admin =====================

def get_all_users() -> list[dict]:
    """Devuelve todos los usuarios."""
    with _db() as conn:
        rows = conn.execute("SELECT id, username, email, email_verified, is_admin, display_name, created_at FROM users ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def update_user_admin(user_id: int, display_name: str, email: str, is_admin: bool) -> None:
    """Actualiza datos de un usuario (desde admin)."""
    with _db() as conn:
        conn.execute(
            "UPDATE users SET display_name = ?, email = ?, is_admin = ? WHERE id = ?",
            (display_name, email.strip().lower(), int(is_admin), user_id),
        )


def delete_user(user_id: int) -> None:
    """Elimina un usuario y todos sus datos asociados."""
    with _db() as conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM verification_codes WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM subjects WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM quiz_results WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM quizzes WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM exams WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM study_plans WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM materials WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


def set_admin(user_id: int, is_admin: bool) -> None:
    with _db() as conn:
        conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (int(is_admin), user_id))


def reset_user_password(user_id: int, new_password: str) -> None:
    with _db() as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (_hash_password(new_password), user_id))


# ===================== Subjects (per user) =====================

def create_subject(user_id: int, name: str) -> int | None:
    try:
        with _db() as conn:
            cursor = conn.execute(
                "INSERT INTO subjects (user_id, name, created_at) VALUES (?, ?, ?)",
                (user_id, name.strip(), datetime.now().isoformat()),
            )
            return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None


def get_user_subjects(user_id: int) -> list[str]:
    with _db() as conn:
        rows = conn.execute("SELECT name FROM subjects WHERE user_id = ? ORDER BY name", (user_id,)).fetchall()
        return [r["name"] for r in rows]


def delete_subject(user_id: int, name: str) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM subjects WHERE user_id = ? AND name = ?", (user_id, name))


# ===================== Materials =====================

def save_material(user_id: int, filename: str, file_type: str, subject: str, raw_text: str, summary: str, unit: str = "") -> int:
    with _db() as conn:
        cursor = conn.execute(
            "INSERT INTO materials (user_id, filename, file_type, subject, unit, raw_text, summary, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, filename, file_type, subject, unit, raw_text, summary, datetime.now().isoformat()),
        )
        return cursor.lastrowid  # type: ignore[return-value]


def get_all_materials(user_id: int) -> list[dict]:
    with _db() as conn:
        rows = conn.execute("SELECT * FROM materials WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
        return [dict(r) for r in rows]


def get_material(material_id: int) -> dict | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
        return dict(row) if row else None


def delete_material(material_id: int) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM materials WHERE id = ?", (material_id,))


def get_all_units(user_id: int) -> list[str]:
    with _db() as conn:
        rows = conn.execute("SELECT DISTINCT unit FROM materials WHERE user_id = ? AND unit != '' ORDER BY unit", (user_id,)).fetchall()
        return [r["unit"] for r in rows]


def get_materials_by_unit(user_id: int, unit: str) -> list[dict]:
    with _db() as conn:
        rows = conn.execute("SELECT * FROM materials WHERE user_id = ? AND unit = ? ORDER BY created_at DESC", (user_id, unit)).fetchall()
        return [dict(r) for r in rows]


def update_material_unit(material_id: int, unit: str) -> None:
    with _db() as conn:
        conn.execute("UPDATE materials SET unit = ? WHERE id = ?", (unit, material_id))


def get_user_subjects_from_materials(user_id: int) -> list[str]:
    """Devuelve materias únicas usadas en materiales del usuario."""
    with _db() as conn:
        rows = conn.execute("SELECT DISTINCT subject FROM materials WHERE user_id = ? AND subject != '' ORDER BY subject", (user_id,)).fetchall()
        return [r["subject"] for r in rows]


# ===================== Study Plans =====================

def save_study_plan(user_id: int, title: str, plan_markdown: str, days: int, hours_per_day: float) -> int:
    with _db() as conn:
        cursor = conn.execute(
            "INSERT INTO study_plans (user_id, title, plan_markdown, days, hours_per_day, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, title, plan_markdown, days, hours_per_day, datetime.now().isoformat()),
        )
        return cursor.lastrowid  # type: ignore[return-value]


def get_all_study_plans(user_id: int) -> list[dict]:
    with _db() as conn:
        rows = conn.execute("SELECT * FROM study_plans WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
        return [dict(r) for r in rows]


def get_study_plan(plan_id: int) -> dict | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM study_plans WHERE id = ?", (plan_id,)).fetchone()
        return dict(row) if row else None


# ===================== Quizzes =====================

def save_quiz(user_id: int, title: str, quiz_data: dict, material_ids: list[int], subject: str) -> int:
    with _db() as conn:
        cursor = conn.execute(
            "INSERT INTO quizzes (user_id, title, quiz_json, material_ids, subject, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, title, json.dumps(quiz_data, ensure_ascii=False), json.dumps(material_ids), subject, datetime.now().isoformat()),
        )
        return cursor.lastrowid  # type: ignore[return-value]


def get_all_quizzes(user_id: int) -> list[dict]:
    with _db() as conn:
        rows = conn.execute("SELECT * FROM quizzes WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["quiz_json"] = json.loads(d["quiz_json"])
            d["material_ids"] = json.loads(d["material_ids"])
            results.append(d)
        return results


def get_quiz(quiz_id: int) -> dict | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM quizzes WHERE id = ?", (quiz_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["quiz_json"] = json.loads(d["quiz_json"])
        d["material_ids"] = json.loads(d["material_ids"])
        return d


# ===================== Quiz Results =====================

def save_quiz_result(user_id: int, quiz_id: int, answers: dict, score: float, details: dict) -> int:
    with _db() as conn:
        cursor = conn.execute(
            "INSERT INTO quiz_results (user_id, quiz_id, answers_json, score, details_json, completed_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, quiz_id, json.dumps(answers, ensure_ascii=False), score, json.dumps(details, ensure_ascii=False), datetime.now().isoformat()),
        )
        return cursor.lastrowid  # type: ignore[return-value]


def get_quiz_results(user_id: int, quiz_id: int | None = None) -> list[dict]:
    with _db() as conn:
        if quiz_id:
            rows = conn.execute("SELECT * FROM quiz_results WHERE user_id = ? AND quiz_id = ? ORDER BY completed_at DESC", (user_id, quiz_id)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM quiz_results WHERE user_id = ? ORDER BY completed_at DESC", (user_id,)).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["answers_json"] = json.loads(d["answers_json"])
            d["details_json"] = json.loads(d["details_json"])
            results.append(d)
        return results


# ===================== Exams =====================

def save_exam(user_id: int, title: str, exam_data: dict, material_ids: list[int], duration_minutes: int) -> int:
    with _db() as conn:
        cursor = conn.execute(
            "INSERT INTO exams (user_id, title, exam_json, material_ids, duration_minutes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, title, json.dumps(exam_data, ensure_ascii=False), json.dumps(material_ids), duration_minutes, datetime.now().isoformat()),
        )
        return cursor.lastrowid  # type: ignore[return-value]


def get_all_exams(user_id: int) -> list[dict]:
    with _db() as conn:
        rows = conn.execute("SELECT * FROM exams WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["exam_json"] = json.loads(d["exam_json"])
            d["material_ids"] = json.loads(d["material_ids"])
            results.append(d)
        return results


def get_exam(exam_id: int) -> dict | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM exams WHERE id = ?", (exam_id,)).fetchone()
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
        total_materials = conn.execute("SELECT COUNT(*) FROM materials WHERE user_id = ?", (user_id,)).fetchone()[0]
        total_quizzes = conn.execute("SELECT COUNT(*) FROM quizzes WHERE user_id = ?", (user_id,)).fetchone()[0]
        total_results = conn.execute("SELECT COUNT(*) FROM quiz_results WHERE user_id = ?", (user_id,)).fetchone()[0]
        avg_score_row = conn.execute("SELECT AVG(score) FROM quiz_results WHERE user_id = ?", (user_id,)).fetchone()
        avg_score = round(avg_score_row[0], 1) if avg_score_row[0] is not None else 0.0
        recent_results = conn.execute(
            "SELECT qr.score, q.title, qr.completed_at FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE qr.user_id = ? ORDER BY qr.completed_at DESC LIMIT 10",
            (user_id,),
        ).fetchall()

        return {
            "total_materiales": total_materials,
            "total_quizzes": total_quizzes,
            "quizzes_completados": total_results,
            "puntaje_promedio": avg_score,
            "resultados_recientes": [dict(r) for r in recent_results],
        }
