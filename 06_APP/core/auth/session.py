"""
Módulo de autenticación y sesiones.
"""
from datetime import datetime, timedelta


ADMIN_SESSION_MINUTES = 15
PUBLIC_SESSION_MINUTES = 60


def session_expired(last_seen, minutes):
    """Verifica si la sesión expiró."""
    if not last_seen:
        return True
    try:
        marca = datetime.fromisoformat(str(last_seen))
    except Exception:
        return True
    return datetime.now() - marca > timedelta(minutes=minutes)


def _get_session_state():
    """Obtiene session_state de forma lazy para evitar dependencia directa."""
    try:
        import streamlit as st
        return st.session_state
    except ImportError:
        return None


def clear_admin_session():
    """Limpia sesión de admin."""
    state = _get_session_state()
    if state is not None:
        state.admin_user = None
        state.admin_last_seen = ""
        state.admin_login_user = ""
        state.admin_login_pass = ""
        state.admin_force_new_password = ""
        state.admin_force_confirm_password = ""


def clear_public_session():
    """Limpia sesión de usuario público."""
    state = _get_session_state()
    if state is not None:
        state.public_user = None
        state.public_last_seen = ""
        state.public_login_user = ""
        state.public_login_pass = ""


def set_login_session(user):
    """Establece la sesión del usuario."""
    state = _get_session_state()
    if state is None:
        return
    
    role = str(user.get("role", "") or "").strip().lower()
    if role == "admin":
        clear_public_session()
        state.admin_user = user
        state.admin_last_seen = datetime.now().isoformat()
    else:
        clear_admin_session()
        state.public_user = user
        state.public_last_seen = datetime.now().isoformat()
