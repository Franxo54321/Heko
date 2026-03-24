"""
Script de inicialización: crea tablas en PostgreSQL y crea la cuenta admin.
Ejecutar UNA SOLA VEZ después de configurar DATABASE_URL en .env o secrets.

  python scripts/init_postgres.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import storage.database as db

def main():
    print("Inicializando base de datos PostgreSQL...")
    db.init_db()
    print("Tablas creadas.")

    # Crear admin si no existe
    user_id = db.register_user(
        username="admin",
        password="Admin123",
        display_name="Administrador",
        email="francolpez123@gmail.com",
    )
    if user_id is None:
        print("El usuario 'admin' ya existe.")
    else:
        from storage.database import _db, _cur
        with _db() as conn:
            cur = _cur(conn)
            cur.execute(
                "UPDATE users SET is_admin = 1, email_verified = 1 WHERE id = %s",
                (user_id,),
            )
        print(f"Admin creado con id={user_id} (admin/Admin123).")

    print("Listo.")

if __name__ == "__main__":
    main()
