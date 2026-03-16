"""Servicio de envío de correos para verificación."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import config

logger = logging.getLogger(__name__)


def send_verification_email(to_email: str, code: str, display_name: str = "") -> bool:
    """Envía un correo con el código de verificación de 6 dígitos.

    Devuelve True si se envió correctamente, False si hubo error.
    """
    if not config.SMTP_USER or not config.SMTP_PASSWORD:
        return False, "SMTP_USER o SMTP_PASSWORD no configurados en .env"

    nombre = display_name or "estudiante"

    msg = EmailMessage()
    msg["Subject"] = f"Tu código de verificación: {code}"
    msg["From"] = f"{config.SMTP_FROM_NAME} <{config.SMTP_USER}>"
    msg["To"] = to_email

    html = f"""\
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #4A90D9;">📚 Agente de Estudio</h2>
        <p>Hola <strong>{nombre}</strong>,</p>
        <p>Tu código de verificación es:</p>
        <div style="background: #f0f4ff; border-radius: 10px; padding: 20px; text-align: center; margin: 20px 0;">
            <span style="font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #333;">{code}</span>
        </div>
        <p style="color: #888; font-size: 13px;">Este código expira en <strong>15 minutos</strong>.</p>
        <p style="color: #888; font-size: 13px;">Si no solicitaste este código, puedes ignorar este mensaje.</p>
    </body>
    </html>
    """
    msg.set_content(f"Tu código de verificación es: {code}\nExpira en 15 minutos.")
    msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(msg)
        return True, None
    except Exception as exc:
        logger.error("Error enviando correo a %s: %s", to_email, exc)
        return False, str(exc)
