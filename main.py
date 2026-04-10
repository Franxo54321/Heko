"""Interfaz principal del Agente de Estudio — Streamlit."""

from __future__ import annotations

import os
import tempfile

import streamlit as st
import extra_streamlit_components as stx
from streamlit.runtime.scriptrunner import get_script_run_ctx as _get_ctx
from streamlit_cookies_controller import CookieController


import config
from agents import orchestrator, tutor
from storage import database
from services import email_service

# ---------------------------------------------------------------------------
# Inicialización (safe en bare mode — no usa Streamlit)
# ---------------------------------------------------------------------------

orchestrator.init()


def _main() -> None:  # noqa: C901
    st.set_page_config(
        page_title="Agente de Estudio",
        page_icon="📚",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ---------------------------------------------------------------------------
    # Antigravity CSS - glassmorphism, animaciones, profundidad espacial
    # ---------------------------------------------------------------------------
    _css_path = os.path.join(os.path.dirname(__file__), "assets", "style.css")
    if os.path.exists(_css_path):
        with open(_css_path, encoding="utf-8") as _f:
            st.markdown(f"<style>{_f.read()}</style>", unsafe_allow_html=True)

    # Cookie manager para sesión persistente
    cookie_manager = CookieController(key="heko_cookies")

    # CookieController necesita 1-2 ciclos de render para inicializarse.
    # getAll() retorna None mientras no esté listo, dict cuando sí.
    _cookies_ready = cookie_manager.getAll() is not None

    # Estado de sesión
    for key, default in [
        ("tutor_messages", []),
        ("current_quiz", None),
        ("quiz_answers", {}),
        ("user", None),
        ("pending_verification", None),   # {"user_id": int, "email": str, "display_name": str}
        ("session_token", None),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    # Restaurar sesión desde cookie (solo si el controller ya está listo)
    if st.session_state.user is None and _cookies_ready:
        saved_token = cookie_manager.get("heko_session")
        if saved_token:
            user = database.get_user_by_session(saved_token)
            if user:
                st.session_state.user = user
                st.session_state.session_token = saved_token
                st.rerun()


    # =========================================================================
    # AUTENTICACIÓN
    # =========================================================================

    def _show_auth():
        """Muestra pantalla de login / registro / verificación."""
        st.title("📚 Agente de Estudio")

        # ---- Pantalla de verificación pendiente ----
        pv = st.session_state.pending_verification
        if pv:
            st.info(f"Se envió un código de verificación a **{pv['email']}**.")
            code_input = st.text_input("Código de 6 dígitos", max_chars=6, key="verify_code")
            col_v1, col_v2 = st.columns(2)
            with col_v1:
                if st.button("Verificar", type="primary", key="verify_btn"):
                    if database.verify_email_code(pv["user_id"], code_input):
                        user = database.get_user(pv["user_id"])
                        token = database.create_session(pv["user_id"])
                        try:
                            cookie_manager.set("heko_session", token)
                        except Exception:
                            pass
                        st.session_state.user = user
                        st.session_state.session_token = token
                        st.session_state.pending_verification = None
                        st.success("¡Correo verificado! Bienvenido.")
                        st.rerun()
                    else:
                        st.error("Código inválido o expirado.")
            with col_v2:
                if st.button("Reenviar código", key="resend_btn"):
                    new_code = database.create_verification_code(pv["user_id"])
                    sent, err = email_service.send_verification_email(pv["email"], new_code, pv.get("display_name", ""))
                    if sent:
                        st.success("Se reenvió el código.")
                    else:
                        st.error(f"No se pudo enviar el correo. Error SMTP: {err}")
            if st.button("Volver al inicio", key="back_auth_btn"):
                st.session_state.pending_verification = None
                st.rerun()
            return

        # ---- Login / Registro ----
        st.markdown("Inicia sesión o crea una cuenta para comenzar.")
        tab_login, tab_register = st.tabs(["Iniciar sesión", "Registrarse"])

        with tab_login:
            username = st.text_input("Usuario o correo electrónico", key="login_user")
            password = st.text_input("Contraseña", type="password", key="login_pass")
            if st.button("Entrar", type="primary", key="login_btn"):
                if not username or not password:
                    st.error("Completa ambos campos.")
                else:
                    user = database.authenticate_user(username, password)
                    if user:
                        if user.get("is_admin"):
                            # Admin siempre verificado
                            token = database.create_session(user["id"])
                            try:
                                cookie_manager.set("heko_session", token)
                            except Exception:
                                pass
                            st.session_state.user = user
                            st.session_state.session_token = token
                            st.rerun()
                        elif not user.get("email_verified"):
                            # Tiene cuenta pero no verificó: enviar código y pedir verificación
                            code = database.create_verification_code(user["id"])
                            sent, err = email_service.send_verification_email(user.get("email", ""), code, user.get("display_name", ""))
                            st.session_state.pending_verification = {
                                "user_id": user["id"],
                                "email": user.get("email", ""),
                                "display_name": user.get("display_name", ""),
                            }
                            if sent:
                                st.info("Tu correo no está verificado. Se envió un nuevo código.")
                            else:
                                st.warning(f"Tu correo no está verificado y no se pudo enviar el código. Error SMTP: {err}")
                            st.rerun()
                        else:
                            token = database.create_session(user["id"])
                            try:
                                cookie_manager.set("heko_session", token)
                            except Exception:
                                pass
                            st.session_state.user = user
                            st.session_state.session_token = token
                            st.rerun()
                    else:
                        st.error("Usuario o contraseña incorrectos.")

        with tab_register:
            new_user = st.text_input("Nombre de usuario", key="reg_user")
            new_email = st.text_input("Correo electrónico", key="reg_email")
            new_name = st.text_input("Nombre para mostrar (opcional)", key="reg_name")
            new_pass = st.text_input("Contraseña", type="password", key="reg_pass")
            new_pass2 = st.text_input("Confirmar contraseña", type="password", key="reg_pass2")
            if st.button("Crear cuenta", type="primary", key="reg_btn"):
                if not new_user or not new_email or not new_pass:
                    st.error("Completa usuario, correo y contraseña.")
                elif "@" not in new_email or "." not in new_email.split("@")[-1]:
                    st.error("Ingresa un correo electrónico válido.")
                elif len(new_pass) < 4:
                    st.error("La contraseña debe tener al menos 4 caracteres.")
                elif new_pass != new_pass2:
                    st.error("Las contraseñas no coinciden.")
                elif database.email_exists(new_email):
                    st.error("Ese correo electrónico ya está registrado.")
                else:
                    uid = database.register_user(new_user, new_pass, new_name, new_email)
                    if uid is None:
                        st.error("Ese nombre de usuario ya existe.")
                    else:
                        # Crear materias por defecto
                        for s in ["Física", "Cálculo", "Programación"]:
                            database.create_subject(uid, s)
                        # Si es admin, marcar como verificado y loguear
                        user = database.get_user(uid)
                        if user.get("is_admin"):
                            token = database.create_session(uid)
                            try:
                                cookie_manager.set("heko_session", token)
                            except Exception:
                                pass
                            st.session_state.user = user
                            st.session_state.session_token = token
                            st.success("¡Cuenta admin creada y verificada!")
                            st.rerun()
                        else:
                            # Generar y enviar código de verificación
                            code = database.create_verification_code(uid)
                            sent, err = email_service.send_verification_email(new_email, code, new_name or new_user)
                            st.session_state.pending_verification = {
                                "user_id": uid,
                                "email": new_email,
                                "display_name": new_name or new_user,
                            }
                            if sent:
                                st.success("¡Cuenta creada! Se envió un código de verificación a tu correo.")
                            else:
                                st.warning(f"Cuenta creada pero no se pudo enviar el correo. Error SMTP: {err}")
                            st.rerun()


    if st.session_state.user is None:
        if not _cookies_ready:
            # Controller aún no listo; st.stop() espera al próximo render
            # (CookieController dispara rerun automático al inicializarse)
            st.stop()
        _show_auth()
        st.stop()

    USER: dict = st.session_state.get("user") or {}  # type: ignore[assignment]
    UID: int = USER.get("id", 0)  # type: ignore[assignment]
    if not UID:
        st.stop()


    # ---------------------------------------------------------------------------
    # Helper: lista de materias del usuario
    # ---------------------------------------------------------------------------

    def _subject_options() -> list[str]:
        """Devuelve las materias del usuario + opción Otra."""
        return database.get_user_subjects(UID) + ["Otra"]


    # ---------------------------------------------------------------------------
    # Sidebar — Navegación
    # ---------------------------------------------------------------------------

    st.sidebar.title("📚 Agente de Estudio")
    st.sidebar.markdown(f"👤 **{USER.get('display_name') or USER.get('username', '')}**")
    if st.sidebar.button("Cerrar sesión"):
        if st.session_state.session_token:
            database.delete_session(st.session_state.session_token)
        try:
            cookie_manager.remove("heko_session")
        except Exception:
            pass
        st.session_state.user = None
        st.session_state.session_token = None
        st.rerun()
    st.sidebar.divider()

    page_list = [
        "Inicio",
        "Subir Material",
        "Mis Materiales",
        "Plan de Estudio",
        "Quizzes",
        "Modelo de Examen",
        "Tutor / Resolver Problemas",
        "Mi Progreso",
        "Mis Materias",
    ]
    if USER.get("is_admin"):
        page_list.append("Admin")

    page = st.sidebar.radio(
        "Navegación",
        page_list,
    )

    # Validar API key
    if not config.ANTHROPIC_API_KEY or config.ANTHROPIC_API_KEY == "tu-api-key-aqui":
        st.sidebar.divider()
        api_key = st.sidebar.text_input("🔑 Anthropic API Key", type="password")
        if api_key:
            config.ANTHROPIC_API_KEY = api_key
            os.environ["ANTHROPIC_API_KEY"] = api_key
            st.sidebar.success("API Key configurada")

    # =========================================================================
    # PÁGINAS
    # =========================================================================


    # ---------------------------------------------------------------------------
    # Mis Materias (CRUD)
    # ---------------------------------------------------------------------------
    if page == "Mis Materias":
        st.title("⚙️ Gestionar Materias")
        st.markdown("Crea o elimina materias. Estas aparecerán como opciones al subir materiales, crear quizzes, etc.")

        subjects = database.get_user_subjects(UID)

        # Crear nueva materia
        col_new, col_btn = st.columns([3, 1])
        new_subj = col_new.text_input("Nueva materia", placeholder="Ej: Álgebra Lineal")
        if col_btn.button("➕ Crear", type="primary") and new_subj.strip():
            result = database.create_subject(UID, new_subj.strip())
            if result is None:
                st.warning("Esa materia ya existe.")
            else:
                st.success(f"Materia **{new_subj.strip()}** creada.")
                st.rerun()

        st.divider()
        st.subheader("Materias actuales")

        if subjects:
            for s in subjects:
                col_name, col_del = st.columns([4, 1])
                col_name.markdown(f"📘 **{s}**")
                if col_del.button("🗑️", key=f"del_subj_{s}"):
                    database.delete_subject(UID, s)
                    st.rerun()
        else:
            st.info("No tenés materias creadas. Creá una arriba.")


    # ---------------------------------------------------------------------------
    # 🏠 Inicio
    # ---------------------------------------------------------------------------
    elif page == "Inicio":
        st.title("📚 Agente de Estudio Inteligente")
        st.markdown(
            """
        Bienvenido a tu asistente de estudio personalizado.

        ### ¿Qué puedo hacer?

        | Función | Descripción |
        |---|---|
        | **📄 Subir Material** | Carga PDFs e imágenes, el agente los lee, interpreta y resume |
        | **📋 Mis Materiales** | Consulta todos los materiales cargados y sus resúmenes |
        | **📝 Plan de Estudio** | Genera un plan personalizado basado en tus materiales |
        | **❓ Quizzes** | Crea quizzes de autoevaluación y mide tu progreso |
        | **📑 Modelo de Examen** | Genera exámenes completos simulando evaluaciones reales |
        | **🎓 Tutor** | Resuelve problemas paso a paso con explicaciones detalladas |
        | **📊 Mi Progreso** | Visualiza tus estadísticas y evolución |
        | **⚙️ Mis Materias** | Crea y elimina materias personalizadas |

        ---
        **Para comenzar**, sube tus materiales de estudio desde la sección **📄 Subir Material**.
        """
        )

        # Mini dashboard
        stats = database.get_progress_stats(UID)
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Materiales", stats["total_materiales"])
        col2.metric("Quizzes creados", stats["total_quizzes"])
        col3.metric("Quizzes resueltos", stats["quizzes_completados"])
        col4.metric("Puntaje promedio", f"{stats['puntaje_promedio']}%")

        # Subida rápida de archivos por unidades
        st.divider()
        st.subheader("📂 Subir archivos por unidad")

        units_existing = database.get_all_units(UID)
        unit_choice = st.radio(
            "Seleccionar unidad",
            ["Nueva unidad"] + units_existing,
            horizontal=True,
            key="home_unit_choice",
        )
        if unit_choice == "Nueva unidad":
            unit_name = st.text_input("Nombre de la nueva unidad", placeholder="Ej: Unidad 1 - Cinemática", key="home_new_unit")
        else:
            unit_name = unit_choice

        subj_opts = _subject_options()
        subject_home = st.selectbox("Materia", subj_opts, key="home_subj")
        if subject_home == "Otra":
            subject_home = st.text_input("Especifica la materia", key="home_subj_other")

        home_files = st.file_uploader(
            "Arrastra uno o varios archivos",
            type=["pdf", "png", "jpg", "jpeg", "gif", "webp"],
            accept_multiple_files=True,
            key="home_uploader",
        )

        if home_files and unit_name and st.button("🚀 Subir a esta unidad", type="primary", key="home_upload_btn"):
            for uploaded_file in home_files:
                with st.spinner(f"Procesando {uploaded_file.name}..."):
                    suffix = os.path.splitext(uploaded_file.name)[1]
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(uploaded_file.read())
                        tmp_path = tmp.name
                    try:
                        if suffix.lower() == ".pdf":
                            result = orchestrator.process_pdf(tmp_path, user_id=UID, subject=subject_home, unit=unit_name)
                        else:
                            result = orchestrator.process_image(tmp_path, user_id=UID, subject=subject_home, unit=unit_name)
                        st.success(f"✅ **{uploaded_file.name}** → {unit_name}")
                    except Exception as e:
                        st.error(f"Error procesando {uploaded_file.name}: {e}")
                    finally:
                        os.unlink(tmp_path)
            st.rerun()

        # Materiales agrupados por unidad
        st.divider()
        st.subheader("📚 Materiales por unidad")
        all_units = database.get_all_units(UID)
        if all_units:
            for u in all_units:
                mats = database.get_materials_by_unit(UID, u)
                with st.expander(f"📁 {u} ({len(mats)} archivo{'s' if len(mats) != 1 else ''})"):
                    for m in mats:
                        icon = "📄" if m["file_type"] == "pdf" else "🖼️"
                        st.markdown(f"- {icon} **{m['filename']}** — {m['subject']} ({m['created_at'][:10]})")
        else:
            st.caption("No hay materiales asignados a unidades aún.")


    # ---------------------------------------------------------------------------
    # Subir Material
    # ---------------------------------------------------------------------------
    elif page == "Subir Material":
        st.title("Subir Material de Estudio")

        subj_opts = _subject_options()
        subject = st.selectbox("Materia", subj_opts)
        if subject == "Otra":
            subject = st.text_input("Especifica la materia")

        existing_units = database.get_all_units(UID)
        unit_opt = st.radio("Asignar a unidad", ["Sin unidad", "Nueva unidad"] + existing_units, horizontal=True, key="upload_unit_opt")
        if unit_opt == "Nueva unidad":
            upload_unit = st.text_input("Nombre de la unidad", key="upload_new_unit")
        elif unit_opt == "Sin unidad":
            upload_unit = ""
        else:
            upload_unit = unit_opt

        uploaded_files = st.file_uploader(
            "Arrastra archivos aquí",
            type=["pdf", "png", "jpg", "jpeg", "gif", "webp"],
            accept_multiple_files=True,
        )

        if uploaded_files and st.button("🚀 Procesar archivos", type="primary"):
            for uploaded_file in uploaded_files:
                with st.spinner(f"Procesando {uploaded_file.name}..."):
                    suffix = os.path.splitext(uploaded_file.name)[1]
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(uploaded_file.read())
                        tmp_path = tmp.name

                    try:
                        if suffix.lower() == ".pdf":
                            result = orchestrator.process_pdf(tmp_path, user_id=UID, subject=subject, unit=upload_unit)
                            st.success(f"✅ **{uploaded_file.name}** procesado — {result.get('images_processed', 0)} imágenes extraídas")
                        else:
                            result = orchestrator.process_image(tmp_path, user_id=UID, subject=subject, unit=upload_unit)
                            st.success(f"✅ **{uploaded_file.name}** interpretado")

                        with st.expander(f"📝 Resumen: {uploaded_file.name}"):
                            st.markdown(result.get("summary", ""))
                    except Exception as e:
                        st.error(f"Error procesando {uploaded_file.name}: {e}")
                    finally:
                        os.unlink(tmp_path)


    # ---------------------------------------------------------------------------
    # Mis Materiales
    # ---------------------------------------------------------------------------
    elif page == "Mis Materiales":
        st.title("Mis Materiales")

        materials = database.get_all_materials(UID)
        if not materials:
            st.info("No hay materiales cargados. Ve a **Subir Material** para comenzar.")
        else:
            # Filtros
            st.subheader("Filtros")
            col_f1, col_f2 = st.columns(2)

            all_subjects = sorted(set(m["subject"] for m in materials if m["subject"]))
            all_units_list = sorted(set(m.get("unit", "") for m in materials if m.get("unit", "")))

            filter_subject = col_f1.selectbox("Filtrar por materia", ["Todas"] + all_subjects, key="filter_subj")
            filter_unit = col_f2.selectbox("Filtrar por unidad", ["Todas"] + all_units_list, key="filter_unit")

            # Aplicar filtros
            filtered = materials
            if filter_subject != "Todas":
                filtered = [m for m in filtered if m["subject"] == filter_subject]
            if filter_unit != "Todas":
                filtered = [m for m in filtered if m.get("unit", "") == filter_unit]

            st.caption(f"Mostrando {len(filtered)} de {len(materials)} materiales")
            st.divider()

            # Agrupar por unidad
            units_map: dict[str, list] = {}
            for mat in filtered:
                u = mat.get("unit", "") or "Sin unidad"
                units_map.setdefault(u, []).append(mat)

            view_mode = st.radio("Vista", ["Por unidad", "Lista completa"], horizontal=True, key="mat_view")

            if view_mode == "Por unidad":
                for unit_label, mats in units_map.items():
                    st.subheader(f"📁 {unit_label}" if unit_label != "Sin unidad" else "📁 Sin unidad asignada")
                    for mat in mats:
                        with st.expander(f"{'📄' if mat['file_type'] == 'pdf' else '🖼️'} {mat['filename']} — {mat['subject']} ({mat['created_at'][:10]})"):
                            tab1, tab2 = st.tabs(["Resumen", "Texto completo"])
                            with tab1:
                                st.markdown(mat["summary"])
                            with tab2:
                                st.text_area("Texto extraído", mat["raw_text"], height=300, disabled=True, key=f"txt_{mat['id']}")
                            col_a, col_b = st.columns(2)
                            with col_a:
                                if st.button("🗑️ Eliminar", key=f"del_{mat['id']}"):
                                    database.delete_material(mat["id"])
                                    st.rerun()
                            with col_b:
                                new_unit = st.text_input("Mover a unidad", value=mat.get("unit", ""), key=f"mu_{mat['id']}")
                                if new_unit != mat.get("unit", "") and st.button("📂 Mover", key=f"mv_{mat['id']}"):
                                    database.update_material_unit(mat["id"], new_unit)
                                    st.rerun()
            else:
                for mat in filtered:
                    with st.expander(f"{'📄' if mat['file_type'] == 'pdf' else '🖼️'} {mat['filename']} — {mat['subject']} | {mat.get('unit', '') or 'Sin unidad'} ({mat['created_at'][:10]})"):
                        tab1, tab2 = st.tabs(["Resumen", "Texto completo"])
                        with tab1:
                            st.markdown(mat["summary"])
                        with tab2:
                            st.text_area("Texto extraído", mat["raw_text"], height=300, disabled=True, key=f"txtf_{mat['id']}")
                        if st.button("🗑️ Eliminar", key=f"delf_{mat['id']}"):
                            database.delete_material(mat["id"])
                            st.rerun()


    # ---------------------------------------------------------------------------
    # 📝 Plan de Estudio
    # ---------------------------------------------------------------------------
    elif page == "Plan de Estudio":
        st.title("Generar Plan de Estudio")

        materials = database.get_all_materials(UID)
        if not materials:
            st.info("Primero sube materiales de estudio.")
        else:
            mat_options = {f"{m['filename']} ({m['subject']})": m["id"] for m in materials}
            selected = st.multiselect("Materiales a incluir (vacío = todos)", list(mat_options.keys()))
            selected_ids = [mat_options[s] for s in selected] if selected else None

            col1, col2 = st.columns(2)
            days = col1.number_input("Días disponibles", min_value=1, max_value=90, value=7)
            hours = col2.number_input("Horas por día", min_value=0.5, max_value=12.0, value=3.0, step=0.5)

            priority = st.text_input("Temas prioritarios (separados por coma)", "")
            priority_list = [t.strip() for t in priority.split(",") if t.strip()] if priority else None

            title = st.text_input("Título del plan", f"Plan de estudio - {days} días")

            if st.button("📝 Generar Plan", type="primary"):
                with st.spinner("Generando plan de estudio..."):
                    result = orchestrator.create_study_plan(
                        user_id=UID,
                        material_ids=selected_ids,
                        days=days,
                        hours_per_day=hours,
                        priority_topics=priority_list,
                        title=title,
                    )
                if "error" in result:
                    st.error(result["error"])
                else:
                    st.success("Plan generado exitosamente")
                    st.markdown(result["plan"])

        # Planes existentes
        st.divider()
        st.subheader("Planes guardados")
        plans = database.get_all_study_plans(UID)
        if plans:
            for plan in plans:
                with st.expander(f"📝 {plan['title']} ({plan['created_at'][:10]})"):
                    st.markdown(plan["plan_markdown"])
        else:
            st.caption("No hay planes guardados aún.")


    # ---------------------------------------------------------------------------
    # Quizzes
    # ---------------------------------------------------------------------------
    elif page == "Quizzes":
        st.title("Quizzes de Autoevaluación")

        tab_create, tab_solve, tab_history = st.tabs(["Crear Quiz", "Resolver Quiz", "Historial"])

        # --- Crear ---
        with tab_create:
            materials = database.get_all_materials(UID)
            if not materials:
                st.info("Primero sube materiales de estudio.")
            else:
                mat_options = {f"{m['filename']} ({m['subject']})": m["id"] for m in materials}
                selected = st.multiselect("Materiales (vacío = todos)", list(mat_options.keys()), key="quiz_mats")
                selected_ids = [mat_options[s] for s in selected] if selected else None

                col1, col2, col3 = st.columns(3)
                num_q = col1.number_input("Número de preguntas", 5, 30, 10)
                diff = col2.selectbox("Dificultad", ["facil", "media", "dificil"])
                subj_opts = [""] + database.get_user_subjects(UID)
                subject = col3.selectbox("Materia", subj_opts, key="quiz_subj")

                if st.button("🎯 Generar Quiz", type="primary"):
                    with st.spinner("Generando quiz..."):
                        result = orchestrator.create_quiz(
                            user_id=UID,
                            material_ids=selected_ids,
                            num_questions=num_q,
                            difficulty=diff,
                            subject=subject,
                        )
                    if "error" in result:
                        st.error(result["error"])
                    else:
                        st.session_state.current_quiz = result
                        st.success(f"Quiz generado: {result['quiz'].get('titulo', 'Quiz')}")
                        st.info("Ve a la pestaña **Resolver Quiz** para responderlo.")

        # --- Resolver ---
        with tab_solve:
            quizzes = database.get_all_quizzes(UID)
            if not quizzes:
                st.info("No hay quizzes generados aún.")
            else:
                quiz_options = {f"[{q['id']}] {q['title']} ({q['created_at'][:10]})": q for q in quizzes}
                selected_quiz_label = st.selectbox("Selecciona un quiz", list(quiz_options.keys()))
                selected_quiz = quiz_options[selected_quiz_label]
                quiz_data = selected_quiz["quiz_json"]
                preguntas = quiz_data.get("preguntas", [])

                if preguntas:
                    st.subheader(quiz_data.get("titulo", "Quiz"))
                    answers = {}

                    for p in preguntas:
                        st.markdown(f"**Pregunta {p['id']}** ({p.get('dificultad', 'media')})")
                        st.markdown(p["enunciado"])

                        if p["tipo"] == "opcion_multiple":
                            opciones = p.get("opciones", [])
                            ans = st.radio(
                                "Selecciona tu respuesta",
                                opciones,
                                key=f"q_{selected_quiz['id']}_{p['id']}",
                            )
                            answers[p["id"]] = ans[0] if ans else ""

                        elif p["tipo"] == "verdadero_falso":
                            ans = st.radio(
                                "Selecciona",
                                ["Verdadero", "Falso"],
                                key=f"q_{selected_quiz['id']}_{p['id']}",
                            )
                            answers[p["id"]] = ans

                        elif p["tipo"] == "desarrollo":
                            ans = st.text_area(
                                "Tu respuesta",
                                key=f"q_{selected_quiz['id']}_{p['id']}",
                            )
                            answers[p["id"]] = ans

                        st.divider()

                    if st.button("✅ Enviar respuestas", type="primary"):
                        with st.spinner("Calificando..."):
                            results = orchestrator.submit_quiz_answers(UID, selected_quiz["id"], answers)

                        if "error" in results:
                            st.error(results["error"])
                        else:
                            score = results["puntaje"]
                            if score >= 80:
                                st.balloons()
                                st.success(f"🎉 Puntaje: **{score}%** — ¡Excelente!")
                            elif score >= 60:
                                st.warning(f"📊 Puntaje: **{score}%** — Buen trabajo, pero hay margen de mejora.")
                            else:
                                st.error(f"📊 Puntaje: **{score}%** — Necesitas repasar más.")

                            st.subheader("Detalle de respuestas")
                            for d in results.get("detalle", []):
                                icon = "✅" if d["correcto"] else "❌"
                                with st.expander(f"{icon} Pregunta {d['id']}: {d['enunciado'][:80]}..."):
                                    st.markdown(f"**Tu respuesta:** {d['tu_respuesta']}")
                                    st.markdown(f"**Respuesta correcta:** {d['respuesta_correcta']}")
                                    st.markdown(f"**Explicación:** {d['explicacion']}")

        # --- Historial ---
        with tab_history:
            all_results = database.get_quiz_results(UID)
            if all_results:
                for r in all_results:
                    st.markdown(
                        f"**Quiz #{r['quiz_id']}** — Puntaje: **{r['score']}%** — {r['completed_at'][:16]}"
                    )
            else:
                st.caption("No hay resultados aún.")


    # ---------------------------------------------------------------------------
    # 📑 Modelo de Examen
    # ---------------------------------------------------------------------------
    elif page == "Modelo de Examen":
        st.title("Generar Modelo de Examen")

        materials = database.get_all_materials(UID)
        if not materials:
            st.info("Primero sube materiales de estudio.")
        else:
            mat_options = {f"{m['filename']} ({m['subject']})": m["id"] for m in materials}
            selected = st.multiselect("Materiales (vacío = todos)", list(mat_options.keys()), key="exam_mats")
            selected_ids = [mat_options[s] for s in selected] if selected else None

            duration = st.number_input("Duración del examen (minutos)", 30, 300, 120, step=15)

            if st.button("📑 Generar Examen", type="primary"):
                with st.spinner("Generando modelo de examen..."):
                    result = orchestrator.create_exam(
                        user_id=UID,
                        material_ids=selected_ids,
                        duration_minutes=duration,
                    )

                if "error" in result:
                    st.error(result["error"])
                else:
                    exam = result["exam"]
                    st.success(f"Examen generado: {exam.get('titulo', 'Examen')}")

                    st.markdown(f"**Duración:** {exam.get('duracion_minutos', duration)} minutos")
                    st.markdown(f"**Instrucciones:** {exam.get('instrucciones', '')}")

                    for seccion in exam.get("secciones", []):
                        st.subheader(seccion["nombre"])
                        st.caption(f"Puntaje total: {seccion.get('puntaje_total', 'N/A')} puntos")

                        for p in seccion.get("preguntas", []):
                            st.markdown(f"**{p['id']}.** ({p.get('puntaje', '?')} pts — {p.get('dificultad', 'media')}) {p['enunciado']}")
                            if p.get("opciones"):
                                for opt in p["opciones"]:
                                    st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;{opt}")
                            st.divider()

                    with st.expander("🔑 Ver soluciones"):
                        for seccion in exam.get("secciones", []):
                            st.markdown(f"### {seccion['nombre']}")
                            for p in seccion.get("preguntas", []):
                                st.markdown(f"**{p['id']}.** {p.get('respuesta_correcta', 'N/A')}")
                                if p.get("criterios_evaluacion"):
                                    st.caption(f"Criterios: {p['criterios_evaluacion']}")

        # Exámenes existentes
        st.divider()
        st.subheader("Exámenes guardados")
        exams = database.get_all_exams(UID)
        if exams:
            for ex in exams:
                exam_data = ex["exam_json"]
                with st.expander(f"📑 {exam_data.get('titulo', 'Examen')} ({ex['created_at'][:10]})"):
                    st.json(exam_data)
        else:
            st.caption("No hay exámenes guardados aún.")


    # ---------------------------------------------------------------------------
    # Tutor / Resolver Problemas
    # ---------------------------------------------------------------------------
    elif page == "Tutor / Resolver Problemas":
        st.title("Tutor Inteligente")

        tab_solve, tab_file, tab_guide, tab_chat = st.tabs(["Resolver Problema", "📎 Resolver desde archivo", "Práctica Guiada", "Chat con Tutor"])

        # --- Resolver ---
        with tab_solve:
            st.markdown("Escribe un problema y el tutor lo resolverá paso a paso con explicaciones detalladas.")
            subj_opts = [""] + database.get_user_subjects(UID)
            subject = st.selectbox("Materia", subj_opts, key="tutor_subj")
            problem = st.text_area("Describe el problema", height=150, key="solve_problem", placeholder="Ej: Calcula la integral de x² sen(x) dx")

            if st.button("🔍 Resolver paso a paso", type="primary") and problem:
                with st.spinner("Resolviendo..."):
                    solution = orchestrator.solve_problem_step_by_step(problem, subject=subject)
                st.markdown(solution)

        # --- Resolver desde archivo ---
        with tab_file:
            st.markdown("Sube un archivo (PDF o imagen) con problemas. El tutor te guiará paso a paso en cada uno.")
            subj_opts_f = [""] + database.get_user_subjects(UID)
            subject_f = st.selectbox("Materia", subj_opts_f, key="tutor_file_subj")
            problem_file = st.file_uploader(
                "Adjuntar archivo con problemas",
                type=["pdf", "png", "jpg", "jpeg", "gif", "webp"],
                key="tutor_file_upload",
            )

            if problem_file:
                if "tutor_file_text" not in st.session_state or st.session_state.get("tutor_file_name") != problem_file.name:
                    suffix = os.path.splitext(problem_file.name)[1]
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(problem_file.read())
                        tmp_path = tmp.name
                    try:
                        if suffix.lower() == ".pdf":
                            from agents import pdf_reader
                            extracted = pdf_reader.extract_text_from_pdf(tmp_path)
                        else:
                            from agents import image_reader as ir
                            extracted = ir.interpret_image_file(tmp_path, question="Lista todos los problemas o ejercicios que aparecen en esta imagen. Transcríbelos fielmente.")
                        st.session_state.tutor_file_text = extracted
                        st.session_state.tutor_file_name = problem_file.name
                        st.session_state.tutor_file_solutions = {}
                        st.session_state.tutor_file_guided = {}
                    except Exception as e:
                        st.error(f"Error leyendo archivo: {e}")
                        st.session_state.tutor_file_text = ""
                    finally:
                        os.unlink(tmp_path)

                file_text = st.session_state.get("tutor_file_text", "")
                if file_text:
                    with st.expander("📄 Contenido extraído del archivo", expanded=False):
                        st.text_area("Texto", file_text, height=200, disabled=True, key="tutor_file_preview")

                    st.divider()

                    if st.button("🔓 Ver todo resuelto", type="secondary", key="solve_all_btn"):
                        with st.spinner("Resolviendo todos los problemas del archivo..."):
                            full_solution = orchestrator.solve_problem_step_by_step(
                                f"Resuelve TODOS los problemas/ejercicios del siguiente texto paso a paso, con explicaciones detalladas para cada uno:\n\n{file_text}",
                                subject=subject_f,
                            )
                        st.session_state.tutor_file_full_solution = full_solution

                    if st.session_state.get("tutor_file_full_solution"):
                        st.subheader("Solución completa")
                        st.markdown(st.session_state.tutor_file_full_solution)

                    st.divider()

                    st.subheader("Modo guiado — problema por problema")
                    st.markdown("Escribe tu intento de solución para un problema y el tutor te guiará.")
                    problem_ref = st.text_area(
                        "Copia/escribe el problema que quieres resolver",
                        height=80,
                        key="tutor_file_selected_problem",
                        placeholder="Pega aquí el enunciado del problema del archivo...",
                    )
                    user_attempt = st.text_area(
                        "Tu intento de solución (opcional, déjalo vacío para que te guíe desde cero)",
                        height=100,
                        key="tutor_file_attempt",
                    )
                    if st.button("📝 Guiar resolución", type="primary", key="guide_file_btn") and problem_ref:
                        with st.spinner("Analizando..."):
                            if user_attempt.strip():
                                feedback = orchestrator.guided_practice(problem_ref, user_attempt, subject=subject_f)
                            else:
                                feedback = orchestrator.solve_problem_step_by_step(
                                    f"Guía al estudiante paso a paso para resolver este problema. No des la respuesta directa, haz preguntas orientadoras y da pistas:\n\n{problem_ref}",
                                    subject=subject_f,
                                )
                        st.markdown(feedback)

        # --- Práctica guiada ---
        with tab_guide:
            st.markdown("Escribe un problema (o sube una foto) y tu intento de solución. El tutor evaluará tu trabajo y te guiará.")
            subj_opts_g = [""] + database.get_user_subjects(UID)
            subject_g = st.selectbox("Materia", subj_opts_g, key="guide_subj")

            guide_image = st.file_uploader(
                "📷 Subir foto del problema (opcional)",
                type=["png", "jpg", "jpeg", "gif", "webp"],
                key="guide_image_upload",
            )

            if guide_image and ("guide_img_name" not in st.session_state or st.session_state.guide_img_name != guide_image.name):
                with st.spinner("Analizando imagen..."):
                    suffix = os.path.splitext(guide_image.name)[1]
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(guide_image.read())
                        tmp_path = tmp.name
                    try:
                        from agents import image_reader as ir
                        interpreted = ir.interpret_image_file(tmp_path, question="Transcribe fielmente todos los problemas o ejercicios que aparecen en esta imagen.")
                        st.session_state.guide_img_text = interpreted
                        st.session_state.guide_img_name = guide_image.name
                    except Exception as e:
                        st.error(f"Error interpretando imagen: {e}")
                        st.session_state.guide_img_text = ""
                    finally:
                        os.unlink(tmp_path)

            img_text = st.session_state.get("guide_img_text", "")
            if img_text:
                with st.expander("📄 Problema detectado en la imagen", expanded=True):
                    st.markdown(img_text)

            problem_g = st.text_area(
                "El problema" + (" (puedes editar lo detectado)" if img_text else ""),
                value=img_text if img_text else "",
                height=100,
                key="guide_problem",
            )
            attempt = st.text_area("Tu intento de solución", height=150, key="guide_attempt")

            if st.button("📝 Evaluar mi intento", type="primary") and problem_g and attempt:
                with st.spinner("Analizando tu intento..."):
                    feedback = orchestrator.guided_practice(problem_g, attempt, subject=subject_g)
                st.markdown(feedback)

        # --- Chat ---
        with tab_chat:
            st.markdown("Conversa con el tutor. Haz preguntas, pide explicaciones, aclara dudas.")
            subj_opts_c = ["General"] + database.get_user_subjects(UID)
            subject_c = st.selectbox("Materia del contexto", subj_opts_c, key="chat_subj")

            for msg in st.session_state.tutor_messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

            user_input = st.chat_input("Escribe tu pregunta...")
            if user_input:
                st.session_state.tutor_messages.append({"role": "user", "content": user_input})
                with st.chat_message("user"):
                    st.markdown(user_input)

                with st.chat_message("assistant"):
                    with st.spinner("Pensando..."):
                        response = tutor.chat_tutor(st.session_state.tutor_messages, subject=subject_c)
                    st.markdown(response)

                st.session_state.tutor_messages.append({"role": "assistant", "content": response})

            if st.session_state.tutor_messages and st.button("🗑️ Limpiar chat"):
                st.session_state.tutor_messages = []
                st.rerun()


    # ---------------------------------------------------------------------------
    # Mi Progreso
    # ---------------------------------------------------------------------------
    elif page == "Mi Progreso":
        st.title("Mi Progreso")

        stats = database.get_progress_stats(UID)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📄 Materiales cargados", stats["total_materiales"])
        col2.metric("❓ Quizzes creados", stats["total_quizzes"])
        col3.metric("✅ Quizzes resueltos", stats["quizzes_completados"])
        col4.metric("📊 Puntaje promedio", f"{stats['puntaje_promedio']}%")

        st.divider()
        st.subheader("Resultados recientes")

        recent = stats.get("resultados_recientes", [])
        if recent:
            for r in recent:
                score = r["score"]
                icon = "🟢" if score >= 80 else "🟡" if score >= 60 else "🔴"
                st.markdown(f"{icon} **{r['title']}** — {score}% — {r['completed_at'][:16]}")
        else:
            st.info("No hay resultados aún. Resuelve quizzes para ver tu progreso aquí.")

        # Materiales por materia
        st.divider()
        st.subheader("Materiales por materia")
        materials = database.get_all_materials(UID)
        if materials:
            subjects = {}
            for m in materials:
                subj = m["subject"] or "Sin materia"
                subjects[subj] = subjects.get(subj, 0) + 1
            for subj, count in subjects.items():
                st.markdown(f"- **{subj}**: {count} material(es)")

    # ---------------------------------------------------------------------------
    # Admin
    # ---------------------------------------------------------------------------
    elif page == "Admin":
        if not USER.get("is_admin"):
            st.error("No tienes permisos de administrador.")
            st.stop()

        st.title("Panel de Administración")
        st.markdown("Gestiona los usuarios registrados en la plataforma.")

        all_users = database.get_all_users()
        st.metric("Total de usuarios", len(all_users))
        st.divider()

        for u in all_users:
            uid_u = u["id"]
            is_current = uid_u == UID
            with st.expander(
                f"{'👑 ' if u['is_admin'] else ''}{u['display_name'] or u['username']} — {u['email'] or 'sin correo'}"
                + (" *(tú)*" if is_current else ""),
                expanded=False,
            ):
                col_info, col_actions = st.columns([2, 1])
                with col_info:
                    st.markdown(f"**ID:** {uid_u}")
                    st.markdown(f"**Usuario:** {u['username']}")
                    st.markdown(f"**Email:** {u['email'] or '—'}")
                    st.markdown(f"**Verificado:** {'✅' if u['email_verified'] else '❌'}")
                    st.markdown(f"**Admin:** {'✅' if u['is_admin'] else '❌'}")
                    st.markdown(f"**Registrado:** {u['created_at'][:16]}")

                with col_actions:
                    # --- Editar ---
                    with st.popover("✏️ Editar", use_container_width=True):
                        new_display = st.text_input("Nombre", value=u["display_name"] or "", key=f"adm_name_{uid_u}")
                        new_email = st.text_input("Email", value=u["email"] or "", key=f"adm_email_{uid_u}")
                        new_admin = st.checkbox("Es admin", value=bool(u["is_admin"]), key=f"adm_admin_{uid_u}")
                        new_pass = st.text_input("Nueva contraseña (dejar vacío para no cambiar)", type="password", key=f"adm_pass_{uid_u}")
                        if st.button("Guardar", key=f"adm_save_{uid_u}", type="primary"):
                            database.update_user_admin(uid_u, new_display, new_email, new_admin)
                            if new_pass:
                                database.reset_user_password(uid_u, new_pass)
                            st.success("Usuario actualizado.")
                            st.rerun()

                    # --- Eliminar (no se puede eliminar a sí mismo) ---
                    if not is_current:
                        with st.popover("🗑️ Eliminar", use_container_width=True):
                            st.warning(f"¿Seguro que deseas eliminar a **{u['username']}**? Se borrarán TODOS sus datos.")
                            if st.button("Confirmar eliminación", key=f"adm_del_{uid_u}", type="primary"):
                                database.delete_user(uid_u)
                                st.success(f"Usuario {u['username']} eliminado.")
                                st.rerun()



if _get_ctx() is not None:
    _main()
