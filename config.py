import os
from dotenv import load_dotenv

load_dotenv()

def _get(key: str, default: str = "") -> str:
    val = os.getenv(key, "")
    if val:
        return val
    try:
        import streamlit as st
        return str(st.secrets.get(key, default))
    except Exception:
        return default


ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = _get("ANTHROPIC_MODEL") or "claude-sonnet-4-20250514"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "study_agent.db")
DATABASE_URL = _get("DATABASE_URL")

# SMTP para verificación de correo
SMTP_HOST = _get("SMTP_HOST") or "smtp.gmail.com"
SMTP_PORT = int(_get("SMTP_PORT") or "587")
SMTP_USER = _get("SMTP_USER")
SMTP_PASSWORD = _get("SMTP_PASSWORD")
SMTP_FROM_NAME = _get("SMTP_FROM_NAME") or "Agente de Estudio"

os.makedirs(UPLOADS_DIR, exist_ok=True)
