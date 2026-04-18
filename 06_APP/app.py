import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
import os
import json
import re
import hmac
from pathlib import Path
import requests
from typing import Optional

from database import init_db, update_resultado_con_cuota, save_picks, get_bankroll_inicial, get_stake_porcentaje, update_config, get_config_value, create_user, authenticate_user, get_all_users, update_user_status, update_user_profile, update_user_password, get_cached_team_logo, save_cached_team_logo, save_prepared_match, get_prepared_matches, update_subscription, get_user_subscription, get_subscription_stats, migrate_subscription_fields, save_motor_pick_log, get_motor_pick_logs
from import_utils import validate_and_load_file
from backtest_engine import es_handicap_asiatico
from config import IAS_LIST, STAKE_PORCENTAJE, get_usd_to_cop, MOSTRAR_USD, API_FOOTBALL_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ADMIN_PASSWORD, BOOTSTRAP_TOKEN
from services.league_service import get_league_key, detectar_liga_automatica, LIGAS_NOMBRES
from services.match_prepare_service import parsear_entrada_partido, preparar_partido_desde_api, construir_ficha_preparada, buscar_logo_equipo, obtener_partidos_por_fecha, obtener_partidos_proximos, obtener_partidos_por_fecha_local, obtener_partidos_proximos_locales
from services.ollama_context_service import analizar_contexto_ollama, sugerir_campos_contexto_ollama
from core.judge import consolidar_picks, guardar_veredicto
from core.motor.engine import analizar_partido_motor

# Imports de módulos propios
from core.auth.session import (
    session_expired as _session_expired,
    clear_admin_session as _clear_admin_session,
    clear_public_session as _clear_public_session,
    set_login_session as _set_login_session,
    ADMIN_SESSION_MINUTES,
    PUBLIC_SESSION_MINUTES,
)
from core.ui.components import (
    render_public_card as _render_public_card,
    market_icon as _market_icon,
    team_initials as _team_initials,
    team_logo_html as _team_logo_html,
    get_team_logo_cached as _get_team_logo_cached,
    render_pick_detail as _render_pick_detail,
    render_section_banner as _render_section_banner,
    filtrar_df_por_periodo as _filtrar_df_por_periodo,
    resumen_periodo_dashboard as _resumen_periodo_dashboard,
    render_empty_state as _render_empty_state,
)
from core.utils import cargar_prompt_automatico, cargar_comparativas, guardar_comparativas

# Cliente backend mínimo
BACKEND_URL = "http://localhost:8000"

def fetch_backend_picks(incluir_alternativas: Optional[bool] = False):
    import time
    start_time = time.time()
    try:
        response = requests.get(
            f"{BACKEND_URL}/api/picks",
            params={"incluir_alternativas": incluir_alternativas},
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
        df = pd.DataFrame(data.get("picks", []))
        df_normalized = normalize_backend_picks_df(df)
        elapsed = int((time.time() - start_time) * 1000)
        print(f"[BACKEND] picks | time={elapsed}ms | status=ok")
        return df_normalized
    except Exception as e:
        elapsed = int((time.time() - start_time) * 1000)
        print(f"[BACKEND FALLBACK] picks | time={elapsed}ms | reason={str(e)}")
        return None

def fetch_backend_metrics(incluir_alternativas: Optional[bool] = False):
    import time
    start_time = time.time()
    try:
        response = requests.get(
            f"{BACKEND_URL}/api/metrics",
            params={"incluir_alternativas": incluir_alternativas},
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
        elapsed = int((time.time() - start_time) * 1000)
        print(f"[BACKEND] metrics | time={elapsed}ms | status=ok")
        return data.get("metrics", data)
    except Exception as e:
        elapsed = int((time.time() - start_time) * 1000)
        print(f"[BACKEND FALLBACK] metrics | time={elapsed}ms | reason={str(e)}")
        return None

def normalize_backend_picks_df(df: pd.DataFrame) -> pd.DataFrame:
    required_columns = {
        "id": 0,
        "partido": "",
        "mercado": "",
        "seleccion": "",
        "cuota": 1.0,
        "confianza": 0.0,
        "resultado": "pendiente",
        "cuota_real": 1.0,
        "ganancia": 0.0,
        "ia": "",
        "tipo_pick": "principal",
        "fecha": "",
        "analisis_breve": ""
    }
    if df is None or df.empty:
        return pd.DataFrame(columns=required_columns.keys())
    for col, default in required_columns.items():
        if col not in df.columns:
            df[col] = default
    # Normalizar tipos
    df['id'] = pd.to_numeric(df['id'], errors='coerce').fillna(0).astype(int)
    df['cuota'] = pd.to_numeric(df['cuota'], errors='coerce').fillna(1.0)
    df['confianza'] = pd.to_numeric(df['confianza'], errors='coerce').fillna(0.0)
    df['cuota_real'] = pd.to_numeric(df['cuota_real'], errors='coerce').fillna(1.0)
    df['ganancia'] = pd.to_numeric(df['ganancia'], errors='coerce').fillna(0.0)
    return df

def fetch_backend_partidos_por_fecha(fecha: str):
    try:
        response = requests.get(
            f"{BACKEND_URL}/api/partidos_por_fecha",
            params={"fecha": fecha},
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("partidos", [])
    except Exception as e:
        print(f"Backend fetch failed for partidos por fecha: {e}")
        return None

def fetch_backend_api_status():
    import time
    start_time = time.time()
    try:
        response = requests.get(
            f"{BACKEND_URL}/api/api-status",
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
        configured = data.get("config", {}).get("api_football_key_configured", False)
        elapsed = int((time.time() - start_time) * 1000)
        print(f"[BACKEND] api-status | time={elapsed}ms | status=ok")
        return "Conectada" if configured else "Sin key"
    except Exception as e:
        elapsed = int((time.time() - start_time) * 1000)
        print(f"[BACKEND FALLBACK] api-status | time={elapsed}ms | reason={str(e)}")
        return None

st.set_page_config(page_title="Jr AI 11 - Plataforma de Analisis", layout="wide")

# CSS global para fondo oscuro
st.markdown("""
    <style>
    .stApp {
        background: linear-gradient(180deg, #08101d 0%, #0d1524 48%, #101722 100%);
    }
    /* Reducir brillo de elementos blancos */
    .stMarkdown, .stText, div[data-testid="stMetricValue"] {
        color: #c8d0dc !important;
    }
    h1, h2, h3 {
        color: #d8e0e8 !important;
    }
    /* Cards más oscuros */
    div[style*="background: linear-gradient"] {
        opacity: 0.95;
    }
    </style>
""", unsafe_allow_html=True)

init_db()
migrate_subscription_fields()

ADMIN_SESSION_MINUTES = 15
PUBLIC_SESSION_MINUTES = 60

# ============================================
# FUNCIONES DE FORMATO DE MONEDA
# ============================================
def formato_cop(valor):
    return f"$ {valor:,.0f}".replace(",", ".")

def formato_usd(valor):
    return f"${valor:,.2f}"

def mostrar_valor(cop, incluir_usd=True):
    if incluir_usd and MOSTRAR_USD:
        usd = cop / get_usd_to_cop()
        return f"{formato_cop(cop)} COP ({formato_usd(usd)} USD)"
    else:
        return formato_cop(cop)


def _extraer_equipos_partido(partido):
    texto = str(partido or "").strip()
    if " vs " in texto:
        local, visita = texto.split(" vs ", 1)
        return local.strip(), visita.strip()
    return "", ""


def _normalizar_mercado_ui(mercado):
    texto = str(mercado or "").strip()
    if not texto:
        return "Sin mercado"
    texto_l = texto.lower()
    if texto_l == "1x2":
        return "1X2"
    if "btts" in texto_l or "ambos anotan" in texto_l:
        return "BTTS"
    if "handicap" in texto_l or "hándicap" in texto_l:
        return "Handicap"
    if "corner" in texto_l:
        return texto.replace("Corners", "corners")
    if "tarjet" in texto_l:
        return texto.replace("Tarjetas", "tarjetas")
    return texto


def _normalizar_seleccion_ui(partido, mercado, seleccion):
    texto = str(seleccion or "").strip()
    if not texto:
        return "NO BET"
    mercado_norm = _normalizar_mercado_ui(mercado)
    local, visita = _extraer_equipos_partido(partido)
    texto_l = texto.lower()
    if mercado_norm == "1X2":
        if texto_l in {"1", "local", "home"} and local:
            return local
        if texto_l in {"2", "visitante", "away"} and visita:
            return visita
        if texto_l in {"x", "draw", "empate"}:
            return "Empate"
    if mercado_norm == "BTTS":
        if texto_l in {"si", "sí", "yes"}:
            return "Si"
        if texto_l == "no":
            return "No"
    return texto


def _auditar_pick_automatico(pick):
    alertas = []
    partido = pick.get("partido", "")
    mercado = _normalizar_mercado_ui(pick.get("mercado", ""))
    seleccion = _normalizar_seleccion_ui(partido, mercado, pick.get("seleccion", ""))
    confianza = float(pick.get("confianza", 0) or 0)
    ev = float(pick.get("ev", 0) or 0)
    cuota = float(pick.get("cuota", 0) or 0)
    sistemas = int(pick.get("sistemas_favor", 0) or 0)
    decision = str(pick.get("decision", "")).upper().strip()
    razonamiento = str(pick.get("razonamiento", "")).strip()

    if decision == "PICK":
        if cuota <= 1.01:
            alertas.append("Cuota invalida o ausente")
        if confianza < 0.65:
            alertas.append("Confianza inferior al umbral")
        if ev <= 0:
            alertas.append("EV no positivo")
        if sistemas < 5:
            alertas.append("Consenso matematico insuficiente")
        if mercado in {"Sin mercado", "NO BET"}:
            alertas.append("Mercado poco definido")
        if seleccion in {"NO BET", "", "Sin seleccion"}:
            alertas.append("Seleccion sin definir")
    if not razonamiento or razonamiento == "Sin razonamiento disponible.":
        alertas.append("Razonamiento debil o ausente")

    return {
        "partido_norm": partido,
        "mercado_norm": mercado,
        "seleccion_norm": seleccion,
        "alertas": alertas,
        "calidad": "Solido" if not alertas else ("Revisar" if len(alertas) <= 2 else "Debil"),
    }


def _estado_campo(valor, zero_is_missing=False):
    if valor is None:
        return "Pendiente"
    texto = str(valor).strip()
    if not texto:
        return "Pendiente"
    if zero_is_missing:
        try:
            if float(texto) == 0:
                return "Pendiente"
        except Exception:
            pass
    return "Completo"


def _resolver_valor(primary, fallback, zero_is_missing=False):
    if _estado_campo(primary, zero_is_missing=zero_is_missing) == "Completo":
        return primary
    return fallback


def _clean_editor_value(value, default=""):
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    texto = str(value).strip()
    return texto if texto else default


def _display_api_value(value, zero_is_missing=False):
    if _estado_campo(value, zero_is_missing=zero_is_missing) != "Completo":
        return "Sin dato"
    return value


def _prefer_prepared_value(saved_value, session_key, default=""):
    texto = str(saved_value or "").strip()
    if texto:
        return texto
    return str(st.session_state.get(session_key, default) or "")


def _collect_prepared_manual_bridge():
    saved = (
        st.session_state.get("prepared_match_manual_data")
        or st.session_state.get("prepared_match_last_manual_data")
        or {}
    )
    motivacion_local = _prefer_prepared_value(saved.get("motivacion_local"), "prep_motivacion_local")
    motivacion_visitante = _prefer_prepared_value(saved.get("motivacion_visitante"), "prep_motivacion_visitante")
    contexto_extra = _prefer_prepared_value(saved.get("contexto_extra"), "prep_contexto_extra")
    contexto_libre = "\n".join(
        [x for x in [motivacion_local, motivacion_visitante, contexto_extra] if str(x or "").strip()]
    ).strip()
    bridge = {
        **saved,
        "xg_local": _prefer_prepared_value(saved.get("xg_local"), "prep_xg_local"),
        "xg_visitante": _prefer_prepared_value(saved.get("xg_visitante"), "prep_xg_visitante"),
        "elo_local": _prefer_prepared_value(saved.get("elo_local"), "prep_elo_local"),
        "elo_visitante": _prefer_prepared_value(saved.get("elo_visitante"), "prep_elo_visitante"),
        "promedio_tarjetas_arbitro": _prefer_prepared_value(saved.get("promedio_tarjetas_arbitro"), "prep_arbitro_cards_avg"),
        "motivacion_local": motivacion_local,
        "motivacion_visitante": motivacion_visitante,
        "contexto_extra": contexto_extra,
        "contexto_perplexity": _prefer_prepared_value(saved.get("contexto_perplexity"), "prep_perplexity_resultado"),
        "contexto_libre": contexto_libre,
    }
    return bridge


def render_portal_acceso():
    if "show_public_register" not in st.session_state:
        st.session_state.show_public_register = False
    st.markdown(
        """
        <style>
        .stApp {background: linear-gradient(180deg, #08101d 0%, #0d1524 48%, #101722 100%);}
        .public-auth-shell {
            max-width: 420px;
            margin: 78px auto 0 auto;
        }
        .public-auth-wrap {
            background: linear-gradient(180deg, rgba(18,27,40,.96), rgba(12,19,31,.98));
            border: 1px solid rgba(255,255,255,.04);
            border-radius: 28px;
            padding: 30px 26px 22px 26px;
            box-shadow: 0 24px 56px rgba(0,0,0,.26);
            text-align: center;
        }
        .public-auth-mark {
            width: 58px;
            height: 58px;
            border-radius: 18px;
            margin: 0 auto 14px auto;
            background: linear-gradient(135deg, #4f8cff, #29d764);
            display:flex;
            align-items:center;
            justify-content:center;
            color:#07111d;
            font-size:20px;
            font-weight:900;
            box-shadow: 0 10px 24px rgba(41,215,100,.18);
        }
        .public-auth-chip {
            display:inline-block;
            background: rgba(255,255,255,.04);
            color:#9bb9f3;
            border:1px solid rgba(255,255,255,.05);
            border-radius:999px;
            padding:6px 10px;
            font-size:10px;
            font-weight:800;
            letter-spacing:.9px;
            text-transform:uppercase;
            margin-bottom:12px;
        }
        .access-card-title {
            color:#f7f9fb;
            font-size:32px;
            font-weight:800;
            line-height:1.04;
            margin:0;
        }
        .access-card-text {
            color:#92a4bb;
            font-size:13px;
            line-height:1.55;
            margin:10px auto 0 auto;
            max-width: 300px;
        }
        .access-form-card {
            margin-top:18px;
        }
        .access-caption {
            color:#7f95ad;
            font-size:12px;
            margin-top:12px;
            text-align:center;
        }
        .public-auth-shell div[data-testid="stTextInput"] input {
            background: rgba(255,255,255,.04) !important;
            border: 1px solid rgba(255,255,255,.06) !important;
            border-radius: 16px !important;
            color: #f7f9fb !important;
            min-height: 52px !important;
            padding-left: 14px !important;
        }
        .public-auth-shell div[data-testid="stTextInput"] input::placeholder {
            color: #73859b !important;
        }
        .public-auth-shell div[data-testid="stButton"] > button {
            border-radius: 16px !important;
            min-height: 50px !important;
            font-weight: 700 !important;
            border: 1px solid rgba(255,255,255,.06) !important;
            box-shadow: none !important;
        }
        .public-auth-shell div[data-testid="stButton"] > button[kind="primary"] {
            background: linear-gradient(135deg, #4f8cff, #29d764) !important;
            color: #07111d !important;
            border: none !important;
        }
        </style>
        <div class="public-auth-shell">
            <div class="public-auth-wrap">
                <div class="public-auth-mark">JR</div>
                <div class="public-auth-chip">Jr AI 11 | Acceso</div>
                <div class="access-card-title">Inicia sesion</div>
                <div class="access-card-text">Accede a tu panel privado con una sola cuenta.</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _, form_col, _ = st.columns([1.2, 2.2, 1.2])
    with form_col:
        st.markdown("<div class='access-form-card'>", unsafe_allow_html=True)
        login_user = st.text_input("Usuario o email", key="unified_login_user", placeholder="Tu usuario o email", label_visibility="collapsed")
        login_pass = st.text_input("Clave", type="password", key="unified_login_pass", placeholder="Tu clave", label_visibility="collapsed")
        if st.button("Entrar", key="unified_login_btn", use_container_width=True, type="primary"):
            with st.spinner("Autenticando..."):
                user = authenticate_user(login_user, login_pass)
                if user:
                    _set_login_session(user)
                    st.success(f"Acceso concedido. Bienvenido, {user.get('display_name', user.get('username'))}.")
                    st.rerun()
                else:
                    st.error("Credenciales invalidas o usuario inactivo. Revisa tus datos e intenta de nuevo.")

        st.markdown("<div class='access-caption'>¿No tienes cuenta?</div>", unsafe_allow_html=True)
        cta_label = "Ocultar registro" if st.session_state.show_public_register else "Crear cuenta nueva"
        if st.button(cta_label, key="toggle_public_register", use_container_width=True):
            st.session_state.show_public_register = not st.session_state.show_public_register
            st.rerun()

        if st.session_state.show_public_register:
            st.markdown("<div style='margin-top:14px;'></div>", unsafe_allow_html=True)
            reg_user = st.text_input("Nuevo usuario", key="public_reg_user", placeholder="Usuario", label_visibility="collapsed")
            reg_name = st.text_input("Nombre visible", key="public_reg_name", placeholder="Nombre visible", label_visibility="collapsed")
            reg_email = st.text_input("Email", key="public_reg_email", placeholder="Email", label_visibility="collapsed")
            reg_pass = st.text_input("Clave nueva", type="password", key="public_reg_pass", placeholder="Clave nueva", label_visibility="collapsed")
            if st.button("Crear cuenta", key="public_register_btn", use_container_width=True):
                ok, mensaje = create_user(reg_user, reg_name, reg_pass, reg_email, role="user")
                if ok:
                    st.session_state.show_public_register = False
                    st.session_state.public_reg_user = ""
                    st.session_state.public_reg_name = ""
                    st.session_state.public_reg_email = ""
                    st.session_state.public_reg_pass = ""
                    st.success(mensaje)
                    st.rerun()
                else:
                    st.error(mensaje)
        st.markdown("</div>", unsafe_allow_html=True)


def _copy_pick_social(pick, resumen_pick, confianza_pct, cuota_pick):
    partido = str(pick.get("partido", "")).strip()
    mercado = str(pick.get("mercado", "")).strip()
    seleccion = str(pick.get("seleccion", "")).strip()
    return (
        f"Jr AI 11 | PICK OFICIAL\n\n"
        f"{partido}\n"
        f"{mercado}: {seleccion}\n"
        f"Cuota publicada: {cuota_pick:.2f}\n"
        f"Confianza declarada: {confianza_pct}%\n\n"
        f"Lectura clave: {resumen_pick}\n\n"
        f"Verifica cuota final antes de entrar.\n"
        f"#JrAI11 #PickOficial #ApuestasDeportivas"
    )


def _copy_resultado_social(pick, etiqueta_estado, cuota_pub, ganancia_pub):
    partido = str(pick.get("partido", "")).strip()
    mercado = str(pick.get("mercado", "")).strip()
    seleccion = str(pick.get("seleccion", "")).strip()
    return (
        f"Jr AI 11 | {etiqueta_estado}\n\n"
        f"{partido}\n"
        f"{mercado}: {seleccion}\n"
        f"Cuota publicada: {cuota_pub:.2f}\n"
        f"Ganancia registrada: {ganancia_pub:.2f}\n\n"
        f"Seguimiento real del sistema.\n"
        f"#JrAI11 #ResultadoPick #ApuestasDeportivas"
    )


def _config_bool(key, default=False):
    raw = get_config_value(key, "1" if default else "0")
    return str(raw).strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


def _enviar_pick_telegram_si_activo(pick):
    from services.telegram_service import telegram_config_ok
    if not telegram_config_ok() or not _config_bool("auto_publicar_pick_telegram", False):
        return None
    try:
        confianza = int(float(pick.get("confianza", 0) or 0) * 100)
        cuota = float(pick.get("cuota", 0) or 0)
        resumen = str(pick.get("analisis_breve", "") or "").strip()
        resumen = resumen[:220] + ("..." if len(resumen) > 220 else "")
        copy_social = _copy_pick_social(pick, resumen, confianza, cuota)
        from pdf_generator import generar_pdf_pick_social
        from services.telegram_service import enviar_paquete_telegram
        pdf_social = generar_pdf_pick_social(pick)
        return enviar_paquete_telegram(
            copy_social,
            pdf_social,
            f"pick_social_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            caption=f"Pick oficial | {pick.get('partido', '')}",
        )
    except Exception as e:
        return False, f"Auto-publicacion de pick fallo: {e}"


def _enviar_resultado_telegram_si_activo(pick):
    from services.telegram_service import telegram_config_ok
    if not telegram_config_ok() or not _config_bool("auto_publicar_resultado_telegram", False):
        return None
    try:
        estado = str(pick.get("resultado", "")).strip().lower()
        etiqueta = "WIN"
        if estado == "perdida":
            etiqueta = "LOSS"
        elif estado == "media":
            etiqueta = "PUSH"
        cuota_pub = float(pick.get("cuota", 0) or 0)
        ganancia_pub = float(pick.get("ganancia", 0) or 0)
        copy_social = _copy_resultado_social(pick, etiqueta, cuota_pub, ganancia_pub)
        from pdf_generator import generar_pdf_resultado_social
        from services.telegram_service import enviar_paquete_telegram
        pdf_social = generar_pdf_resultado_social(pick)
        return enviar_paquete_telegram(
            copy_social,
            pdf_social,
            f"resultado_social_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            caption=f"Resultado | {pick.get('partido', '')}",
        )
    except Exception as e:
        return False, f"Auto-publicacion de resultado fallo: {e}"


def render_vista_publica():
    usuario_publico = st.session_state.get("public_user")
    if usuario_publico and _session_expired(st.session_state.get("public_last_seen"), PUBLIC_SESSION_MINUTES):
        _clear_public_session()
        usuario_publico = None
    public_logged = bool(usuario_publico)

    if not public_logged:
        render_portal_acceso()
        return

    st.session_state.public_last_seen = datetime.now().isoformat()
    
    # Obtener información de suscripción
    subscription_info = get_user_subscription(usuario_publico.get("id")) if usuario_publico else None
    user_plan = subscription_info.get("plan", "free") if subscription_info else "free"
    is_premium = user_plan in ("premium", "vip")
    is_vip = user_plan == "vip"
    
    # Banner de upgrade para usuarios free
    if not is_premium:
        st.markdown(
            """
            <div style="background: linear-gradient(135deg, rgba(214,170,76,0.15), rgba(255,145,77,0.1)); border: 1px solid rgba(214,170,76,0.3); border-radius: 20px; padding: 20px; margin-bottom: 20px; text-align: center;">
                <div style="color: #f7f9fb; font-size: 20px; font-weight: 800;">🔒 Actualiza a Premium</div>
                <div style="color: #9fb0c5; font-size: 14px; margin-top: 8px;">Obtén acceso completo a análisis detallados, historial ilimitado y alertas instantáneas.</div>
                <div style="margin-top: 14px;">
                    <span style="background: linear-gradient(135deg, #d6aa4c, #ff9150); color: #07111d; padding: 12px 24px; border-radius: 12px; font-weight: 800; font-size: 14px;">$19.99/mes</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        """
        <style>
        .stApp {background: linear-gradient(180deg, #08101d 0%, #0d1524 48%, #101722 100%);}
        .public-hero {
            background: radial-gradient(circle at top right, rgba(41,215,100,.16), transparent 34%), linear-gradient(135deg, #0c1220, #131b2a 68%, #162234);
            border: 1px solid rgba(255,255,255,.06);
            border-radius: 28px;
            padding: 24px 24px 20px 24px;
            box-shadow: 0 18px 44px rgba(0,0,0,.28);
            margin-bottom: 18px;
        }
        .public-kpis {
            display:grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 12px;
            margin: 14px 0 10px 0;
        }
        .public-kpi {
            background: rgba(255,255,255,.04);
            border: 1px solid rgba(255,255,255,.06);
            border-radius: 18px;
            padding: 14px 16px;
        }
        .public-kpi-label {
            color: #8fa1b9;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
            font-weight: 700;
        }
        .public-kpi-value {
            color: #f7f9fb;
            font-size: 28px;
            font-weight: 800;
            margin-top: 4px;
        }
        .public-chips {
            display:flex;
            flex-wrap:wrap;
            gap:10px;
            margin-top: 14px;
        }
        .public-chip {
            background:#151f30;
            color:#d7e0ea;
            border:1px solid rgba(255,255,255,.08);
            padding:10px 14px;
            border-radius:999px;
            font-size:13px;
            font-weight:700;
        }
        .public-chip-muted {
            opacity:.92;
        }
        .member-bar {
            display:flex;
            justify-content:space-between;
            align-items:center;
            gap:16px;
            flex-wrap:wrap;
            background: rgba(255,255,255,.03);
            border:1px solid rgba(255,255,255,.06);
            border-radius: 20px;
            padding: 14px 16px;
            margin: 14px 0 18px 0;
        }
        .member-name {
            color:#f7f9fb;
            font-size:18px;
            font-weight:800;
        }
        .member-sub {
            color:#91a5bb;
            font-size:13px;
            margin-top:2px;
        }
        .member-badge {
            background: linear-gradient(135deg, rgba(41,215,100,.18), rgba(214,170,76,.18));
            color:#e8f1f8;
            border:1px solid rgba(255,255,255,.08);
            padding:10px 14px;
            border-radius:999px;
            font-size:12px;
            font-weight:800;
            letter-spacing:.8px;
            text-transform:uppercase;
        }
        .member-nav {
            display:grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap:12px;
            margin: 6px 0 18px 0;
        }
        .member-nav-item {
            background: rgba(255,255,255,.03);
            border:1px solid rgba(255,255,255,.06);
            border-radius:18px;
            padding:14px 16px;
            color:#dce6ef;
            font-size:14px;
            font-weight:800;
            text-align:center;
        }
        .member-nav-item.active {
            background: linear-gradient(135deg, rgba(41,215,100,.16), rgba(214,170,76,.16));
            color:#f7fbff;
        }
        @media (max-width: 900px) {
            .public-hero {
                padding: 18px 16px 16px 16px;
                border-radius: 22px;
            }
            .public-kpis {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
            .member-bar {
                padding: 12px 14px;
                border-radius: 18px;
            }
            .member-nav {
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 10px;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    public_picks_backend_error = False
    df_publico = fetch_backend_picks(incluir_alternativas=True)
    if df_publico is None:
        print("[BACKEND ERROR] picks | public_view | no fallback")
        public_picks_backend_error = True
        df_publico = pd.DataFrame()
    public_backend_error = False
    metrics = fetch_backend_metrics(incluir_alternativas=False)
    if metrics is None:
        print("[BACKEND ERROR] metrics | public_view | no fallback")
        public_backend_error = True
        metrics = {}
    total_picks = metrics.get("total_picks", 0)
    acierto = (metrics.get("ganadas", 0) + metrics.get("medias", 0) / 2) / max(1, total_picks) * 100
    roi = metrics.get("roi_global", 0)
    yield_global = metrics.get("yield_global", 0)
    if public_backend_error:
        st.warning("⚠️ Datos no disponibles en este momento")
    total_picks_display = "N/A" if public_backend_error else total_picks
    acierto_display = "N/A" if public_backend_error else f"{acierto:.1f}%"
    roi_display = "N/A" if public_backend_error else f"{roi}%"
    yield_display = "N/A" if public_backend_error else f"{yield_global}%"

    pendientes = df_publico[
        (df_publico["tipo_pick"] == "principal")
        & (df_publico["resultado"] == "pendiente")
    ].copy() if not df_publico.empty else pd.DataFrame()
    cerrados = df_publico[
        (df_publico["tipo_pick"] == "principal")
        & (df_publico["resultado"].isin(["ganada", "perdida", "media"]))
    ].copy() if not df_publico.empty else pd.DataFrame()
    if public_picks_backend_error:
        st.warning("⚠️ Picks no disponibles en este momento")
    pendientes_count = "N/A" if public_picks_backend_error else len(pendientes)
    cerrados_count = "N/A" if public_picks_backend_error else len(cerrados)

    st.markdown(
        f"""
        <div class="public-hero">
            <div style="display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap;">
                <div>
                    <div style="color:#29d764; font-size:12px; font-weight:800; letter-spacing:1.4px; text-transform:uppercase;">Jr AI 11 | Zona de miembros</div>
                    <div style="color:#f7f9fb; font-size:34px; font-weight:900; line-height:1.08; margin-top:6px;">Tus picks oficiales, resultados y evolucion del sistema</div>
                    <div style="color:#9fb0c5; font-size:16px; margin-top:10px;">Panel privado para seguir picks activos, revisar cierres y consultar el historico del servicio.</div>
                </div>
                <div style="background:linear-gradient(135deg, #29d764, #d6aa4c); color:#07111d; padding:16px 20px; border-radius:22px; font-weight:900; font-size:18px;">MIEMBRO ACTIVO</div>
            </div>
            <div class="public-kpis">
                <div class="public-kpi"><div class="public-kpi-label">Picks</div><div class="public-kpi-value">{total_picks_display}</div></div>
                <div class="public-kpi"><div class="public-kpi-label">Win Rate</div><div class="public-kpi-value">{acierto_display}</div></div>
                <div class="public-kpi"><div class="public-kpi-label">ROI</div><div class="public-kpi-value">{roi_display}</div></div>
                <div class="public-kpi"><div class="public-kpi-label">Pendientes</div><div class="public-kpi-value">{pendientes_count}</div></div>
            </div>
            <div class="public-chips">
                <div class="public-chip public-chip-muted">Picks oficiales</div>
                <div class="public-chip public-chip-muted">Resultados</div>
                <div class="public-chip public-chip-muted">Historico</div>
                <div class="public-chip public-chip-muted">Yield: {yield_display}</div>
                <div class="public-chip public-chip-muted">{"Miembro activo" if public_logged else "Acceso restringido"}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="member-bar">
            <div>
                <div class="member-name">{usuario_publico.get('display_name', usuario_publico.get('username', 'usuario'))}</div>
                <div class="member-sub">Acceso habilitado a feed privado, resultados y seguimiento historico.</div>
            </div>
            <div class="member-badge">Cuenta miembro activa</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if "member_section_nav" not in st.session_state:
        st.session_state.member_section_nav = "Feed"
    member_section = st.session_state.member_section_nav

    def _member_nav_class(nombre):
        return "member-nav-item active" if member_section == nombre else "member-nav-item"

    st.markdown(
        f"""
        <div class="member-nav">
            <div class="{_member_nav_class('Feed')}">Feed</div>
            <div class="{_member_nav_class('Pendientes')}">Pendientes</div>
            <div class="{_member_nav_class('Resultados')}">Resultados</div>
            <div class="{_member_nav_class('Historico')}">Historico</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_pub_u1, col_pub_u2 = st.columns([3, 1])
    col_pub_u1.caption("Tu cuenta ya esta dentro del panel privado.")
    if col_pub_u2.button("Cerrar sesion publica"):
        _clear_public_session()
        st.rerun()
    with st.expander("Mi perfil"):
        with st.form("public_profile_form"):
            perfil_nombre = st.text_input("Nombre visible", value=usuario_publico.get("display_name", ""))
            perfil_email = st.text_input("Email", value=usuario_publico.get("email", "") or "")
            guardar_perfil = st.form_submit_button("Guardar perfil")
        if guardar_perfil:
            ok, mensaje = update_user_profile(usuario_publico["id"], perfil_nombre, perfil_email)
            if ok:
                # Actualizar directamente el usuario en sesión
                st.session_state.public_user["display_name"] = perfil_nombre
                st.session_state.public_user["email"] = perfil_email
                st.success(mensaje)
                st.rerun()
            else:
                st.error(mensaje)

        with st.form("public_password_form"):
            clave_actual = st.text_input("Clave actual", type="password", key="public_current_password")
            clave_nueva = st.text_input("Clave nueva", type="password", key="public_new_password")
            cambiar_clave = st.form_submit_button("Cambiar clave")
        if cambiar_clave:
            ok, mensaje = update_user_password(usuario_publico["id"], clave_actual, clave_nueva)
            if ok:
                st.success(mensaje + " Por seguridad, vuelve a iniciar sesión.")
                # Cerrar sesión para forzar re-login con nueva contraseña
                _clear_public_session()
                st.rerun()
            else:
                st.error(mensaje)

    st.caption("Secciones del panel privado")
    nav_cols = st.columns(4)
    if nav_cols[0].button("Feed", use_container_width=True, type="primary" if st.session_state.member_section_nav == "Feed" else "secondary", key="member_nav_feed"):
        st.session_state.member_section_nav = "Feed"
        st.rerun()
    if nav_cols[1].button("Pendientes", use_container_width=True, type="primary" if st.session_state.member_section_nav == "Pendientes" else "secondary", key="member_nav_pending"):
        st.session_state.member_section_nav = "Pendientes"
        st.rerun()
    if nav_cols[2].button("Resultados", use_container_width=True, type="primary" if st.session_state.member_section_nav == "Resultados" else "secondary", key="member_nav_results"):
        st.session_state.member_section_nav = "Resultados"
        st.rerun()
    if nav_cols[3].button("Historico", use_container_width=True, type="primary" if st.session_state.member_section_nav == "Historico" else "secondary", key="member_nav_history"):
        st.session_state.member_section_nav = "Historico"
        st.rerun()
    member_section = st.session_state.member_section_nav

    if member_section == "Feed":
        _render_section_banner(
            "Feed privado",
            "Aqui ves los picks activos y los cierres mas recientes con formato tipo publicacion.",
            "Actividad",
        )
        if pendientes.empty and cerrados.empty:
            st.info("Todavia no hay actividad publicada.")
        else:
            if not pendientes.empty:
                st.markdown("### Picks activos")
                # Límites según plan de suscripción
                if is_vip:
                    limite_pendientes = 20
                elif is_premium:
                    limite_pendientes = 10
                else:
                    limite_pendientes = 3  # Free solo ve 3 picks
                
                # Limitar contenido para usuarios free (solo mostrar sin análisis detallado)
                mostrar_solo_seleccion = not is_premium
                
                for _, row in pendientes.head(limite_pendientes).iterrows():
                    cuota = float(row.get("cuota", 0) or 0)
                    confianza = int(float(row.get("confianza", 0) or 0) * 100)
                    
                    if mostrar_solo_seleccion:
                        # Vista limitada para usuarios free
                        cuerpo = (
                            f"{row.get('mercado', '')}: {row.get('seleccion', '')}\n"
                            f"Cuota: {cuota:.2f}"
                        )
                    else:
                        # Vista completa para premium
                        cuerpo = (
                            f"{row.get('mercado', '')}: {row.get('seleccion', '')}\n"
                            f"Cuota: {cuota:.2f}\n"
                            f"Confianza: {confianza}% | Fuente: {row.get('ia', '')}\n\n"
                            f"{str(row.get('analisis_breve', '') or '')[:150]}"
                        )
                    
                    _render_public_card(
                        str(row.get("partido", "Partido")),
                        cuerpo,
                        "Pick oficial",
                        meta_left=f"{_market_icon(row.get('mercado', ''))} | Cuota {cuota:.2f}",
                        meta_right=f"Confianza {confianza}%" if not mostrar_solo_seleccion else "Ver detalles en Premium",
                        footer_hint=str(row.get("ia", "Analista")) if not mostrar_solo_seleccion else "Actualiza a Premium",
                    )
                    if is_premium:
                        _render_pick_detail(row, "feed")
                
                if not is_premium and len(pendientes) > limite_pendientes:
                    st.info("🔒 Actualiza a Premium para ver todos los picks pendientes.")
            if not cerrados.empty:
                st.markdown("### Ultimos cierres")
                # Límites según plan
                if is_vip:
                    limite_cerrados = 15
                elif is_premium:
                    limite_cerrados = 8
                else:
                    limite_cerrados = 3  # Free solo ve 3 resultados
                    
                mostrar_solo_resultado = not is_premium
                
                for _, row in cerrados.head(limite_cerrados).iterrows():
                    estado = str(row.get("resultado", "")).strip().lower()
                    etiqueta = "WIN"
                    tono = "win"
                    if estado == "perdida":
                        etiqueta = "LOSS"
                        tono = "loss"
                    elif estado == "media":
                        etiqueta = "PUSH"
                        tono = "push"
                    
                    if mostrar_solo_resultado:
                        cuerpo = (
                            f"{row.get('mercado', '')}: {row.get('seleccion', '')}\n"
                            f"Resultado: {etiqueta}"
                        )
                        footer = "Ver más en Premium"
                    else:
                        cuerpo = (
                            f"{row.get('mercado', '')}: {row.get('seleccion', '')}\n"
                            f"Cuota: {float(row.get('cuota', 0) or 0):.2f}\n"
                            f"Ganancia: {float(row.get('ganancia', 0) or 0):.2f}"
                        )
                        footer = str(row.get("ia", "Analista"))
                    
                    _render_public_card(
                        str(row.get("partido", "Partido")),
                        cuerpo,
                        etiqueta,
                        tono,
                        meta_left=f"{_market_icon(row.get('mercado', ''))} | {etiqueta}",
                        meta_right=f"Ganancia {float(row.get('ganancia', 0) or 0):.2f}" if not mostrar_solo_resultado else f"Ver detalles en Premium",
                        footer_hint=footer,
                    )
                    if is_premium:
                        _render_pick_detail(row, "feed")
                if not is_premium and len(cerrados) > limite_cerrados:
                    st.info("🔒 Actualiza a Premium para ver el historial completo de resultados.")

    elif member_section == "Pendientes":
        _render_section_banner(
            "Picks pendientes",
            "Filtra los picks activos por mercado y revisa el detalle completo antes del cierre.",
            "Pendientes",
        )
        if not is_premium:
            st.warning("🔒 Esta sección es solo para miembros Premium.")
            st.markdown("""
            **Beneficios Premium:**
            - Ver todos los picks pendientes
            - Filtrar por mercado
            - Análisis completo de cada pick
            - Historial ilimitado
            
            [Actualiza a Premium por $19.99/mes]
            """)
        elif pendientes.empty:
            st.info("No hay picks principales pendientes en este momento.")
        else:
            pendientes_view = pendientes.copy()
            mercados_opts = ["Todos"] + sorted(
                pendientes_view["mercado"].fillna("Sin mercado").astype(str).unique().tolist()
            )
            mercado_pend = st.selectbox("Filtrar pendientes por mercado", mercados_opts, key="member_filter_pend")
            if mercado_pend != "Todos":
                pendientes_view = pendientes_view[
                    pendientes_view["mercado"].fillna("Sin mercado").astype(str) == mercado_pend
                ]
            mercados_top = pendientes["mercado"].fillna("Sin mercado").astype(str).value_counts().head(4).index.tolist()
            st.markdown(
                "<div class='public-chips'>" + "".join([f"<div class='public-chip'>{m}</div>" for m in mercados_top]) + "</div>",
                unsafe_allow_html=True,
            )
            col_pen_a, col_pen_b, col_pen_c = st.columns(3)
            col_pen_a.metric("Activos", len(pendientes_view))
            col_pen_b.metric("Mercados", pendientes_view["mercado"].nunique())
            conf_media_pen = pendientes_view["confianza"].fillna(0).astype(float).mean() * 100 if not pendientes_view.empty else 0
            col_pen_c.metric("Confianza media", f"{conf_media_pen:.0f}%")
            for _, row in pendientes_view.head(12).iterrows():
                cuota = float(row.get("cuota", 0) or 0)
                confianza = int(float(row.get("confianza", 0) or 0) * 100)
                etiqueta = "Alta confianza" if confianza >= 75 else ("Valor medio" if confianza >= 65 else "En revision")
                cuerpo = (
                    f"{row.get('mercado', '')}: {row.get('seleccion', '')}\n"
                    f"Cuota: {cuota:.2f} | Confianza: {confianza}%\n"
                    f"Fuente: {row.get('ia', '')}\n\n"
                    f"{str(row.get('analisis_breve', '') or '')[:180]}"
                )
                _render_public_card(
                    str(row.get("partido", "Partido")),
                    cuerpo,
                    etiqueta,
                    meta_left=f"{_market_icon(row.get('mercado', ''))} | {row.get('mercado', '')}",
                    meta_right=f"Cuota {cuota:.2f}",
                    footer_hint="Pendiente",
                )
                _render_pick_detail(row, "pendientes")

    elif member_section == "Resultados":
        _render_section_banner(
            "Resultados cerrados",
            "Consulta cierres recientes y filtra por estado para revisar la trazabilidad del sistema.",
            "Cierres",
        )
        if not is_premium:
            st.warning("🔒 Esta sección es solo para miembros Premium.")
            st.markdown("""
            **Beneficios Premium:**
            - Ver todos los resultados cerrados
            - Filtrar por estado (ganada/perdida/media)
            - Análisis completo de cada cierre
            - Estadísticas detalladas
            
            [Actualiza a Premium por $19.99/mes]
            """)
        elif cerrados.empty:
            st.info("No hay picks cerrados todavia.")
        else:
            cerrados_view = cerrados.copy()
            estado_map = {"Todos": None, "Ganadas": "ganada", "Perdidas": "perdida", "Medias": "media"}
            estado_sel = st.selectbox("Filtrar resultados", list(estado_map.keys()), key="member_filter_results")
            if estado_map[estado_sel]:
                cerrados_view = cerrados_view[cerrados_view["resultado"] == estado_map[estado_sel]]
            col_res1, col_res2, col_res3 = st.columns(3)
            col_res1.metric("Ganadas", int((cerrados_view["resultado"] == "ganada").sum()))
            col_res2.metric("Perdidas", int((cerrados_view["resultado"] == "perdida").sum()))
            col_res3.metric("Medias", int((cerrados_view["resultado"] == "media").sum()))
            for _, row in cerrados_view.head(20).iterrows():
                estado = str(row.get("resultado", "")).strip().lower()
                etiqueta = "WIN"
                tono = "win"
                if estado == "perdida":
                    etiqueta = "LOSS"
                    tono = "loss"
                elif estado == "media":
                    etiqueta = "PUSH"
                    tono = "push"
                cuerpo = (
                    f"{row.get('mercado', '')}: {row.get('seleccion', '')}\n"
                    f"Cuota: {float(row.get('cuota', 0) or 0):.2f} | Ganancia: {float(row.get('ganancia', 0) or 0):.2f}\n"
                    f"Fuente: {row.get('ia', '')}"
                )
                _render_public_card(
                    str(row.get("partido", "Partido")),
                    cuerpo,
                    etiqueta,
                    tono,
                    meta_left=f"{_market_icon(row.get('mercado', ''))} | {row.get('mercado', '')}",
                    meta_right=f"Cuota {float(row.get('cuota', 0) or 0):.2f}",
                    footer_hint=str(row.get("ia", "Analista")),
                )
                _render_pick_detail(row, "resultados")

    elif member_section == "Historico":
        _render_section_banner(
            "Historico del sistema",
            "Sigue la evolucion total del servicio por periodo, junto con metricas de riesgo y rendimiento.",
            "Evolucion",
        )
        if not is_premium:
            st.warning("🔒 Esta sección es solo para miembros Premium.")
            st.markdown("""
            **Beneficios Premium:**
            - Ver el histórico completo del sistema
            - Métricas de riesgo (Sharpe, Drawdown)
            - Evolución por día/mes/año
            - Estadísticas por IA
            - Comparativas
            
            [Actualiza a Premium por $19.99/mes]
            """)
        else:
            col_h1, col_h2, col_h3, col_h4 = st.columns(4)
            col_h1.metric("Picks", total_picks)
            col_h2.metric("Win Rate", f"{acierto:.1f}%")
            col_h3.metric("ROI", f"{roi}%")
            col_h4.metric("Yield", f"{yield_global}%")

            riesgo = metrics.get("metricas_riesgo", {})
            if riesgo:
                col_h5, col_h6, col_h7 = st.columns(3)
                col_h5.metric("Sharpe", riesgo.get("sharpe_ratio", 0))
                col_h6.metric("Drawdown", f"{riesgo.get('max_drawdown', 0)}%")
                col_h7.metric("Profit Factor", riesgo.get("profit_factor", 0))

            evolucion = metrics.get("evolucion", pd.DataFrame())
            if not evolucion.empty:
                periodo = st.selectbox("Agrupar evolucion por", ["Dia", "Mes", "Ano"], key="public_periodo")
                evolucion_plot = evolucion.copy()
                evolucion_plot["fecha"] = pd.to_datetime(evolucion_plot["fecha"])
                if periodo == "Dia":
                    evolucion_plot["periodo"] = evolucion_plot["fecha"].dt.strftime("%Y-%m-%d")
                elif periodo == "Mes":
                    evolucion_plot["periodo"] = evolucion_plot["fecha"].dt.to_period("M").astype(str)
                else:
                    evolucion_plot["periodo"] = evolucion_plot["fecha"].dt.to_period("Y").astype(str)
                evolucion_plot = evolucion_plot.sort_values("fecha").groupby("periodo", as_index=False)["bankroll"].last()
                fig_public = px.line(
                    evolucion_plot,
                    x="periodo",
                    y="bankroll",
                    title=f"Evolucion del sistema por {periodo.lower()}",
                    markers=True,
                )
                fig_public.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(15,22,34,0.85)",
                    font_color="#f5f7fa",
                )
                st.plotly_chart(fig_public, width="stretch")

            if not cerrados.empty:
                st.markdown("### Historico operativo")
                columnas = [c for c in ["fecha", "partido", "mercado", "seleccion", "cuota", "resultado", "ganancia"] if c in cerrados.columns]
                st.dataframe(cerrados[columnas].astype(str), width="stretch")

# ============================================
# ACCESO Y RUTEO POR ROL
# ============================================
if "admin_user" not in st.session_state:
    st.session_state.admin_user = None
if "public_user" not in st.session_state:
    st.session_state.public_user = None

df_usuarios = get_all_users()
hay_admin = not df_usuarios.empty and "role" in df_usuarios.columns and (df_usuarios["role"] == "admin").any()

if not hay_admin:
    st.markdown(
        """
        <div style="max-width:860px; margin:44px auto 0 auto; background:radial-gradient(circle at top right, rgba(214,170,76,.12), transparent 34%), linear-gradient(135deg, #0b1220, #121a29 68%, #172437); border:1px solid rgba(255,255,255,.06); border-radius:34px; padding:40px 40px 32px 40px; box-shadow:0 24px 60px rgba(0,0,0,.32);">
            <div style="display:inline-block; background:rgba(214,170,76,.12); color:#e7bb58; border:1px solid rgba(214,170,76,.20); border-radius:999px; padding:8px 14px; font-size:12px; font-weight:800; letter-spacing:1px; text-transform:uppercase; margin-bottom:14px;">Admin inicial</div>
            <div style="color:#f7f9fb; font-size:40px; font-weight:900; line-height:1.04;">Crea la primera cuenta administradora</div>
            <div style="color:#9fb0c5; font-size:17px; margin-top:12px; line-height:1.55;">Todavia no existe un usuario admin. Crea la cuenta inicial para habilitar el panel operativo.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    col_pad1, col_boot, col_pad2 = st.columns([1, 1.15, 1])
    with col_boot:
        st.markdown("⚠️ **Solo el primer admin puede crearse con token de seguridad**")
        with st.form("bootstrap_admin_form"):
            boot_token = st.text_input("Token de bootstrap", type="password", placeholder="Ingresa el token de seguridad")
            boot_user = st.text_input("Usuario admin")
            boot_name = st.text_input("Nombre visible")
            boot_email = st.text_input("Email admin")
            boot_pass = st.text_input("Clave admin", type="password")
            crear_bootstrap = st.form_submit_button("Crear admin inicial", use_container_width=True)
        if crear_bootstrap:
            import hmac
            with st.spinner("Creando cuenta inicial..."):
                if not boot_token or not hmac.compare_digest(str(boot_token), str(BOOTSTRAP_TOKEN)):
                    st.error("Token de bootstrap incorrecto. Revisa el valor en config.py o consulta con soporte.")
                elif not boot_user or not boot_pass:
                    st.error("Usuario y clave son campos obligatorios.")
                elif len(boot_pass) < 8:
                    st.error("La clave del administrador debe tener al menos 8 caracteres por seguridad.")
                else:
                    ok, mensaje = create_user(boot_user, boot_name, boot_pass, boot_email, role="admin", must_change_password=True)
                    if ok:
                        st.success("✓ Admin inicial creado correctamente. Ya puedes iniciar sesion con tus nuevas credenciales.")
                        st.info("Nota: Se te pedira cambiar la clave temporal en el primer acceso.")
                        st.rerun()
                    else:
                        st.error(f"Error al crear admin: {mensaje}")
    st.stop()

if st.session_state.get("admin_user") and _session_expired(st.session_state.get("admin_last_seen"), ADMIN_SESSION_MINUTES):
    _clear_admin_session()

if st.session_state.get("public_user") and _session_expired(st.session_state.get("public_last_seen"), PUBLIC_SESSION_MINUTES):
    _clear_public_session()

if st.session_state.get("admin_user"):
    match_admin = df_usuarios[df_usuarios["id"] == st.session_state["admin_user"].get("id")]
    if match_admin.empty or not bool(match_admin.iloc[0].get("active", 0)) or str(match_admin.iloc[0].get("role", "")).strip().lower() != "admin":
        _clear_admin_session()

if st.session_state.get("public_user"):
    match_public = df_usuarios[df_usuarios["id"] == st.session_state["public_user"].get("id")]
    if match_public.empty or not bool(match_public.iloc[0].get("active", 0)) or str(match_public.iloc[0].get("role", "")).strip().lower() != "user":
        _clear_public_session()

if st.session_state.get("admin_user") and st.session_state.get("public_user"):
    _clear_public_session()

if not st.session_state.get("admin_user") and not st.session_state.get("public_user"):
    render_portal_acceso()
    st.stop()

panel_activo = "Admin" if st.session_state.get("admin_user") else "Miembro"

if st.session_state.get("admin_user") and st.session_state.admin_user.get("must_change_password"):
    st.title("Jr AI 11 | Cambio obligatorio de clave")
    st.caption("Por seguridad, cambia la clave temporal del admin antes de seguir.")
    
    # Para cambio obligatorio, pedimos la clave actual (o se puede omitir si es temporal)
    clave_actual = st.text_input("Clave actual (deja vacio si es temporal)", type="password", key="admin_current_password_force")
    nueva_admin_pass = st.text_input("Nueva clave admin", type="password", key="admin_force_new_password")
    confirmar_admin_pass = st.text_input("Confirma la nueva clave", type="password", key="admin_force_confirm_password")
    
    if st.button("Actualizar clave admin"):
        if not nueva_admin_pass or len(nueva_admin_pass) < 8:
            st.error("La nueva clave debe tener al menos 8 caracteres.")
        elif nueva_admin_pass != confirmar_admin_pass:
            st.error("La confirmacion no coincide.")
        else:
            # Verificar si es la primera vez (password temporal) - permitir cambio sin verificación
            if st.session_state.admin_user.get("must_change_password"):
                # Cambio forzado - actualizar directamente
                from database import _hash_password
                from database import get_conn
                try:
                    with get_conn() as conn:
                        conn.execute(
                            "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
                            (_hash_password(nueva_admin_pass), st.session_state.admin_user["id"]),
                        )
                    # Re-autenticar
                    user = authenticate_user(
                        st.session_state.admin_user.get("username", ""),
                        nueva_admin_pass,
                    )
                    if user:
                        st.session_state.admin_user = user
                    st.session_state.admin_last_seen = datetime.now().isoformat()
                    st.success("Clave admin actualizada. Ya puedes entrar al panel.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al actualizar: {e}")
            else:
                # Cambio normal con verificación
                ok, mensaje = update_user_password(
                    st.session_state.admin_user["id"],
                    clave_actual,
                    nueva_admin_pass,
                )
                if ok:
                    user = authenticate_user(
                        st.session_state.admin_user.get("username", ""),
                        nueva_admin_pass,
                    )
                    if user:
                        st.session_state.admin_user = user
                    st.session_state.admin_last_seen = datetime.now().isoformat()
                    st.success("Clave admin actualizada. Ya puedes entrar al panel.")
                    st.rerun()
                else:
                    st.error(mensaje)
    st.stop()

if st.session_state.get("public_user") and not st.session_state.get("admin_user"):
    render_vista_publica()
    st.stop()

st.session_state.admin_last_seen = datetime.now().isoformat()

st.markdown(
    f"""
    <div style="background:radial-gradient(circle at top right, rgba(214,170,76,.12), transparent 32%), linear-gradient(135deg, #0b1220, #121a29 68%, #172437); border:1px solid rgba(255,255,255,.06); border-radius:30px; padding:28px 28px 22px 28px; box-shadow:0 18px 44px rgba(0,0,0,.24); margin-bottom:14px;">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:18px; flex-wrap:wrap;">
            <div>
                <div style="display:inline-block; background:rgba(214,170,76,.12); color:#e7bb58; border:1px solid rgba(214,170,76,.20); border-radius:999px; padding:8px 14px; font-size:12px; font-weight:800; letter-spacing:1px; text-transform:uppercase; margin-bottom:14px;">Panel administrativo</div>
                <div style="color:#f7f9fb; font-size:38px; font-weight:900; line-height:1.05;">Jr AI 11 - Centro de operacion</div>
                <div style="color:#9fb0c5; font-size:16px; margin-top:10px; line-height:1.55;">Gestiona preparacion de partidos, analisis automatico, resultados, usuarios, exportaciones y publicaciones desde un solo lugar.</div>
            </div>
            <div style="background:linear-gradient(135deg, #29d764, #d6aa4c); color:#07111d; padding:14px 18px; border-radius:20px; font-weight:900; font-size:16px;">ADMIN ACTIVO</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    """
    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:12px; margin:0 0 18px 0;">
        <div style="background:#121a28; border:1px solid rgba(255,255,255,.06); border-radius:20px; padding:16px 18px;">
            <div style="color:#8fa1b9; font-size:11px; font-weight:800; letter-spacing:1px; text-transform:uppercase;">Operacion</div>
            <div style="color:#f7f9fb; font-size:17px; font-weight:800; margin-top:8px;">Preparar partido y analisis</div>
        </div>
        <div style="background:#121a28; border:1px solid rgba(255,255,255,.06); border-radius:20px; padding:16px 18px;">
            <div style="color:#8fa1b9; font-size:11px; font-weight:800; letter-spacing:1px; text-transform:uppercase;">Publicacion</div>
            <div style="color:#f7f9fb; font-size:17px; font-weight:800; margin-top:8px;">PDF, Telegram y feed social</div>
        </div>
        <div style="background:#121a28; border:1px solid rgba(255,255,255,.06); border-radius:20px; padding:16px 18px;">
            <div style="color:#8fa1b9; font-size:11px; font-weight:800; letter-spacing:1px; text-transform:uppercase;">Control</div>
            <div style="color:#f7f9fb; font-size:17px; font-weight:800; margin-top:8px;">Resultados, usuarios y aprendizaje</div>
        </div>
        <div style="background:#121a28; border:1px solid rgba(255,255,255,.06); border-radius:20px; padding:16px 18px;">
            <div style="color:#8fa1b9; font-size:11px; font-weight:800; letter-spacing:1px; text-transform:uppercase;">Rendimiento</div>
            <div style="color:#f7f9fb; font-size:17px; font-weight:800; margin-top:8px;">ROI, riesgo y comparativa</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

admin_overview_backend_error = False
_df_admin_overview = fetch_backend_picks(incluir_alternativas=True)
if _df_admin_overview is None:
    print("[BACKEND ERROR] picks | admin_overview | no fallback")
    admin_overview_backend_error = True
    _df_admin_overview = normalize_backend_picks_df(pd.DataFrame())
if admin_overview_backend_error:
    st.warning("⚠️ Resumen de picks no disponible (backend no responde)")

_pend_admin = _df_admin_overview[
    (_df_admin_overview["tipo_pick"] == "principal") & (_df_admin_overview["resultado"] == "pendiente")
].copy() if not _df_admin_overview.empty else pd.DataFrame()
_cerr_admin = _df_admin_overview[
    (_df_admin_overview["tipo_pick"] == "principal") & (_df_admin_overview["resultado"].isin(["ganada", "perdida", "media"]))
].copy() if not _df_admin_overview.empty else pd.DataFrame()
_users_count = len(df_usuarios) if not df_usuarios.empty else 0
_admin_kpis = fetch_backend_metrics(incluir_alternativas=False)
if _admin_kpis is None:
    print("[BACKEND ERROR] metrics | admin_header | no fallback")
    _admin_kpis = {}
    st.warning("⚠️ Datos no disponibles (backend no responde)")

st.markdown(
    f"""
    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:12px; margin:0 0 22px 0;">
        <div style="background:#121a28; border:1px solid rgba(255,255,255,.06); border-radius:20px; padding:16px 18px;">
            <div style="color:#8fa1b9; font-size:11px; font-weight:800; letter-spacing:1px; text-transform:uppercase;">Picks pendientes</div>
            <div style="color:#f7f9fb; font-size:28px; font-weight:900; margin-top:8px;">{len(_pend_admin)}</div>
        </div>
        <div style="background:#121a28; border:1px solid rgba(255,255,255,.06); border-radius:20px; padding:16px 18px;">
            <div style="color:#8fa1b9; font-size:11px; font-weight:800; letter-spacing:1px; text-transform:uppercase;">Picks cerrados</div>
            <div style="color:#f7f9fb; font-size:28px; font-weight:900; margin-top:8px;">{len(_cerr_admin)}</div>
        </div>
        <div style="background:#121a28; border:1px solid rgba(255,255,255,.06); border-radius:20px; padding:16px 18px;">
            <div style="color:#8fa1b9; font-size:11px; font-weight:800; letter-spacing:1px; text-transform:uppercase;">Usuarios</div>
            <div style="color:#f7f9fb; font-size:28px; font-weight:900; margin-top:8px;">{_users_count}</div>
        </div>
        <div style="background:#121a28; border:1px solid rgba(255,255,255,.06); border-radius:20px; padding:16px 18px;">
            <div style="color:#8fa1b9; font-size:11px; font-weight:800; letter-spacing:1px; text-transform:uppercase;">ROI global</div>
            <div style="color:#f7f9fb; font-size:28px; font-weight:900; margin-top:8px;">{_admin_kpis.get('roi_global', 0)}%</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ============================================
# PESTANAS
# ============================================
tab_dash, tab_picks, tab_operacion, tab_pub, tab_lab, tab_users = st.tabs([
    "Dashboard",
    "Mis Picks",
    "Operación",
    "Publicación",
    "Laboratorio",
    "Usuarios",
])

# ====================== DASHBOARD ======================
with tab_dash:
    incluir_alternativas = st.checkbox("Incluir picks alternativos en las metricas", value=False)
    dashboard_backend_error = False
    metrics = fetch_backend_metrics(incluir_alternativas=incluir_alternativas)
    if metrics is None:
        print("[BACKEND ERROR] metrics | dashboard | no fallback")
        dashboard_backend_error = True
        metrics = {}
    df_dash = fetch_backend_picks(incluir_alternativas=incluir_alternativas)
    if df_dash is None:
        print("[BACKEND ERROR] picks | dashboard | no fallback")
        dashboard_backend_error = True
        df_dash = pd.DataFrame()
    if dashboard_backend_error:
        st.warning("⚠️ Dashboard no disponible: backend no responde")
    periodo_dash = st.selectbox(
        "Periodo del dashboard",
        ["Todo", "7 dias", "30 dias", "Mes actual", "Ano actual"],
        key="dashboard_periodo",
    )
    df_dash_periodo = _filtrar_df_por_periodo(df_dash, periodo_dash)
    periodo_comp = st.selectbox(
        "Comparar contra",
        ["Sin comparacion", "7 dias", "30 dias", "Mes anterior", "Ano anterior"],
        key="dashboard_periodo_compare",
    )
    df_dash_compare = pd.DataFrame()
    resumen_compare = None
    if periodo_comp != "Sin comparacion":
        df_dash_compare = _filtrar_df_por_periodo(df_dash, periodo_comp)
        resumen_compare = _resumen_periodo_dashboard(df_dash_compare)
    picks_pendientes_dash = df_dash_periodo[df_dash_periodo["resultado"] == "pendiente"].copy() if not df_dash_periodo.empty else pd.DataFrame()
    picks_cerrados_dash = df_dash_periodo[df_dash_periodo["resultado"].isin(["ganada", "perdida", "media"])].copy() if not df_dash_periodo.empty else pd.DataFrame()

    st.markdown(
        f"""
        <div style="background:radial-gradient(circle at top right, rgba(41,215,100,.10), transparent 32%), linear-gradient(135deg, #0d1523, #121a28 68%, #172437); border:1px solid rgba(255,255,255,.06); border-radius:28px; padding:22px 24px; margin-bottom:16px;">
            <div style="display:flex; justify-content:space-between; gap:18px; flex-wrap:wrap; align-items:flex-start;">
                <div>
                    <div style="display:inline-block; background:rgba(41,215,100,.10); color:#5bf089; border:1px solid rgba(59,226,111,.16); border-radius:999px; padding:7px 12px; font-size:11px; font-weight:800; letter-spacing:1px; text-transform:uppercase; margin-bottom:10px;">EV+ Dashboard</div>
                    <div style="color:#f7f9fb; font-size:30px; font-weight:900; line-height:1.08;">Lectura ejecutiva del sistema</div>
                    <div style="color:#9fb0c5; font-size:15px; margin-top:8px;">Resumen de rendimiento, riesgo, actividad y distribucion operativa para leer la salud del sistema en segundos. Periodo activo: {periodo_dash}.</div>
                </div>
                <div style="background:linear-gradient(135deg, rgba(41,215,100,.16), rgba(214,170,76,.16)); border:1px solid rgba(255,255,255,.08); border-radius:20px; padding:14px 16px; min-width:180px;">
                    <div style="color:#8fa1b9; font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:1px;">Estado actual</div>
                    <div style="color:#f7fbff; font-size:18px; font-weight:900; margin-top:8px;">{"N/A" if dashboard_backend_error else f"{len(picks_pendientes_dash)} pendientes | {len(picks_cerrados_dash)} cerrados"}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3, col4 = st.columns(4)
    bankroll_cop = metrics.get('bankroll_actual', 0)
    bankroll_inicial = get_bankroll_inicial()
    delta_pct = ((bankroll_cop / bankroll_inicial) - 1) * 100
    col1.metric("Bankroll Actual", "N/A" if dashboard_backend_error else mostrar_valor(bankroll_cop), "N/A" if dashboard_backend_error else f"{delta_pct:+.1f}%")
    total_picks_dash = len(df_dash_periodo)
    ganadas_dash = int((picks_cerrados_dash["resultado"] == "ganada").sum()) if not picks_cerrados_dash.empty else 0
    medias_dash = int((picks_cerrados_dash["resultado"] == "media").sum()) if not picks_cerrados_dash.empty else 0
    col2.metric("Total Picks", "N/A" if dashboard_backend_error else total_picks_dash)
    acierto_ponderado = (ganadas_dash + medias_dash/2) / max(1, len(picks_cerrados_dash)) * 100 if len(picks_cerrados_dash) else 0
    col3.metric("Acierto", "N/A" if dashboard_backend_error else f"{acierto_ponderado:.1f}%")
    roi_dash = round(float(picks_cerrados_dash["ganancia"].sum() / picks_cerrados_dash["stake"].sum() * 100), 2) if not picks_cerrados_dash.empty and picks_cerrados_dash["stake"].sum() else 0
    col4.metric("ROI Global", "N/A" if dashboard_backend_error else f"{roi_dash}%")
    col1b, col2b, col3b, col4b = st.columns(4)
    col1b.metric("Yield", "N/A" if dashboard_backend_error else f"{roi_dash}%")
    col2b.metric("Pendientes", "N/A" if dashboard_backend_error else len(picks_pendientes_dash))
    col3b.metric("Cerrados", "N/A" if dashboard_backend_error else len(picks_cerrados_dash))
    df_ia = metrics.get('df_ia', pd.DataFrame())
    if not df_ia.empty and "roi" in df_ia.columns:
        df_ia_sorted = df_ia.sort_values("roi", ascending=False)
        ia_top = str(df_ia_sorted.iloc[0].get("ia", "-"))
        roi_ia_top = float(df_ia_sorted.iloc[0].get("roi", 0) or 0)
    else:
        ia_top = "-"
        roi_ia_top = 0
    col4b.metric("IA top", "N/A" if dashboard_backend_error else ia_top, "N/A" if dashboard_backend_error else f"{roi_ia_top:.1f}%")

    st.subheader("Metricas avanzadas de riesgo")
    riesgo = metrics.get('metricas_riesgo', {})
    if riesgo:
        col_risk1, col_risk2, col_risk3, col_risk4 = st.columns(4)
        col_risk1.metric("Sharpe Ratio", f"{riesgo['sharpe_ratio']:.2f}")
        col_risk2.metric("Max Drawdown", f"{riesgo['max_drawdown']}%")
        col_risk3.metric("Profit Factor", f"{riesgo['profit_factor']:.2f}")
        col_risk4.metric("EV Promedio", f"{riesgo['ev_promedio']:.2f}")
        col_risk5, col_risk6, col_risk7 = st.columns(3)
        col_risk5.metric("Racha Max. Ganadora", riesgo['racha_max_ganadora'])
        col_risk6.metric("Racha Max. Perdedora", riesgo['racha_max_perdedora'])
        col_risk7.metric("p-valor", f"{riesgo['p_value']:.4f}")
        if riesgo['significativo_95']:
            st.success("El sistema presenta significancia estadistica (p < 0.05).")
        else:
            st.warning("El rendimiento observado aun no alcanza significancia estadistica (p >= 0.05).")
    else:
        _render_empty_state("Sin métricas de riesgo", "No hay información suficiente para calcular el Sharpe Ratio, Drawdown o Profit Factor.", "📊")

    colA, colB = st.columns(2)
    with colA:
        evolucion_df = metrics.get('evolucion', pd.DataFrame())
        if not evolucion_df.empty:
            fig_bank = px.line(evolucion_df, x='fecha', y='bankroll',
                               title="Evolucion del Bankroll", markers=True)
            st.plotly_chart(fig_bank, width='stretch')
        else:
            _render_empty_state("Sin historial de bankroll", "Se requiere al menos un pick cerrado para visualizar la evolución.", "📈")
    with colB:
        if not df_ia.empty:
            fig_roi = px.bar(df_ia, x='ia', y='roi',
                             title="ROI por IA", color='roi', color_continuous_scale='RdYlGn')
            st.plotly_chart(fig_roi, width='stretch')
        else:
            _render_empty_state("Sin ROI por IA", "No hay datos de rendimiento por modelo todavía.", "🤖")

    colC, colD = st.columns(2)
    with colC:
        if not picks_cerrados_dash.empty and "resultado" in picks_cerrados_dash.columns:
            dist = picks_cerrados_dash["resultado"].value_counts().reset_index()
            dist.columns = ["resultado", "total"]
            fig_dist = px.pie(
                dist,
                names="resultado",
                values="total",
                title="Distribucion de cierres",
                color="resultado",
                color_discrete_map={"ganada": "#31b36b", "perdida": "#d14b4b", "media": "#d6aa4c"},
            )
            fig_dist.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="#f5f7fa")
            st.plotly_chart(fig_dist, width="stretch")
        else:
            st.info("Aun no hay cierres suficientes para mostrar distribucion.")
    with colD:
        if not df_dash_periodo.empty and "mercado" in df_dash_periodo.columns:
            df_market = df_dash_periodo.copy()
            df_market["mercado"] = df_market["mercado"].fillna("Sin mercado").astype(str)
            ranking_market = df_market["mercado"].value_counts().head(8).reset_index()
            ranking_market.columns = ["mercado", "total"]
            fig_market = px.bar(
                ranking_market,
                x="mercado",
                y="total",
                title="Mercados mas trabajados",
                color="total",
                color_continuous_scale="Blues",
            )
            fig_market.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(15,22,34,0.85)", font_color="#f5f7fa")
            st.plotly_chart(fig_market, width="stretch")
        else:
            st.info("No hay informacion suficiente para construir ranking de mercados.")

    if resumen_compare is not None:
        st.markdown("### Comparativa de periodos")
        resumen_actual = _resumen_periodo_dashboard(df_dash_periodo)
        cmp1, cmp2, cmp3, cmp4 = st.columns(4)
        cmp1.metric("ROI actual vs comparado", f"{resumen_actual['roi']:.2f}%", f"{resumen_actual['roi'] - resumen_compare['roi']:+.2f}%")
        cmp2.metric("Acierto actual vs comparado", f"{resumen_actual['acierto']:.1f}%", f"{resumen_actual['acierto'] - resumen_compare['acierto']:+.1f}%")
        cmp3.metric("Cerrados actual vs comparado", resumen_actual["cerrados"], f"{resumen_actual['cerrados'] - resumen_compare['cerrados']:+d}")
        cmp4.metric("Pendientes actual vs comparado", resumen_actual["pendientes"], f"{resumen_actual['pendientes'] - resumen_compare['pendientes']:+d}")

# ====================== IMPORTAR PICKS ======================
with tab_picks:
    st.divider()
    st.header("Carga Manual de Picks")
    st.subheader("Carga de archivos de picks")
    st.markdown("Formato esperado: IA, FECHA, ---, PARTIDO, MERCADO, SELECCION, CUOTA, CONFIANZA, ANALISIS (o JSON estructurado)")

    uploaded_files = st.file_uploader(
        "Selecciona uno o varios archivos .txt o .json",
        type=["txt", "json"],
        accept_multiple_files=True,
    )

    if uploaded_files:
        all_dfs = []
        for file in uploaded_files:
            try:
                df = validate_and_load_file(file)
                all_dfs.append(df)
                st.success(f"{file.name} cargado correctamente")
            except Exception as e:
                st.error(f"{file.name}: {e}")

        if all_dfs:
            preview = pd.concat(all_dfs, ignore_index=True)
            if 'tipo_pick' in preview.columns:
                st.dataframe(preview[['fecha', 'ia', 'partido', 'mercado', 'seleccion', 'cuota', 'confianza', 'tipo_pick']], width='stretch')
            else:
                st.dataframe(preview, width='stretch')

            if st.button("Importar todos los picks seleccionados"):
                batch = datetime.now().strftime("%Y%m%d_%H%M%S")
                save_picks(preview, batch)
                st.success(f"{len(preview)} picks importados en el lote {batch}.")
                st.rerun()

    st.markdown("---")
    st.subheader("Registro manual guiado")
    st.caption("Usa este bloque para cargar un pick manual principal o alternativo sin depender de archivos.")

    with st.form("form_pick_manual_guiado"):
        col_pm1, col_pm2, col_pm3 = st.columns(3)
        pm_ia = col_pm1.text_input("IA / Fuente", value="Manual")
        pm_fecha = col_pm2.text_input("Fecha", value=datetime.now().strftime("%Y-%m-%d"))
        pm_tipo = col_pm3.selectbox("Tipo de pick", ["principal", "alternativa"])

        pm_partido = st.text_input("Partido", placeholder="Ej: Atletico Nacional vs Llaneros")

        col_pm4, col_pm5, col_pm6 = st.columns(3)
        pm_mercado = col_pm4.text_input("Mercado", placeholder="Ej: 1X2, Over/Under, BTTS")
        pm_seleccion = col_pm5.text_input("Seleccion", placeholder="Ej: Atletico Nacional, Under 2.5")
        pm_cuota = col_pm6.number_input("Cuota", min_value=1.01, value=1.90, step=0.01)

        col_pm7, col_pm8 = st.columns(2)
        pm_confianza = col_pm7.number_input("Confianza", min_value=0.0, max_value=1.0, value=0.65, step=0.01)
        pm_competicion = col_pm8.text_input("Competicion", placeholder="Opcional")

        pm_analisis = st.text_area("Analisis breve", height=100, placeholder="Lectura corta del pick manual")

        guardar_manual = st.form_submit_button("Guardar pick manual en la base")

    if guardar_manual:
        if not pm_partido.strip() or not pm_mercado.strip() or not pm_seleccion.strip():
            st.warning("Completa al menos partido, mercado y seleccion para registrar el pick.")
        else:
            try:
                with st.spinner("Guardando pick manual..."):
                    df_manual = pd.DataFrame([
                        {
                            "ia": pm_ia.strip() or "Manual",
                            "fecha": pm_fecha.strip() or datetime.now().strftime("%Y-%m-%d"),
                            "partido": pm_partido.strip(),
                            "mercado": pm_mercado.strip(),
                            "seleccion": pm_seleccion.strip(),
                            "cuota": pm_cuota,
                            "confianza": pm_confianza,
                            "analisis_breve": pm_analisis.strip(),
                            "tipo_pick": pm_tipo,
                            "resultado": "pendiente"
                        }
                    ])
                    batch_manual = f"manual_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    resultado_save = save_picks(df_manual, batch_manual)
                    insertados = resultado_save.get("insertados", 0) if isinstance(resultado_save, dict) else 0
                    
                     if insertados > 0:
                         st.success(f"✓ Pick manual {'alternativo' if pm_tipo == 'alternativa' else 'principal'} guardado correctamente.")
                         # Intentar auto-publicar si es principal
                         lote_backend_error = False
                         df_lote = fetch_backend_picks(incluir_alternativas=True)
                         if df_lote is None:
                             lote_backend_error = True
                             df_lote = normalize_backend_picks_df(pd.DataFrame())
                         if lote_backend_error:
                             st.error("Auto-publicación no disponible: backend no responde")
                         else:
                            lote = df_lote[df_lote["import_batch"] == batch_manual].copy() if not df_lote.empty and "import_batch" in df_lote.columns else pd.DataFrame()
                            if not lote.empty:
                                pick_pub = lote.iloc[0].to_dict()
                                auto_pub = _enviar_pick_telegram_si_activo(pick_pub)
                                if auto_pub:
                                    ok, mens = auto_pub
                                    if ok: st.success(f"Auto-publicacion Telegram: {mens}")
                                    else: st.warning(mens)
                    else:
                        st.warning("No se pudo insertar el pick. Puede que ya exista un registro identico.")
                    st.rerun()
            except Exception as e:
                st.error(f"Fallo critico al guardar el pick manual: {e}")

# ====================== REGISTRAR RESULTADOS ======================
    st.divider()
    st.header("Resultados de Picks")
    picks_backend_error = False
    df = fetch_backend_picks(incluir_alternativas=True)
    if df is None:
        print("[BACKEND ERROR] picks | tab_picks | no fallback")
        picks_backend_error = True
        df = pd.DataFrame()
    if picks_backend_error:
        st.warning("⚠️ Datos de picks no disponibles (backend no responde)")
    if df.empty:
        if picks_backend_error:
            st.info("Datos no disponibles temporalmente.")
        else:
            st.info("Aun no hay picks registrados. Carga informacion primero desde la pestana de picks.")
    else:
        _render_section_banner(
            "Registro de resultados",
            "Cierra picks pendientes, consulta cuotas reales y actualiza el rendimiento operativo del sistema.",
            "Resultados",
        )
        pendientes_total = int((df["resultado"] == "pendiente").sum()) if "resultado" in df.columns else 0
        cerrados_total = len(df) - pendientes_total
        principales_total = int((df["tipo_pick"] == "principal").sum()) if "tipo_pick" in df.columns else 0
        alternativas_total = int((df["tipo_pick"] == "alternativa").sum()) if "tipo_pick" in df.columns else 0
        rr1, rr2, rr3, rr4 = st.columns(4)
        rr1.metric("Pendientes", pendientes_total)
        rr2.metric("Cerrados", cerrados_total)
        rr3.metric("Principales", principales_total)
        rr4.metric("Alternativos", alternativas_total)

        # Construir opciones_liga desde el nuevo league_service
        opciones_liga = {v: k for k, v in LIGAS_NOMBRES.items()}

        filtro_cols = st.columns([1.2, 1.2, 1.6])
        tipo_mostrar = filtro_cols[0].radio("Mostrar:", ["Principales", "Alternativas", "Todos"], horizontal=True)
        estado_mostrar = filtro_cols[1].radio("Estado:", ["Solo pendientes", "Todos (incluye registrados)"], horizontal=True)
        busqueda_resultados = filtro_cols[2].text_input(
            "Buscar partido o IA",
            placeholder="Ej: Lazio, Groq, Nacional...",
            key="registro_resultados_busqueda",
        )

        if tipo_mostrar == "Principales":
            df_filtrado = df[df['tipo_pick'] == 'principal']
        elif tipo_mostrar == "Alternativas":
            df_filtrado = df[df['tipo_pick'] == 'alternativa']
        else:
            df_filtrado = df

        if estado_mostrar == "Solo pendientes":
            df_filtrado = df_filtrado[df_filtrado['resultado'] == 'pendiente']

        if busqueda_resultados.strip():
            patron = busqueda_resultados.strip().lower()
            df_filtrado = df_filtrado[
                df_filtrado["partido"].fillna("").astype(str).str.lower().str.contains(patron, na=False)
                | df_filtrado["ia"].fillna("").astype(str).str.lower().str.contains(patron, na=False)
            ]

        if df_filtrado.empty:
            st.info(f"No hay picks {tipo_mostrar.lower()} en el estado seleccionado.")
        else:
            st.subheader(f"Registros visibles: {len(df_filtrado)}")

            bookmaker_elegido = st.selectbox(
                "Casa de apuestas para cuota real",
                ["Bet365", "Pinnacle", "Betsson", "Coolbet", "Manual"],
                help="Bet365 y Pinnacle son las referencias principales."
            )

            if 'cuotas_cache' not in st.session_state:
                st.session_state.cuotas_cache = {}

            for idx, row in df_filtrado.iterrows():
                with st.container():
                    cols = st.columns([2, 1, 1, 1, 1])

                    if tipo_mostrar == "Todos":
                        tipo_etiqueta = "[Principal]" if row['tipo_pick'] == 'principal' else "[Alternativa]"
                        cols[0].write(f"{tipo_etiqueta} **{row['ia']}** - {row['partido']} | {row['mercado']} @ {row['cuota']}")
                    else:
                        cols[0].write(f"**{row['ia']}** - {row['partido']} | {row['mercado']} @ {row['cuota']}")

                    cols[1].write(row['seleccion'])

                    if row['resultado'] != 'pendiente':
                        cols[2].write(f"**Resultado:** {row['resultado']}")
                        cols[3].write(f"**Cuota real:** {row['cuota_real']}")
                        cols[4].write(f"**Ganancia:** {row['ganancia']:.2f}")
                    else:
                        # Deteccion automatica de liga
                        liga_key = get_league_key(row['partido'])
                        if liga_key is None:
                            state_key = f"liga_{row['id']}"
                            if state_key not in st.session_state:
                                st.session_state[state_key] = list(opciones_liga.keys())[0]
                            liga_elegida = st.selectbox(
                                "Liga",
                                list(opciones_liga.keys()),
                                index=list(opciones_liga.keys()).index(st.session_state[state_key]),
                                key=f"select_{row['id']}"
                            )
                            st.session_state[state_key] = liga_elegida
                            liga_key = opciones_liga[liga_elegida]

                        cache_key = f"{row['id']}_{bookmaker_elegido}"
                        cuota_sugerida = row['cuota']

                        if bookmaker_elegido != "Manual":
                            if cache_key in st.session_state.cuotas_cache:
                                cuota_sugerida = st.session_state.cuotas_cache[cache_key]
                            else:
                                with st.spinner(f"Obteniendo cuota de {bookmaker_elegido}..."):
                                    from obtener_cuotas_api import obtener_cuota_de_bookmaker
                                    c_local, c_empate, c_visit = obtener_cuota_de_bookmaker(
                                        liga_key, row['partido'], bookmaker_elegido
                                    )
                                    if c_local and ("Local" in row['seleccion'] or row['seleccion'] == row['partido'].split(' vs ')[0]):
                                        cuota_sugerida = c_local
                                    elif c_empate and "Empate" in row['seleccion']:
                                        cuota_sugerida = c_empate
                                    elif c_visit and ("Visitante" in row['seleccion'] or row['seleccion'] == row['partido'].split(' vs ')[-1]):
                                        cuota_sugerida = c_visit
                                    st.session_state.cuotas_cache[cache_key] = cuota_sugerida

                        if cuota_sugerida is None or cuota_sugerida == 0:
                            cuota_sugerida = row['cuota'] if row['cuota'] >= 1.01 else 1.01

                        try:
                            cuota_valida = float(cuota_sugerida)
                            cuota_valida = max(1.01, min(100.0, cuota_valida))
                        except (ValueError, TypeError):
                            cuota_valida = 1.01

                        cuota_real = cols[2].number_input(
                            "Cuota real", min_value=1.01, max_value=100.0,
                            value=cuota_valida, step=0.01,
                            key=f"cuota_{row['id']}", label_visibility="collapsed"
                        )

                        opciones_res = ['ganada', 'perdida']
                        if es_handicap_asiatico(row['seleccion']):
                            opciones_res.append('media')
                        nuevo = cols[3].selectbox(
                            "Resultado", opciones_res,
                            key=f"res_{row['id']}", label_visibility="collapsed"
                        )

                        if cols[4].button("Guardar", key=f"btn_{row['id']}"):
                            from database import update_resultado_con_cuota
                            update_resultado_con_cuota(row['id'], nuevo, cuota_real)
                            if cache_key in st.session_state.cuotas_cache:
                                del st.session_state.cuotas_cache[cache_key]
                            st.success(f"Registro actualizado: {row['seleccion']} -> {nuevo} @ {cuota_real_input}")
                            actualizado_backend_error = False
                            actualizado = fetch_backend_picks(incluir_alternativas=True)
                            if actualizado is None:
                                actualizado_backend_error = True
                                actualizado = normalize_backend_picks_df(pd.DataFrame())
                            if actualizado_backend_error:
                                st.error("Auto-publicación no disponible: backend no responde")
                            else:
                                if not actualizado.empty and "id" in actualizado.columns:
                                fila_act = actualizado[actualizado["id"] == row["id"]]
                                if not fila_act.empty:
                                    auto_pub = _enviar_resultado_telegram_si_activo(fila_act.iloc[0].to_dict())
                                    if auto_pub:
                                        ok, mensaje = auto_pub
                                        if ok:
                                            st.success(f"Auto-publicacion Telegram: {mensaje}")
                                        else:
                                            st.warning(mensaje)
                            st.rerun()

                    st.divider()

# ====================== DETALLE & EXPORT ======================
with tab_pub:
    from pdf_generator import (
        recopilar_todos_los_picks,
        generar_pdf,
        generar_pdf_desde_dataframe,
        generar_pdf_pick_oficial,
        generar_pdf_resultado_pick,
        generar_pdf_pick_social,
        generar_pdf_resultado_social,
    )
    from services.telegram_service import (
        telegram_config_ok,
        enviar_mensaje_telegram,
        enviar_documento_telegram,
        enviar_paquete_telegram,
    )

    _render_section_banner(
        "Publicacion y exportacion",
        "Convierte picks y resultados en piezas listas para compartir por Telegram, PDF o base operativa.",
        "Publicacion",
    )
    publicacion_backend_error = False
    df_publicacion = fetch_backend_picks(incluir_alternativas=True)
    if df_publicacion is None:
        print("[BACKEND ERROR] picks | publicacion | no fallback")
        publicacion_backend_error = True
        df_publicacion = normalize_backend_picks_df(pd.DataFrame())
    if publicacion_backend_error:
        st.warning("⚠️ Picks no disponibles para publicación (backend no responde)")
    if not df_publicacion.empty:
        pub_pendientes = int(((df_publicacion["tipo_pick"] == "principal") & (df_publicacion["resultado"] == "pendiente")).sum())
        pub_cerrados = int(((df_publicacion["tipo_pick"] == "principal") & (df_publicacion["resultado"].isin(["ganada", "perdida", "media"]))).sum())
        pub_total = len(df_publicacion)
        pub_cols = st.columns(4)
        pub_cols[0].metric("Base total", pub_total)
        pub_cols[1].metric("Principales pendientes", pub_pendientes)
        pub_cols[2].metric("Principales cerrados", pub_cerrados)
        pub_cols[3].metric("Telegram", "Listo" if telegram_config_ok() else "No configurado")

    st.subheader("Publicacion rapida a Telegram")
    if not df_publicacion.empty and telegram_config_ok():
        df_pendientes_pub = df_publicacion[
            (df_publicacion["tipo_pick"] == "principal")
            & (df_publicacion["resultado"] == "pendiente")
        ].copy()
        df_cerrados_pub = df_publicacion[
            (df_publicacion["tipo_pick"] == "principal")
            & (df_publicacion["resultado"].isin(["ganada", "perdida", "media"]))
        ].copy()

        if "id" in df_pendientes_pub.columns and not df_pendientes_pub.empty:
            df_pendientes_pub = df_pendientes_pub.sort_values(by="id", ascending=False)
        if "id" in df_cerrados_pub.columns and not df_cerrados_pub.empty:
            df_cerrados_pub = df_cerrados_pub.sort_values(by="id", ascending=False)

        col_q1, col_q2 = st.columns(2)

        with col_q1:
            st.caption("Pick principal mas reciente")
            if df_pendientes_pub.empty:
                st.info("No hay picks principales pendientes para publicacion rapida.")
            else:
                pick_rapido = df_pendientes_pub.iloc[0].to_dict()
                confianza_rapida = int(float(pick_rapido.get("confianza", 0) or 0) * 100)
                cuota_rapida = float(pick_rapido.get("cuota", 0) or 0)
                resumen_rapido = str(pick_rapido.get("analisis_breve", "") or "").strip()
                resumen_rapido = resumen_rapido[:220] + ("..." if len(resumen_rapido) > 220 else "")
                pick_rapido_complete = all(pick_rapido.get(k) for k in ["partido", "mercado", "seleccion", "cuota", "confianza"])
                if not pick_rapido_complete or publicacion_backend_error:
                    st.error("No se puede publicar: datos del pick incompletos o backend no responde.")
                    st.stop()
                st.write(
                    f"**{pick_rapido.get('partido', '')}**  \n"
                    f"{pick_rapido.get('mercado', '')}: {pick_rapido.get('seleccion', '')} @ {cuota_rapida:.2f}"
                )
                if st.button("Publicar pick rapido a Telegram"):
                    copy_rapido = _copy_pick_social(
                        pick_rapido,
                        resumen_rapido,
                        confianza_rapida,
                        cuota_rapida,
                    )
                    pdf_rapido = generar_pdf_pick_social(pick_rapido)
                    ok, mensaje = enviar_paquete_telegram(
                        copy_rapido,
                        pdf_rapido,
                        f"pick_social_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                        caption=f"Pick oficial | {pick_rapido.get('partido', '')}",
                    )
                    if ok:
                        st.success(mensaje)
                    else:
                        st.error(mensaje)

        with col_q2:
            st.caption("Ultimo resultado cerrado")
            if df_cerrados_pub.empty:
                st.info("No hay picks cerrados para publicacion rapida.")
            else:
                resultado_rapido = df_cerrados_pub.iloc[0].to_dict()
                cuota_res_rapida = float(resultado_rapido.get("cuota", 0) or 0)
                ganancia_res_rapida = float(resultado_rapido.get("ganancia", 0) or 0)
                estado_res_rapido = str(resultado_rapido.get("resultado", "")).strip().lower()
                etiqueta_res_rapida = "WIN"
                if estado_res_rapido == "perdida":
                    etiqueta_res_rapida = "LOSS"
                elif estado_res_rapido == "media":
                    etiqueta_res_rapida = "PUSH"
                resultado_rapido_complete = all(resultado_rapido.get(k) for k in ["partido", "mercado", "seleccion", "resultado", "cuota_real", "ganancia"])
                if not resultado_rapido_complete or publicacion_backend_error:
                    st.error("No se puede publicar: datos del resultado incompletos o backend no responde.")
                    st.stop()
                st.write(
                    f"**{resultado_rapido.get('partido', '')}**  \n"
                    f"{resultado_rapido.get('mercado', '')}: {resultado_rapido.get('seleccion', '')} | {etiqueta_res_rapida}"
                )
                if st.button("Publicar resultado rapido a Telegram"):
                    copy_res_rapido = _copy_resultado_social(
                        resultado_rapido,
                        etiqueta_res_rapida,
                        cuota_res_rapida,
                        ganancia_res_rapida,
                    )
                    pdf_res_rapido = generar_pdf_resultado_social(resultado_rapido)
                    ok, mensaje = enviar_paquete_telegram(
                        copy_res_rapido,
                        pdf_res_rapido,
                        f"resultado_social_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                        caption=f"Resultado | {resultado_rapido.get('partido', '')}",
                    )
                    if ok:
                        st.success(mensaje)
                    else:
                        st.error(mensaje)
    elif not telegram_config_ok():
        st.info("Configura Telegram en el .env para activar la publicacion rapida.")
    else:
        st.info("Todavia no hay picks en la base para usar publicacion rapida.")

    st.markdown("---")

    st.markdown("---")
    st.subheader("Pick oficial del dia")
    pick_oficial_backend_error = False
    df_pick_oficial = fetch_backend_picks(incluir_alternativas=True)
    if df_pick_oficial is None:
        print("[BACKEND ERROR] picks | pick_oficial | no fallback")
        pick_oficial_backend_error = True
        df_pick_oficial = normalize_backend_picks_df(pd.DataFrame())
    if pick_oficial_backend_error:
        st.warning("⚠️ Picks no disponibles para pick oficial (backend no responde)")
    if not df_pick_oficial.empty:
        df_pick_oficial = df_pick_oficial[
            (df_pick_oficial["tipo_pick"] == "principal") & (df_pick_oficial["resultado"] == "pendiente")
        ].copy()

        if df_pick_oficial.empty:
            st.info("No hay picks principales pendientes para convertir en pick oficial.")
        else:
            df_pick_oficial["label_pick"] = df_pick_oficial.apply(
                lambda r: f"{r['partido']} | {r['ia']} | {r['mercado']} | {r['seleccion']} @ {r['cuota']}",
                axis=1,
            )
            opcion_pick = st.selectbox("Selecciona el pick a convertir", df_pick_oficial["label_pick"].tolist())
            pick_seleccionado = df_pick_oficial[df_pick_oficial["label_pick"] == opcion_pick].iloc[0].to_dict()
            pick_data_complete = all(pick_seleccionado.get(k) for k in ["partido", "mercado", "seleccion", "cuota", "confianza"])
            if not pick_data_complete or pick_oficial_backend_error:
                st.error("No se puede publicar: datos del pick incompletos o backend no responde.")
                st.stop()

            col_p1, col_p2 = st.columns(2)
            titulo_pick = col_p1.text_input("Titulo del pick", value="Jr AI 11 - Pick Oficial")
            subtitulo_pick = col_p2.text_input("Subtitulo", value="Seleccion destacada del sistema")

            confianza_pct = int(float(pick_seleccionado.get("confianza", 0) or 0) * 100)
            cuota_pick = float(pick_seleccionado.get("cuota", 0) or 0)
            resumen_pick = str(pick_seleccionado.get("analisis_breve", "") or "").strip()
            resumen_pick = resumen_pick[:220] + ("..." if len(resumen_pick) > 220 else "")

            st.markdown("### Vista previa del copy")
            copy_corto = (
                f"PICK OFICIAL\n"
                f"{pick_seleccionado.get('partido', '')}\n"
                f"{pick_seleccionado.get('mercado', '')}: {pick_seleccionado.get('seleccion', '')}\n"
                f"Cuota: {cuota_pick:.2f} | Confianza: {confianza_pct}%"
            )
            copy_social = _copy_pick_social(
                pick_seleccionado,
                resumen_pick,
                confianza_pct,
                cuota_pick,
            )
            copy_largo = (
                f"{titulo_pick}\n\n"
                f"Partido: {pick_seleccionado.get('partido', '')}\n"
                f"Mercado: {pick_seleccionado.get('mercado', '')}\n"
                f"Seleccion: {pick_seleccionado.get('seleccion', '')}\n"
                f"Cuota: {cuota_pick:.2f}\n"
                f"Confianza declarada: {confianza_pct}%\n"
                f"IA / Fuente: {pick_seleccionado.get('ia', '')}\n"
                f"Lectura breve: {resumen_pick}"
            )
            pick_copy_suffix = re.sub(r"[^a-zA-Z0-9_]+", "_", str(opcion_pick))[:80]
            st.text_area("Copy corto", value=copy_corto, height=100, key=f"copy_corto_{pick_copy_suffix}")
            st.text_area("Copy redes", value=copy_social, height=150, key=f"copy_redes_{pick_copy_suffix}")
            st.text_area("Copy largo", value=copy_largo, height=180, key=f"copy_largo_{pick_copy_suffix}")

            col_pick_dl1, col_pick_dl2, col_pick_dl3, col_pick_dl4 = st.columns(4)
            col_pick_dl1.download_button(
                "Descargar copy TXT",
                data=copy_largo,
                file_name=f"pick_oficial_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                mime="text/plain",
            )
            if telegram_config_ok():
                if col_pick_dl2.button("Enviar copy social a Telegram"):
                    ok, mensaje = enviar_mensaje_telegram(copy_social)
                    if ok:
                        st.success(mensaje)
                    else:
                        st.error(mensaje)
            else:
                col_pick_dl2.caption("Telegram no configurado")
            try:
                pdf_pick = generar_pdf_pick_oficial(
                    pick_seleccionado,
                    titulo=titulo_pick,
                    subtitulo=subtitulo_pick,
                )
                col_pick_dl3.download_button(
                    "Descargar PDF individual",
                    data=pdf_pick,
                    file_name=f"pick_oficial_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                    mime="application/pdf",
                )
                pdf_pick_social = generar_pdf_pick_social(pick_seleccionado)
                col_pick_dl4.download_button(
                    "Descargar PDF social",
                    data=pdf_pick_social,
                    file_name=f"pick_social_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                    mime="application/pdf",
                )
                if telegram_config_ok():
                    if st.button("Enviar PDF individual a Telegram"):
                        ok, mensaje = enviar_documento_telegram(
                            pdf_pick,
                            f"pick_oficial_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                            caption=f"{titulo_pick} | {pick_seleccionado.get('partido', '')}",
                        )
                        if ok:
                            st.success(mensaje)
                        else:
                            st.error(mensaje)
                    if st.button("Enviar pack social a Telegram"):
                        ok, mensaje = enviar_paquete_telegram(
                            copy_social,
                            pdf_pick_social,
                            f"pick_social_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                            caption=f"Pick oficial | {pick_seleccionado.get('partido', '')}",
                        )
                        if ok:
                            st.success(mensaje)
                        else:
                            st.error(mensaje)
            except Exception as e:
                col_pick_dl3.warning(f"No se pudo preparar PDF individual: {e}")
    else:
        st.info("Todavia no hay picks en la base para crear un pick oficial.")

    st.markdown("---")

    st.markdown("---")
    st.subheader("Post de resultado")
    resultado_post_backend_error = False
    df_resultado_post = fetch_backend_picks(incluir_alternativas=True)
    if df_resultado_post is None:
        print("[BACKEND ERROR] picks | resultado_post | no fallback")
        resultado_post_backend_error = True
        df_resultado_post = normalize_backend_picks_df(pd.DataFrame())
    if resultado_post_backend_error:
        st.warning("⚠️ Picks no disponibles para post de resultado (backend no responde)")
    if not df_resultado_post.empty:
        df_resultado_post = df_resultado_post[
            (df_resultado_post["tipo_pick"] == "principal")
            & (df_resultado_post["resultado"].isin(["ganada", "perdida", "media"]))
        ].copy()

        if df_resultado_post.empty:
            st.info("No hay picks principales cerrados para convertir en post de resultado.")
        else:
            df_resultado_post["label_resultado"] = df_resultado_post.apply(
                lambda r: f"{r['partido']} | {r['ia']} | {r['seleccion']} | {r['resultado']}",
                axis=1,
            )
            opcion_resultado = st.selectbox(
                "Selecciona el pick cerrado",
                df_resultado_post["label_resultado"].tolist(),
                key="resultado_pick_selector",
            )
            pick_cerrado = df_resultado_post[
                df_resultado_post["label_resultado"] == opcion_resultado
            ].iloc[0].to_dict()
            resultado_data_complete = all(pick_cerrado.get(k) for k in ["partido", "resultado", "cuota_real", "ganancia"])
            if not resultado_data_complete or resultado_post_backend_error:
                st.error("No se puede publicar: datos del resultado incompletos o backend no responde.")
                st.stop()

            titulo_resultado = "Jr AI 11 - Resultado del Pick"
            estado_resultado = str(pick_cerrado.get("resultado", "")).strip().lower()
            etiqueta_estado = "WIN"
            if estado_resultado == "perdida":
                etiqueta_estado = "LOSS"
            elif estado_resultado == "media":
                etiqueta_estado = "PUSH"

            cuota_pub = float(pick_cerrado.get("cuota", 0) or 0)
            ganancia_pub = float(pick_cerrado.get("ganancia", 0) or 0)
            copy_resultado = (
                f"{titulo_resultado}\n\n"
                f"{etiqueta_estado}\n"
                f"Partido: {pick_cerrado.get('partido', '')}\n"
                f"Mercado: {pick_cerrado.get('mercado', '')}\n"
                f"Seleccion: {pick_cerrado.get('seleccion', '')}\n"
                f"Cuota publicada: {cuota_pub:.2f}\n"
                f"Ganancia registrada: {ganancia_pub:.2f}\n"
                f"Fuente / IA: {pick_cerrado.get('ia', '')}"
            )
            copy_resultado_social = _copy_resultado_social(
                pick_cerrado,
                etiqueta_estado,
                cuota_pub,
                ganancia_pub,
            )

            resultado_copy_suffix = re.sub(r"[^a-zA-Z0-9_]+", "_", str(opcion_resultado))[:80]
            st.text_area(
                "Copy de resultado",
                value=copy_resultado,
                height=180,
                key=f"copy_resultado_{resultado_copy_suffix}",
            )
            st.text_area(
                "Copy redes resultado",
                value=copy_resultado_social,
                height=140,
                key=f"copy_resultado_social_{resultado_copy_suffix}",
            )

            col_rp1, col_rp2, col_rp3, col_rp4 = st.columns(4)
            col_rp1.download_button(
                "Descargar copy resultado",
                data=copy_resultado,
                file_name=f"resultado_pick_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                mime="text/plain",
            )

            if telegram_config_ok():
                if col_rp2.button("Enviar copy social resultado"):
                    ok, mensaje = enviar_mensaje_telegram(copy_resultado_social)
                    if ok:
                        st.success(mensaje)
                    else:
                        st.error(mensaje)
            else:
                col_rp2.caption("Telegram no configurado")

            try:
                pdf_resultado = generar_pdf_resultado_pick(pick_cerrado)
                col_rp3.download_button(
                    "Descargar PDF resultado",
                    data=pdf_resultado,
                    file_name=f"resultado_pick_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                    mime="application/pdf",
                )
                pdf_resultado_social = generar_pdf_resultado_social(pick_cerrado)
                col_rp4.download_button(
                    "Descargar PDF social",
                    data=pdf_resultado_social,
                    file_name=f"resultado_social_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                    mime="application/pdf",
                )
                if telegram_config_ok():
                    if st.button("Enviar PDF resultado a Telegram"):
                        ok, mensaje = enviar_documento_telegram(
                            pdf_resultado,
                            f"resultado_pick_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                            caption=f"{titulo_resultado} | {pick_cerrado.get('partido', '')}",
                        )
                        if ok:
                            st.success(mensaje)
                        else:
                            st.error(mensaje)
                    if st.button("Enviar pack resultado a Telegram"):
                        ok, mensaje = enviar_paquete_telegram(
                            copy_resultado_social,
                            pdf_resultado_social,
                            f"resultado_social_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                            caption=f"Resultado | {pick_cerrado.get('partido', '')}",
                        )
                        if ok:
                            st.success(mensaje)
                        else:
                            st.error(mensaje)
            except Exception as e:
                col_rp3.warning(f"No se pudo preparar PDF de resultado: {e}")
    else:
        st.info("Todavia no hay picks en la base para crear posts de resultado.")

    st.markdown("---")

    st.markdown("---")
    st.subheader("Boletin compartible desde la base")
    boletin_backend_error = False
    df_boletin = fetch_backend_picks(incluir_alternativas=True)
    if df_boletin is None:
        print("[BACKEND ERROR] picks | boletin | no fallback")
        boletin_backend_error = True
        df_boletin = normalize_backend_picks_df(pd.DataFrame())
    if boletin_backend_error:
        st.warning("⚠️ Picks no disponibles para boletín (backend no responde)")
    if not df_boletin.empty:
        col_b1, col_b2, col_b3 = st.columns(3)
        tipo_boletin = col_b1.selectbox("Tipo de picks", ["Solo principales", "Solo alternativos", "Todos"], key="boletin_tipo")
        estado_boletin = col_b2.selectbox("Estado a exportar", ["Solo pendientes", "Todos"], key="boletin_estado")
        titulo_boletin = col_b3.text_input("Titulo del PDF", value="Jr AI 11 - Boletin de Picks")
        subtitulo_boletin = st.text_input(
            "Subtitulo del PDF",
            value="Resumen operativo de picks listos para compartir",
        )

        df_export = df_boletin.copy()
        if tipo_boletin == "Solo principales":
            df_export = df_export[df_export["tipo_pick"] == "principal"]
        elif tipo_boletin == "Solo alternativos":
            df_export = df_export[df_export["tipo_pick"] == "alternativa"]

        if estado_boletin == "Solo pendientes":
            df_export = df_export[df_export["resultado"] == "pendiente"]

        df_export_valido = df_export.dropna(subset=['partido', 'mercado', 'seleccion', 'cuota'])
        if not df_export.empty and df_export_valido.empty:
            st.error("No se puede generar PDF: picks sin datos mínimos (partido/mercado/seleccion/cuota).")
            st.stop()

        if df_export.empty:
            st.info("No hay picks en la base con ese filtro para generar boletin.")
        else:
            st.caption(f"Picks incluidos en el boletin: {len(df_export)}")
            if st.button("Generar PDF desde la base"):
                with st.spinner("Preparando boletin PDF consolidado..."):
                    try:
                        pdf_base = generar_pdf_desde_dataframe(
                            df_export,
                            titulo=titulo_boletin,
                            subtitulo=subtitulo_boletin,
                        )
                        fecha_pdf = datetime.now().strftime("%Y%m%d_%H%M")
                        st.success("✓ Boletin PDF generado con exito.")
                        st.download_button(
                            "Descargar boletin PDF",
                            data=pdf_base,
                            file_name=f"boletin_picks_{fecha_pdf}.pdf",
                            mime="application/pdf",
                        )
                        if telegram_config_ok():
                            with st.spinner("Enviando boletin a Telegram..."):
                                ok, mensaje = enviar_documento_telegram(
                                    pdf_base,
                                    f"boletin_picks_{fecha_pdf}.pdf",
                                    caption=titulo_boletin,
                                )
                            if ok:
                                st.success("✓ Boletin tambien enviado a Telegram.")
                            else:
                                st.warning(f"Boletin generado, pero fallo el envio a Telegram: {mensaje}")
                    except Exception as e:
                        st.error(f"Fallo critico al generar o exportar el boletin: {e}")
    else:
        st.info("Todavia no hay picks en la base para generar un boletin compartible.")

    st.markdown("---")
    with st.expander("Archivo historico (07_PICKSREALES)"):
        st.caption("Este bloque usa archivos historicos y no el flujo operativo actual de la base.")
        incluir_alt = st.checkbox("Incluir picks alternativos del archivo historico", value=True)

        if st.button("Generar PDF historico"):
            with st.spinner("Generando PDF historico..."):
                try:
                    datos = recopilar_todos_los_picks()
                    if not datos:
                        st.warning("No se encontraron partidos con picks en 07_PICKSREALES.")
                    else:
                        pdf_bytes = generar_pdf(datos, incluir_alt)
                        fecha = datetime.now().strftime("%Y%m%d_%H%M")
                        st.download_button(
                            "Descargar PDF historico",
                            data=pdf_bytes,
                            file_name=f"historico_picks_{fecha}.pdf",
                            mime="application/pdf",
                        )
                        st.success("PDF historico generado correctamente.")
                except Exception as e:
                    st.error(f"Error al generar el PDF historico: {e}")

    st.markdown("---")
    st.subheader("Base detallada de registros")
    pub_base_backend_error = False
    df = fetch_backend_picks(incluir_alternativas=True)
    if df is None:
        print("[BACKEND ERROR] picks | pub_base | no fallback")
        pub_base_backend_error = True
        df = normalize_backend_picks_df(pd.DataFrame())
    if pub_base_backend_error:
        st.warning("⚠️ Base detallada no disponible (backend no responde)")
    if not df.empty:
        base_cols = st.columns([1.1, 1.1, 1.4])
        tipo_filtro = base_cols[0].selectbox("Filtrar por tipo", ["Todos", "Principales", "Alternativas"])
        estado_base = base_cols[1].selectbox("Filtrar por estado", ["Todos", "Pendientes", "Cerrados"])
        busqueda_base = base_cols[2].text_input("Buscar en base", placeholder="Partido, mercado, IA...", key="base_busqueda")
        if tipo_filtro == "Principales":
            df_filtrado = df[df['tipo_pick'] == 'principal']
        elif tipo_filtro == "Alternativas":
            df_filtrado = df[df['tipo_pick'] == 'alternativa']
        else:
            df_filtrado = df
        if estado_base == "Pendientes":
            df_filtrado = df_filtrado[df_filtrado["resultado"] == "pendiente"]
        elif estado_base == "Cerrados":
            df_filtrado = df_filtrado[df_filtrado["resultado"] != "pendiente"]
        if busqueda_base.strip():
            patron = busqueda_base.strip().lower()
            df_filtrado = df_filtrado[
                df_filtrado["partido"].fillna("").astype(str).str.lower().str.contains(patron, na=False)
                | df_filtrado["mercado"].fillna("").astype(str).str.lower().str.contains(patron, na=False)
                | df_filtrado["ia"].fillna("").astype(str).str.lower().str.contains(patron, na=False)
            ]
        st.caption(f"Filas visibles en base: {len(df_filtrado)}")
        st.dataframe(df_filtrado, width='stretch')
        col1, col2 = st.columns(2)
        if col1.button("Exportar CSV"):
            csv = df_filtrado.to_csv(index=False)
            st.download_button("Descargar CSV", csv, "backtest_completo.csv", "text/csv")
        if col2.button("Borrar toda la base"):
            if st.checkbox("Confirmo que quiero borrar todo"):
                from database import delete_all_picks
                delete_all_picks()
                st.success("Base de datos reseteada")
                st.rerun()
    else:
        if pub_base_backend_error:
            st.info("Base no disponible temporalmente.")
        else:
            st.info("No hay datos disponibles. Carga picks para continuar.")

# ====================== PREPARAR PARTIDO ======================
with tab_operacion:
    st.subheader("Preparar Partido")
    st.markdown(
        "Automatiza la recoleccion previa del partido con **API-Football**, completa los campos "
        "que siguen siendo manuales y genera una ficha lista para el motor automatico."
    )
    fetched_status = fetch_backend_api_status()
    if fetched_status is not None:
        api_status = fetched_status
    else:
        api_status = "Conectada" if API_FOOTBALL_KEY else "Sin key"
    st.markdown(
        f"""
        <div style="background:radial-gradient(circle at top right, rgba(41,215,100,.12), transparent 34%), linear-gradient(135deg, #0d1523, #121a28 68%, #172437); border:1px solid rgba(255,255,255,.06); border-radius:28px; padding:22px 24px; margin-bottom:16px;">
            <div style="display:flex; justify-content:space-between; gap:18px; flex-wrap:wrap; align-items:flex-start;">
                <div>
                    <div style="display:inline-block; background:rgba(41,215,100,.10); color:#5bf089; border:1px solid rgba(59,226,111,.16); border-radius:999px; padding:7px 12px; font-size:11px; font-weight:800; letter-spacing:1px; text-transform:uppercase; margin-bottom:10px;">Centro de preparacion</div>
                    <div style="color:#f7f9fb; font-size:28px; font-weight:900; line-height:1.08;">Arma la ficha del partido antes del analisis</div>
                    <div style="color:#9fb0c5; font-size:15px; margin-top:8px;">Paso 1: localiza el fixture. Paso 2: completa lo manual y revisa faltantes. Paso 3: genera la ficha final.</div>
                </div>
                <div style="display:grid; grid-template-columns:repeat(2, minmax(140px, 1fr)); gap:10px; min-width:320px;">
                    <div style="background:rgba(255,255,255,.035); border:1px solid rgba(255,255,255,.06); border-radius:18px; padding:14px 16px;"><div style="color:#8fa1b9; font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:1px;">API</div><div style="color:#f7fbff; font-size:18px; font-weight:900; margin-top:6px;">{api_status}</div></div>
                    <div style="background:rgba(255,255,255,.035); border:1px solid rgba(255,255,255,.06); border-radius:18px; padding:14px 16px;"><div style="color:#8fa1b9; font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:1px;">Entrada</div><div style="color:#f7fbff; font-size:18px; font-weight:900; margin-top:6px;">Partido + fecha</div></div>
                    <div style="background:rgba(255,255,255,.035); border:1px solid rgba(255,255,255,.06); border-radius:18px; padding:14px 16px;"><div style="color:#8fa1b9; font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:1px;">Manual</div><div style="color:#f7fbff; font-size:18px; font-weight:900; margin-top:6px;">xG + ELO + contexto</div></div>
                    <div style="background:rgba(255,255,255,.035); border:1px solid rgba(255,255,255,.06); border-radius:18px; padding:14px 16px;"><div style="color:#8fa1b9; font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:1px;">Salida</div><div style="color:#f7fbff; font-size:18px; font-weight:900; margin-top:6px;">Ficha estructurada</div></div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if "prepared_match_data" not in st.session_state:
        st.session_state.prepared_match_data = None
    if "prepared_match_text" not in st.session_state:
        st.session_state.prepared_match_text = ""
    if "prepared_match_input" not in st.session_state:
        st.session_state.prepared_match_input = ""
    if "prepared_match_step" not in st.session_state:
        st.session_state.prepared_match_step = 1
    if "prepared_match_fixture_loaded" not in st.session_state:
        st.session_state.prepared_match_fixture_loaded = None
    if "prepared_match_manual_data" not in st.session_state:
        st.session_state.prepared_match_manual_data = {}
    if "prepared_match_last_data" not in st.session_state:
        st.session_state.prepared_match_last_data = None
    if "prepared_match_last_manual_data" not in st.session_state:
        st.session_state.prepared_match_last_manual_data = {}
    if "motor_pick_result" not in st.session_state:
        st.session_state.motor_pick_result = None
    if "motor_context_result" not in st.session_state:
        st.session_state.motor_context_result = None
    if "motor_last_log_id" not in st.session_state:
        st.session_state.motor_last_log_id = None

    step_actual = st.session_state.get("prepared_match_step", 1)
    st.caption("Pasos del flujo")
    step_cols = st.columns(4)
    if step_cols[0].button("1. Buscar fixture", use_container_width=True, type="primary" if step_actual == 1 else "secondary", key="prep_step_1"):
        st.session_state.prepared_match_step = 1
        st.rerun()
    if step_cols[1].button("2. Completar manual", use_container_width=True, type="primary" if step_actual == 2 else "secondary", key="prep_step_2"):
        st.session_state.prepared_match_step = 2
        st.rerun()
    if step_cols[2].button("3. Generar ficha", use_container_width=True, type="primary" if step_actual == 3 else "secondary", key="prep_step_3"):
        st.session_state.prepared_match_step = 3
        st.rerun()
    if step_cols[3].button("4. Motor propio", use_container_width=True, type="primary" if step_actual == 4 else "secondary", key="prep_step_4"):
        st.session_state.prepared_match_step = 4
        st.rerun()

    def _reset_prepared_widgets():
        prep_keys_to_reset = [
            "prep_data_editor",
            "prep_over25_local_fallback",
            "prep_over25_visit_fallback",
            "prep_btts_local_fallback",
            "prep_btts_visit_fallback",
            "prep_g_local_fallback",
            "prep_e_local_fallback",
            "prep_p_local_fallback",
            "prep_g_visit_fallback",
            "prep_e_visit_fallback",
            "prep_p_visit_fallback",
            "prep_pos_local_fallback",
            "prep_pos_visit_fallback",
            "prep_arbitro_manual",
            "prep_forma_local_manual",
            "prep_forma_visit_manual",
            "prep_h2h_manual",
            "prep_lesiones_local_manual",
            "prep_lesiones_visitante_manual",
            "prep_alineacion_local_manual",
            "prep_alineacion_visitante_manual",
            "prep_cuotas_manual_resumen",
            "prep_xg_local",
            "prep_xg_visitante",
            "prep_elo_local",
            "prep_elo_visitante",
            "prep_arbitro_cards_avg",
            "prep_prompt_perplexity",
            "prep_perplexity_resultado",
            "prep_motivacion_local",
            "prep_motivacion_visitante",
            "prep_contexto_extra",
        ]
        for clave_reset in prep_keys_to_reset:
            if clave_reset in st.session_state:
                del st.session_state[clave_reset]

    fecha_seleccionada = st.session_state.get("prep_fecha_seleccionada", datetime.now().astimezone().date())
    fecha_iso_seleccion = fecha_seleccionada.isoformat() if hasattr(fecha_seleccionada, "isoformat") else str(fecha_seleccionada)

    if step_actual == 1:
        st.markdown("### Partidos analizables por fecha")
        col_fecha1, col_fecha2, col_fecha3 = st.columns([1.2, 1, 1])
        with col_fecha1:
            fecha_seleccionada = st.date_input(
                "Fecha local",
                value=st.session_state.get("prep_fecha_seleccionada", datetime.now().astimezone().date()),
                min_value=datetime.now().astimezone().date(),
                max_value=(datetime.now().astimezone() + timedelta(days=7)).date(),
                key="prep_fecha_seleccionada",
            )
            fecha_iso_seleccion = fecha_seleccionada.isoformat()
        with col_fecha2:
            if st.button("Cargar partidos del dia", use_container_width=True, type="primary"):
                fetched = fetch_backend_partidos_por_fecha(fecha_iso_seleccion)
                if fetched is not None:
                    st.session_state.partidos_del_dia = fetched
                    st.session_state.prep_partidos_error = None
                else:
                    partidos_fecha, error_fecha = obtener_partidos_por_fecha_local(fecha_iso_seleccion, solo_futuros=True)
                    st.session_state.partidos_del_dia = partidos_fecha if not error_fecha else []
                    st.session_state.prep_partidos_error = error_fecha
                st.session_state.prep_fecha_cargada = fecha_iso_seleccion
                st.rerun()
        with col_fecha3:
            if st.button("Proximos 3 dias", use_container_width=True):
                partidos_proximos, error_prox = obtener_partidos_proximos_locales(dias_adelante=3)
                st.session_state.partidos_del_dia = partidos_proximos if not error_prox else []
                st.session_state.prep_partidos_error = error_prox
                st.session_state.prep_fecha_cargada = "__proximos__"
                st.rerun()

        fecha_cargada = st.session_state.get("prep_fecha_cargada")
        if fecha_cargada != fecha_iso_seleccion:
            fetched = fetch_backend_partidos_por_fecha(fecha_iso_seleccion)
            if fetched is not None:
                st.session_state.partidos_del_dia = fetched
                st.session_state.prep_partidos_error = None
            else:
                partidos_inicio, error_inicio = obtener_partidos_por_fecha_local(fecha_iso_seleccion, solo_futuros=True)
                st.session_state.partidos_del_dia = partidos_inicio if not error_inicio else []
                st.session_state.prep_partidos_error = error_inicio
            st.session_state.prep_fecha_cargada = fecha_iso_seleccion

        if "partidos_del_dia" not in st.session_state:
            fetched = fetch_backend_partidos_por_fecha(fecha_iso_seleccion)
            if fetched is not None:
                st.session_state.partidos_del_dia = fetched
                st.session_state.prep_partidos_error = None
            else:
                partidos_inicio, error_inicio = obtener_partidos_por_fecha_local(fecha_iso_seleccion, solo_futuros=True)
                st.session_state.partidos_del_dia = partidos_inicio if not error_inicio else []
                st.session_state.prep_partidos_error = error_inicio
            st.session_state.prep_fecha_cargada = fecha_iso_seleccion

        partidos_filtrados_fecha = st.session_state.get("partidos_del_dia", [])
        error_lista = st.session_state.get("prep_partidos_error")
        if error_lista and not partidos_filtrados_fecha:
            st.warning(f"No se pudo cargar la lista: {error_lista}")

        if partidos_filtrados_fecha:
            st.success(f"✓ {len(partidos_filtrados_fecha)} partidos disponibles para analizar")
            from collections import defaultdict
            partidos_por_liga = defaultdict(list)
            for p in partidos_filtrados_fecha:
                partidos_por_liga[p.get("liga", "Sin liga")].append(p)

            ligas_disponibles = ["Todas"] + sorted(partidos_por_liga.keys())
            liga_seleccionada = st.selectbox("Filtrar por liga", ligas_disponibles, key="prep_filtro_liga")
            partidos_filtrados = partidos_por_liga.get(liga_seleccionada, []) if liga_seleccionada != "Todas" else partidos_filtrados_fecha

            st.markdown("---")
            for i, partido in enumerate(partidos_filtrados):
                col_part_1, col_part_2 = st.columns([4, 1])
                with col_part_1:
                    st.markdown(
                        f"""
                        <div style="background: linear-gradient(135deg, rgba(20,28,40,0.9), rgba(15,22,32,0.95)); border: 1px solid rgba(255,255,255,0.06); border-radius: 16px; padding: 16px; margin-bottom: 10px;">
                            <div style="color: #7a8aa3; font-size: 12px; margin-bottom: 6px;">
                                {partido.get('liga', 'Sin liga')} • Por jugar
                            </div>
                            <div style="color: #c8d4e0; font-size: 16px; font-weight: 700;">
                                {partido.get('local', 'Local')} vs {partido.get('visitante', 'Visitante')}
                            </div>
                            <div style="color: #6a7a8d; font-size: 13px; margin-top: 4px;">
                                🕐 {partido.get('hora', '--:--')} (hora local)
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                with col_part_2:
                    if st.button("Seleccionar", key=f"sel_partido_{i}", use_container_width=True):
                        entrada_partido = f"{partido.get('local', '')} vs {partido.get('visitante', '')}"
                        with st.spinner("Consultando fixture, forma, H2H, tabla, lesiones, alineaciones y odds..."):
                            datos_prep, error_prep = preparar_partido_desde_api(
                                entrada_partido,
                                fecha_iso=fecha_seleccionada.isoformat(),
                            )
                        if error_prep:
                            st.error(f"No se pudo preparar el partido: {error_prep}")
                            st.session_state.prepared_match_data = None
                        else:
                            nuevo_fixture_id = datos_prep.get("fixture_id")
                            fixture_anterior = st.session_state.get("prepared_match_fixture_loaded")
                            if nuevo_fixture_id and nuevo_fixture_id != fixture_anterior:
                                _reset_prepared_widgets()
                            st.session_state.prepared_match_input = entrada_partido
                            st.session_state.prepared_match_data = datos_prep
                            st.session_state.prepared_match_fixture_loaded = nuevo_fixture_id
                            st.session_state.prepared_match_step = 2
                            st.success(f"✓ Partido cargado: {entrada_partido}")
                        st.rerun()
            st.markdown(f"Total: **{len(partidos_filtrados)}** partidos")
        else:
            st.info("No hay partidos pendientes para esa fecha local.")
    
    # Mantener el sistema antiguo por compatibilidad (entrada manual)
    with st.expander("🔧 Buscar partido manualmente (alternativo)"):
        st.markdown("Si no encuentra el partido en la lista, puede buscarlo manualmente:")
        entrada_partido = st.text_input(
            "Partido a preparar",
            value=st.session_state.get("prepared_match_input", ""),
            placeholder="Ej: Atletico Nacional vs Llaneros - 14/03/2026",
            key="prep_match_input_manual",
        )
        parsed_input = parsear_entrada_partido(entrada_partido)
        liga_detectada_key, liga_detectada_nombre = detectar_liga_automatica(parsed_input.get("partido", ""))

        col_p1, col_p2, col_p3 = st.columns([1.2, 1, 1])
        col_p1.text_input(
            "Liga detectada",
            value=liga_detectada_nombre or "Sin deteccion automatica",
            disabled=True,
            key="prep_liga_detectada",
        )
        fecha_manual = col_p2.text_input(
            "Fecha del partido",
            value=parsed_input.get("fecha", ""),
            placeholder="DD/MM/AAAA",
            key="prep_fecha_manual",
        )
        fecha_iso_manual = parsed_input.get("fecha_iso", "")
        if fecha_manual and fecha_manual != parsed_input.get("fecha", ""):
            try:
                fecha_iso_manual = datetime.strptime(fecha_manual, "%d/%m/%Y").strftime("%Y-%m-%d")
            except Exception:
                fecha_iso_manual = ""

                if not entrada_partido.strip():
                    st.warning("Escribe primero el nombre del partido (ej: Local vs Visitante).")
                else:
                    st.session_state.prepared_match_input = entrada_partido.strip()
                    with st.spinner("Consultando fixture, forma, H2H, tabla, lesiones, alineaciones y odds..."):
                        datos_prep, error_prep = preparar_partido_desde_api(
                            entrada_partido.strip(),
                            fecha_iso=fecha_iso_manual,
                            liga_key=liga_detectada_key,
                        )
                    if error_prep:
                        st.error(f"Fallo en la busqueda: {error_prep}")
                        st.info("Asegurate de que el nombre del equipo sea similar al oficial y la fecha sea correcta.")
                        st.session_state.prepared_match_data = None
                    else:
                        nuevo_fixture_id = datos_prep.get("fixture_id")
                        fixture_anterior = st.session_state.get("prepared_match_fixture_loaded")
                        if nuevo_fixture_id and nuevo_fixture_id != fixture_anterior:
                            _reset_prepared_widgets()
                        st.session_state.prepared_match_data = datos_prep
                        st.session_state.prepared_match_fixture_loaded = nuevo_fixture_id
                        st.session_state.prepared_match_step = 2
                        st.success(f"✓ Partido localizado: {datos_prep.get('partido', entrada_partido)}")
                    st.rerun()

    datos_preparados = st.session_state.get("prepared_match_data")
    if datos_preparados:
        st.markdown("---")
        _render_section_banner(
            "Revision de datos cargados",
            "Revisa primero la materia prima de la API. Luego corrige faltantes y completa lo manual antes de generar la ficha final.",
            "Revision",
        )
        step_actual = st.session_state.get("prepared_match_step", 2)
        st.subheader("Revision de datos cargados")
        col_v1, col_v2, col_v3, col_v4 = st.columns(4)
        col_v1.metric("Partido", datos_preparados.get("partido", "-"))
        col_v2.metric("Fecha", datos_preparados.get("fecha", "-"))
        col_v3.metric("Arbitro", datos_preparados.get("arbitro", "") or "Pendiente")
        col_v4.metric("Liga", datos_preparados.get("liga_nombre", "-"))

        home_api = datos_preparados.get("home", {})
        away_api = datos_preparados.get("away", {})

        st.markdown("### Estado de preparacion")
        debug_api = datos_preparados.get("debug_api", {})

        def _lineup_item_has_real_data(item):
            formacion = str((item or {}).get("formacion", "") or "").strip().lower()
            titulares = [str(x or "").strip() for x in (item or {}).get("titulares", []) if str(x or "").strip()]
            return bool((formacion and formacion != "none") or len(titulares) >= 6)

        def _lineups_have_real_data_ui(lineups):
            return any(_lineup_item_has_real_data(item) for item in (lineups or []))

        def _find_team_lineup_item(lineups, team_name):
            team_norm = str(team_name or "").strip().lower()
            for item in lineups or []:
                if str(item.get("equipo", "")).strip().lower() == team_norm:
                    return item
            return {}

        def _alineaciones_api_ok():
            lineups = datos_preparados.get("lineups", []) or []
            if lineups:
                home_item = _find_team_lineup_item(lineups, home_api.get("equipo", ""))
                away_item = _find_team_lineup_item(lineups, away_api.get("equipo", ""))
                return _lineup_item_has_real_data(home_item) and _lineup_item_has_real_data(away_item)
            info = debug_api.get("alineaciones", {}) or {}
            detalle = str(info.get("detalle", "") or "").strip().lower()
            if "sin formacion/titulares utiles" in detalle:
                return False
            return bool(info.get("ok"))

        def _estado_compuesto(*flags):
            flags = [bool(f) for f in flags]
            if flags and all(flags):
                return "Completo"
            if any(flags):
                return "Parcial"
            return "Sin dato"

        resumen_bloques = [
            ("Partido y fixture", _estado_compuesto(debug_api.get("fixture", {}).get("ok"), bool(datos_preparados.get("partido")))),
            ("Tabla y posiciones", _estado_compuesto(debug_api.get("tabla", {}).get("ok"))),
            ("Forma reciente", _estado_compuesto(debug_api.get("forma_local", {}).get("ok"), debug_api.get("forma_visitante", {}).get("ok"))),
            ("H2H", _estado_compuesto(debug_api.get("h2h", {}).get("ok"))),
            ("Arbitro", _estado_compuesto(bool(datos_preparados.get("arbitro")))),
            ("Lesiones", _estado_compuesto(debug_api.get("lesiones_local", {}).get("ok"), debug_api.get("lesiones_visitante", {}).get("ok"))),
            ("Alineaciones", _estado_compuesto(_alineaciones_api_ok())),
            ("Cuotas", _estado_compuesto(debug_api.get("odds", {}).get("ok"))),
        ]
        faltantes_api = [etiqueta for etiqueta, estado in resumen_bloques if estado != "Completo"]
        api_ok_count = sum(1 for _, estado in resumen_bloques if estado == "Completo")
        if step_actual == 2:
            if api_ok_count >= 6:
                st.info("La API ya cubre bastante. Siguiente paso recomendado: completar lo manual.")
            elif api_ok_count <= 3:
                st.warning("La cobertura API sigue floja. Revisa bien faltantes antes de continuar.")

        if step_actual >= 2:
            col_e1, col_e2 = st.columns(2)
            with col_e1:
                st.markdown("**Resumen real de lo que trajo la API**")
                api_ok_labels = [etiqueta for etiqueta, estado in resumen_bloques if estado == "Completo"]
                api_missing_labels = [f"{etiqueta} ({estado})" for etiqueta, estado in resumen_bloques if estado != "Completo"]
                st.success("La API si trajo: " + (", ".join(api_ok_labels) if api_ok_labels else "Nada"))
                if api_missing_labels:
                    st.warning("La API no trajo: " + ", ".join(api_missing_labels))
            with col_e2:
                st.markdown("**Campos que aun debes completar manualmente**")
                faltantes_accionables = [
                    "xG local",
                    "xG visitante",
                    "ELO local",
                    "ELO visitante",
                    "Promedio amarillas arbitro",
                    "Motivacion / contexto local",
                    "Motivacion / contexto visitante",
                    "Contexto adicional del partido",
                ]
                if debug_api.get("lesiones_local", {}).get("ok") is False:
                    faltantes_accionables.append("Lesiones / suspensiones local")
                if debug_api.get("lesiones_visitante", {}).get("ok") is False:
                    faltantes_accionables.append("Lesiones / suspensiones visitante")
                if not _alineaciones_api_ok():
                    faltantes_accionables.append("Alineacion probable local")
                    faltantes_accionables.append("Alineacion probable visitante")
                if not bool(datos_preparados.get("arbitro")):
                    faltantes_accionables.append("Arbitro")
                for item in faltantes_accionables:
                    st.write(f"- {item}")
                if faltantes_api:
                    st.warning("La API no encontro: " + ", ".join(faltantes_api))
                else:
                    st.success("La API encontro todos los bloques principales disponibles.")

        home_api_resuelto = dict(home_api)
        away_api_resuelto = dict(away_api)

        home_forma_txt = "\n".join(
            f"{item.get('fecha', '')} | vs {item.get('rival', '')} | {item.get('marcador', '')}"
            for item in home_api.get("forma", [])
        )
        away_forma_txt = "\n".join(
            f"{item.get('fecha', '')} | vs {item.get('rival', '')} | {item.get('marcador', '')}"
            for item in away_api.get("forma", [])
        )
        h2h_txt = "\n".join(
            f"{item.get('fecha', '')} | {item.get('partido', '')} | {item.get('marcador', '')}"
            for item in datos_preparados.get("h2h", [])
        )
        lesiones_local_api_txt = "\n".join(
            f"{item.get('jugador', '')} | {item.get('tipo', '')} | {item.get('razon', '')}"
            for item in home_api.get("lesiones", [])
        )
        lesiones_visit_api_txt = "\n".join(
            f"{item.get('jugador', '')} | {item.get('tipo', '')} | {item.get('razon', '')}"
            for item in away_api.get("lesiones", [])
        )
        lineups_api = datos_preparados.get("lineups", [])
        lineup_local_api_txt = ""
        lineup_visit_api_txt = ""
        home_norm = re.sub(r"\s+", " ", str(home_api.get("equipo", "")).strip().lower())
        away_norm = re.sub(r"\s+", " ", str(away_api.get("equipo", "")).strip().lower())
        for item in lineups_api:
            equipo_raw = str(item.get("equipo", "")).strip().lower()
            equipo_norm = re.sub(r"\s+", " ", equipo_raw)
            titulares = ", ".join([x for x in item.get("titulares", []) if x])
            formacion = str(item.get("formacion", "") or "").strip()
            if not formacion or formacion.lower() == "none":
                formacion = "Sin formacion confirmada"
            bloque = f"Formacion: {formacion}\nTitulares: {titulares or 'Sin titulares confirmados'}"
            if equipo_norm == home_norm:
                lineup_local_api_txt = bloque
            elif equipo_norm == away_norm:
                lineup_visit_api_txt = bloque
        if not lineup_local_api_txt and len(lineups_api) >= 1:
            item = lineups_api[0]
            titulares = ", ".join([x for x in item.get("titulares", []) if x])
            formacion = str(item.get("formacion", "") or "").strip() or "Sin formacion confirmada"
            lineup_local_api_txt = f"Formacion: {formacion}\nTitulares: {titulares or 'Sin titulares confirmados'}"
        if not lineup_visit_api_txt and len(lineups_api) >= 2:
            item = lineups_api[1]
            titulares = ", ".join([x for x in item.get("titulares", []) if x])
            formacion = str(item.get("formacion", "") or "").strip() or "Sin formacion confirmada"
            lineup_visit_api_txt = f"Formacion: {formacion}\nTitulares: {titulares or 'Sin titulares confirmados'}"
        odds_api_txt = ""
        resumen_odds_api = datos_preparados.get("odds", {}).get("resumen", {})
        odds_lines = []
        for mercado, items in resumen_odds_api.items():
            if not items:
                continue
            primero = items[0]
            valores = ", ".join(f"{v.get('value', '')} @ {v.get('odd', '')}" for v in primero.get("valores", [])[:6])
            odds_lines.append(f"{mercado} ({primero.get('bookmaker', '')}): {valores}")
        odds_api_txt = "\n".join(odds_lines)

        if debug_api:
            plan_limit_msgs = []
            debug_rows = []
            etiquetas_debug = {
                "fixture": "Fixture",
                "tabla": "Tabla",
                "stats_local": "Stats local",
                "stats_visitante": "Stats visitante",
                "forma_local": "Forma local",
                "forma_visitante": "Forma visitante",
                "h2h": "H2H",
                "lesiones_local": "Lesiones local",
                "lesiones_visitante": "Lesiones visitante",
                "alineaciones": "Alineaciones",
                "odds": "Odds",
            }
            for clave, info in debug_api.items():
                detalle = str(info.get("detalle", "") or "")
                estado_ok = bool(info.get("ok"))
                if clave == "alineaciones":
                    estado_ok = _alineaciones_api_ok()
                    if not estado_ok:
                        detalle = "Sin formacion/titulares utiles por ambos equipos"
                if "Free plans do not have access" in detalle:
                    plan_limit_msgs.append(f"{etiquetas_debug.get(clave, clave)}: {detalle}")
                debug_rows.append(
                    {
                        "Bloque": etiquetas_debug.get(clave, clave),
                        "Estado": "OK" if estado_ok else "Sin datos",
                        "Detalle": detalle,
                    }
                )
            if plan_limit_msgs:
                st.warning(
                    "Tu plan free de API-Football esta limitando varios bloques para esta temporada/consulta.\n\n"
                    + "\n".join(f"- {msg}" for msg in plan_limit_msgs)
                )
            with st.expander("Ver diagnostico tecnico API", expanded=False):
                st.dataframe(pd.DataFrame(resumen_bloques, columns=["Bloque", "Estado"]), width="stretch", hide_index=True)
                st.dataframe(pd.DataFrame(debug_rows), width="stretch", hide_index=True)
        df_api_original = pd.DataFrame(
            [
                {
                    "Equipo": home_api.get("equipo", ""),
                    "GF": _display_api_value(home_api.get("goles_favor", ""), zero_is_missing=True),
                    "GC": _display_api_value(home_api.get("goles_contra", ""), zero_is_missing=True),
                    "Over25%": _display_api_value(home_api.get("over25_pct", ""), zero_is_missing=True),
                    "BTTS%": _display_api_value(home_api.get("btts_pct", ""), zero_is_missing=True),
                    "Tiros puerta": _display_api_value(home_api.get("shots_on_goal", ""), zero_is_missing=True),
                    "Tiros totales": _display_api_value(home_api.get("shots_total", ""), zero_is_missing=True),
                    "Corners": _display_api_value(home_api.get("corners", ""), zero_is_missing=True),
                    "Posesion": _display_api_value(home_api.get("possession", ""), zero_is_missing=True),
                    "Amarillas": _display_api_value(home_api.get("yellow", ""), zero_is_missing=True),
                    "Rojas": _display_api_value(home_api.get("red", ""), zero_is_missing=True),
                    "Pos": _display_api_value(home_api.get("tabla", {}).get("pos", "")),
                    "Pts": _display_api_value(home_api.get("tabla", {}).get("puntos", "")),
                    "G": _display_api_value(home_api.get("tabla", {}).get("g", "")),
                    "E": _display_api_value(home_api.get("tabla", {}).get("e", "")),
                    "P": _display_api_value(home_api.get("tabla", {}).get("p", "")),
                },
                {
                    "Equipo": away_api.get("equipo", ""),
                    "GF": _display_api_value(away_api.get("goles_favor", ""), zero_is_missing=True),
                    "GC": _display_api_value(away_api.get("goles_contra", ""), zero_is_missing=True),
                    "Over25%": _display_api_value(away_api.get("over25_pct", ""), zero_is_missing=True),
                    "BTTS%": _display_api_value(away_api.get("btts_pct", ""), zero_is_missing=True),
                    "Tiros puerta": _display_api_value(away_api.get("shots_on_goal", ""), zero_is_missing=True),
                    "Tiros totales": _display_api_value(away_api.get("shots_total", ""), zero_is_missing=True),
                    "Corners": _display_api_value(away_api.get("corners", ""), zero_is_missing=True),
                    "Posesion": _display_api_value(away_api.get("possession", ""), zero_is_missing=True),
                    "Amarillas": _display_api_value(away_api.get("yellow", ""), zero_is_missing=True),
                    "Rojas": _display_api_value(away_api.get("red", ""), zero_is_missing=True),
                    "Pos": _display_api_value(away_api.get("tabla", {}).get("pos", "")),
                    "Pts": _display_api_value(away_api.get("tabla", {}).get("puntos", "")),
                    "G": _display_api_value(away_api.get("tabla", {}).get("g", "")),
                    "E": _display_api_value(away_api.get("tabla", {}).get("e", "")),
                    "P": _display_api_value(away_api.get("tabla", {}).get("p", "")),
                },
            ]
        )
        with st.expander("Ver detalle crudo de la API", expanded=False):
            st.dataframe(df_api_original, width="stretch", hide_index=True)

            api_tab1, api_tab2, api_tab3, api_tab4, api_tab5 = st.tabs(
                ["Forma API", "H2H API", "Lesiones API", "Alineaciones API", "Odds API"]
            )
            with api_tab1:
                col_f1, col_f2 = st.columns(2)
                col_f1.markdown(f"**{home_api.get('equipo', 'Local')}**")
                df_home_forma = pd.DataFrame(home_api.get("forma", []))
                if not df_home_forma.empty:
                    col_f1.dataframe(df_home_forma, width="stretch", hide_index=True)
                else:
                    col_f1.info("La API no trajo forma reciente para este equipo.")
                col_f2.markdown(f"**{away_api.get('equipo', 'Visitante')}**")
                df_away_forma = pd.DataFrame(away_api.get("forma", []))
                if not df_away_forma.empty:
                    col_f2.dataframe(df_away_forma, width="stretch", hide_index=True)
                else:
                    col_f2.info("La API no trajo forma reciente para este equipo.")
            with api_tab2:
                df_h2h = pd.DataFrame(datos_preparados.get("h2h", []))
                if not df_h2h.empty:
                    st.dataframe(df_h2h, width="stretch", hide_index=True)
                else:
                    st.info("La API no trajo H2H para este partido.")
            with api_tab3:
                col_i1, col_i2 = st.columns(2)
                col_i1.markdown(f"**{home_api.get('equipo', 'Local')}**")
                df_i1 = pd.DataFrame(home_api.get("lesiones", []))
                if not df_i1.empty:
                    col_i1.dataframe(df_i1, width="stretch", hide_index=True)
                else:
                    col_i1.info("La API no trajo lesiones para este equipo.")
                col_i2.markdown(f"**{away_api.get('equipo', 'Visitante')}**")
                df_i2 = pd.DataFrame(away_api.get("lesiones", []))
                if not df_i2.empty:
                    col_i2.dataframe(df_i2, width="stretch", hide_index=True)
                else:
                    col_i2.info("La API no trajo lesiones para este equipo.")
            with api_tab4:
                if lineups_api:
                    st.dataframe(pd.DataFrame(lineups_api), width="stretch", hide_index=True)
                else:
                    st.info("La API no trajo alineaciones para este partido.")
            with api_tab5:
                resumen_odds = datos_preparados.get("odds", {}).get("resumen", {})
                filas_odds = []
                for mercado, items in resumen_odds.items():
                    if not items:
                        filas_odds.append({"Mercado": mercado, "Bookmaker": "-", "Valores": "Sin datos"})
                        continue
                    primero = items[0]
                    valores = ", ".join(f"{v.get('value', '')} @ {v.get('odd', '')}" for v in primero.get("valores", [])[:6])
                    filas_odds.append({"Mercado": mercado, "Bookmaker": primero.get("bookmaker", ""), "Valores": valores})
                if filas_odds:
                    st.dataframe(pd.DataFrame(filas_odds), width="stretch", hide_index=True)
                else:
                    st.info("La API no trajo odds para este partido.")

        st.markdown("---")
        st.subheader("2. Editar o completar datos")
        st.caption("Por defecto solo deberias completar lo manual o lo que la API no trajo. Las sobreescrituras avanzadas quedan ocultas abajo.")
        mostrar_avanzado = st.toggle("Mostrar correcciones avanzadas de API", value=False, key="prep_toggle_avanzado")
        if mostrar_avanzado:
            st.markdown("**Metricas editables por equipo**")
        df_api_editor = pd.DataFrame(
                [
                    {
                        "Equipo": home_api.get("equipo", ""),
                        "GF": home_api_resuelto.get("goles_favor", ""),
                        "GC": home_api_resuelto.get("goles_contra", ""),
                        "Over25%": home_api_resuelto.get("over25_pct", ""),
                        "BTTS%": home_api_resuelto.get("btts_pct", ""),
                        "Tiros puerta": home_api_resuelto.get("shots_on_goal", ""),
                        "Tiros totales": home_api_resuelto.get("shots_total", ""),
                        "Corners": home_api_resuelto.get("corners", ""),
                        "Posesion": home_api_resuelto.get("possession", ""),
                        "Amarillas": home_api_resuelto.get("yellow", ""),
                        "Rojas": home_api_resuelto.get("red", ""),
                        "Pos": home_api_resuelto.get("tabla", {}).get("pos", ""),
                        "Pts": home_api_resuelto.get("tabla", {}).get("puntos", ""),
                        "G": home_api_resuelto.get("tabla", {}).get("g", ""),
                        "E": home_api_resuelto.get("tabla", {}).get("e", ""),
                        "P": home_api_resuelto.get("tabla", {}).get("p", ""),
                    },
                    {
                        "Equipo": away_api.get("equipo", ""),
                        "GF": away_api_resuelto.get("goles_favor", ""),
                        "GC": away_api_resuelto.get("goles_contra", ""),
                        "Over25%": away_api_resuelto.get("over25_pct", ""),
                        "BTTS%": away_api_resuelto.get("btts_pct", ""),
                        "Tiros puerta": away_api_resuelto.get("shots_on_goal", ""),
                        "Tiros totales": away_api_resuelto.get("shots_total", ""),
                        "Corners": away_api_resuelto.get("corners", ""),
                        "Posesion": away_api_resuelto.get("possession", ""),
                        "Amarillas": away_api_resuelto.get("yellow", ""),
                        "Rojas": away_api_resuelto.get("red", ""),
                        "Pos": away_api_resuelto.get("tabla", {}).get("pos", ""),
                        "Pts": away_api_resuelto.get("tabla", {}).get("puntos", ""),
                        "G": away_api_resuelto.get("tabla", {}).get("g", ""),
                        "E": away_api_resuelto.get("tabla", {}).get("e", ""),
                        "P": away_api_resuelto.get("tabla", {}).get("p", ""),
                    },
                ]
            )
        over25_local_fallback = ""
        over25_visit_fallback = ""
        btts_local_fallback = ""
        btts_visit_fallback = ""
        g_local_fallback = ""
        e_local_fallback = ""
        p_local_fallback = ""
        g_visit_fallback = ""
        e_visit_fallback = ""
        p_visit_fallback = ""
        posesion_local_fallback = ""
        posesion_visit_fallback = ""
        arbitro_manual = str(datos_preparados.get("arbitro", "") or "")
        forma_local_manual = home_forma_txt
        forma_visitante_manual = away_forma_txt
        h2h_manual = h2h_txt
        lesiones_local_manual = lesiones_local_api_txt
        lesiones_visitante_manual = lesiones_visit_api_txt
        alineacion_local_manual = lineup_local_api_txt
        alineacion_visitante_manual = lineup_visit_api_txt
        cuotas_manual_resumen = odds_api_txt
        faltan_lesiones = not (debug_api.get("lesiones_local", {}).get("ok") and debug_api.get("lesiones_visitante", {}).get("ok"))
        faltan_alineaciones = not _alineaciones_api_ok()
        faltan_arbitro = not bool((arbitro_manual or "").strip())

        if mostrar_avanzado:
            df_api_editor = st.data_editor(
                df_api_editor,
                width="stretch",
                hide_index=True,
                key="prep_data_editor",
                disabled=["Equipo"],
                use_container_width=True,
            )

            st.markdown("**Sobreescrituras avanzadas**")
            col_fx1, col_fx2 = st.columns(2)
            over25_local_fallback = col_fx1.text_input("Over 2.5 local (%)", key="prep_over25_local_fallback", placeholder="Ej: 62.5")
            over25_visit_fallback = col_fx2.text_input("Over 2.5 visitante (%)", key="prep_over25_visit_fallback", placeholder="Ej: 48.0")
            col_fx3, col_fx4 = st.columns(2)
            btts_local_fallback = col_fx3.text_input("BTTS local (%)", key="prep_btts_local_fallback", placeholder="Ej: 54.0")
            btts_visit_fallback = col_fx4.text_input("BTTS visitante (%)", key="prep_btts_visit_fallback", placeholder="Ej: 44.0")
            st.caption("G / E / P")
            col_gep1, col_gep2, col_gep3 = st.columns(3)
            g_local_fallback = col_gep1.text_input("G local", key="prep_g_local_fallback", placeholder="Ej: 7")
            e_local_fallback = col_gep2.text_input("E local", key="prep_e_local_fallback", placeholder="Ej: 2")
            p_local_fallback = col_gep3.text_input("P local", key="prep_p_local_fallback", placeholder="Ej: 1")
            col_gep4, col_gep5, col_gep6 = st.columns(3)
            g_visit_fallback = col_gep4.text_input("G visitante", key="prep_g_visit_fallback", placeholder="Ej: 4")
            e_visit_fallback = col_gep5.text_input("E visitante", key="prep_e_visit_fallback", placeholder="Ej: 3")
            p_visit_fallback = col_gep6.text_input("P visitante", key="prep_p_visit_fallback", placeholder="Ej: 3")
            col_pos1, col_pos2 = st.columns(2)
            posesion_local_fallback = col_pos1.text_input("Posesion local (%)", key="prep_pos_local_fallback", placeholder="Ej: 54.3")
            posesion_visit_fallback = col_pos2.text_input("Posesion visitante (%)", key="prep_pos_visit_fallback", placeholder="Ej: 48.9")
            arbitro_manual = st.text_input("Arbitro", key="prep_arbitro_manual", value=arbitro_manual, placeholder="Ej: Andres Rojas")
            col_form1, col_form2 = st.columns(2)
            forma_local_manual = col_form1.text_area(f"Forma reciente {home_api.get('equipo', 'Local')}", key="prep_forma_local_manual", value=forma_local_manual, height=130, placeholder="Fecha | Rival | Marcador")
            forma_visitante_manual = col_form2.text_area(f"Forma reciente {away_api.get('equipo', 'Visitante')}", key="prep_forma_visit_manual", value=forma_visitante_manual, height=130, placeholder="Fecha | Rival | Marcador")
            h2h_manual = st.text_area("H2H ultimos enfrentamientos", key="prep_h2h_manual", value=h2h_manual, height=120, placeholder="Fecha | Partido | Marcador")
            col_les1, col_les2 = st.columns(2)
            lesiones_local_manual = col_les1.text_area("Lesiones / suspensiones local", key="prep_lesiones_local_manual", value=lesiones_local_manual, height=90, placeholder="Jugadores ausentes o suspensiones")
            lesiones_visitante_manual = col_les2.text_area("Lesiones / suspensiones visitante", key="prep_lesiones_visitante_manual", value=lesiones_visitante_manual, height=90, placeholder="Jugadores ausentes o suspensiones")
            col_al1, col_al2 = st.columns(2)
            alineacion_local_manual = col_al1.text_area("Alineacion probable local", key="prep_alineacion_local_manual", value=alineacion_local_manual, height=90, placeholder="Formacion y titulares probables")
            alineacion_visitante_manual = col_al2.text_area("Alineacion probable visitante", key="prep_alineacion_visitante_manual", value=alineacion_visitante_manual, height=90, placeholder="Formacion y titulares probables")
            cuotas_manual_resumen = st.text_area("Cuotas / resumen de mercado", key="prep_cuotas_manual_resumen", value=cuotas_manual_resumen, height=120, placeholder="Ej: 1X2 Bet365: Local 1.80, Empate 3.40, Visitante 4.90")
        else:
            st.markdown("**Solo faltantes detectados**")
            if faltan_arbitro:
                arbitro_manual = st.text_input("Arbitro", key="prep_arbitro_manual", value=arbitro_manual, placeholder="Ej: Andres Rojas")
            if faltan_lesiones:
                col_les1, col_les2 = st.columns(2)
                lesiones_local_manual = col_les1.text_area("Lesiones / suspensiones local", key="prep_lesiones_local_manual", value=lesiones_local_manual, height=90, placeholder="Jugadores ausentes o suspensiones")
                lesiones_visitante_manual = col_les2.text_area("Lesiones / suspensiones visitante", key="prep_lesiones_visitante_manual", value=lesiones_visitante_manual, height=90, placeholder="Jugadores ausentes o suspensiones")
            if faltan_alineaciones:
                col_al1, col_al2 = st.columns(2)
                alineacion_local_manual = col_al1.text_area("Alineacion probable local", key="prep_alineacion_local_manual", value=alineacion_local_manual, height=90, placeholder="Formacion y titulares probables")
                alineacion_visitante_manual = col_al2.text_area("Alineacion probable visitante", key="prep_alineacion_visitante_manual", value=alineacion_visitante_manual, height=90, placeholder="Formacion y titulares probables")
            if not any([faltan_arbitro, faltan_lesiones, faltan_alineaciones]):
                st.caption("No hay faltantes principales de API en esta seccion. Solo completa xG, ELO, arbitro/tarjetas y contexto.")

        if isinstance(df_api_editor, pd.DataFrame) and len(df_api_editor) >= 2:
            home_row = df_api_editor.iloc[0].to_dict()
            away_row = df_api_editor.iloc[1].to_dict()
            home_api_resuelto["goles_favor"] = _clean_editor_value(home_row.get("GF"), home_api_resuelto.get("goles_favor", ""))
            home_api_resuelto["goles_contra"] = _clean_editor_value(home_row.get("GC"), home_api_resuelto.get("goles_contra", ""))
            home_api_resuelto["over25_pct"] = _clean_editor_value(home_row.get("Over25%"), home_api_resuelto.get("over25_pct", ""))
            home_api_resuelto["btts_pct"] = _clean_editor_value(home_row.get("BTTS%"), home_api_resuelto.get("btts_pct", ""))
            home_api_resuelto["shots_on_goal"] = _clean_editor_value(home_row.get("Tiros puerta"), home_api_resuelto.get("shots_on_goal", ""))
            home_api_resuelto["shots_total"] = _clean_editor_value(home_row.get("Tiros totales"), home_api_resuelto.get("shots_total", ""))
            home_api_resuelto["corners"] = _clean_editor_value(home_row.get("Corners"), home_api_resuelto.get("corners", ""))
            home_api_resuelto["possession"] = _clean_editor_value(home_row.get("Posesion"), home_api_resuelto.get("possession", ""))
            home_api_resuelto["yellow"] = _clean_editor_value(home_row.get("Amarillas"), home_api_resuelto.get("yellow", ""))
            home_api_resuelto["red"] = _clean_editor_value(home_row.get("Rojas"), home_api_resuelto.get("red", ""))
            away_api_resuelto["goles_favor"] = _clean_editor_value(away_row.get("GF"), away_api_resuelto.get("goles_favor", ""))
            away_api_resuelto["goles_contra"] = _clean_editor_value(away_row.get("GC"), away_api_resuelto.get("goles_contra", ""))
            away_api_resuelto["over25_pct"] = _clean_editor_value(away_row.get("Over25%"), away_api_resuelto.get("over25_pct", ""))
            away_api_resuelto["btts_pct"] = _clean_editor_value(away_row.get("BTTS%"), away_api_resuelto.get("btts_pct", ""))
            away_api_resuelto["shots_on_goal"] = _clean_editor_value(away_row.get("Tiros puerta"), away_api_resuelto.get("shots_on_goal", ""))
            away_api_resuelto["shots_total"] = _clean_editor_value(away_row.get("Tiros totales"), away_api_resuelto.get("shots_total", ""))
            away_api_resuelto["corners"] = _clean_editor_value(away_row.get("Corners"), away_api_resuelto.get("corners", ""))
            away_api_resuelto["possession"] = _clean_editor_value(away_row.get("Posesion"), away_api_resuelto.get("possession", ""))
            away_api_resuelto["yellow"] = _clean_editor_value(away_row.get("Amarillas"), away_api_resuelto.get("yellow", ""))
            away_api_resuelto["red"] = _clean_editor_value(away_row.get("Rojas"), away_api_resuelto.get("red", ""))
            home_api_resuelto["tabla"] = dict(home_api_resuelto.get("tabla", {}))
            away_api_resuelto["tabla"] = dict(away_api_resuelto.get("tabla", {}))
            home_api_resuelto["tabla"]["pos"] = _clean_editor_value(home_row.get("Pos"), home_api_resuelto["tabla"].get("pos", ""))
            home_api_resuelto["tabla"]["puntos"] = _clean_editor_value(home_row.get("Pts"), home_api_resuelto["tabla"].get("puntos", ""))
            home_api_resuelto["tabla"]["g"] = _clean_editor_value(home_row.get("G"), home_api_resuelto["tabla"].get("g", ""))
            home_api_resuelto["tabla"]["e"] = _clean_editor_value(home_row.get("E"), home_api_resuelto["tabla"].get("e", ""))
            home_api_resuelto["tabla"]["p"] = _clean_editor_value(home_row.get("P"), home_api_resuelto["tabla"].get("p", ""))
            away_api_resuelto["tabla"]["pos"] = _clean_editor_value(away_row.get("Pos"), away_api_resuelto["tabla"].get("pos", ""))
            away_api_resuelto["tabla"]["puntos"] = _clean_editor_value(away_row.get("Pts"), away_api_resuelto["tabla"].get("puntos", ""))
            away_api_resuelto["tabla"]["g"] = _clean_editor_value(away_row.get("G"), away_api_resuelto["tabla"].get("g", ""))
            away_api_resuelto["tabla"]["e"] = _clean_editor_value(away_row.get("E"), away_api_resuelto["tabla"].get("e", ""))
            away_api_resuelto["tabla"]["p"] = _clean_editor_value(away_row.get("P"), away_api_resuelto["tabla"].get("p", ""))

        home_api_resuelto["over25_pct"] = _resolver_valor(home_api_resuelto.get("over25_pct"), over25_local_fallback, zero_is_missing=True)
        away_api_resuelto["over25_pct"] = _resolver_valor(away_api_resuelto.get("over25_pct"), over25_visit_fallback, zero_is_missing=True)
        home_api_resuelto["btts_pct"] = _resolver_valor(home_api_resuelto.get("btts_pct"), btts_local_fallback, zero_is_missing=True)
        away_api_resuelto["btts_pct"] = _resolver_valor(away_api_resuelto.get("btts_pct"), btts_visit_fallback, zero_is_missing=True)
        home_api_resuelto["possession"] = _resolver_valor(home_api_resuelto.get("possession"), posesion_local_fallback, zero_is_missing=True)
        away_api_resuelto["possession"] = _resolver_valor(away_api_resuelto.get("possession"), posesion_visit_fallback, zero_is_missing=True)
        home_api_resuelto["tabla"] = dict(home_api_resuelto.get("tabla", {}))
        away_api_resuelto["tabla"] = dict(away_api_resuelto.get("tabla", {}))
        home_api_resuelto["tabla"]["g"] = _resolver_valor(home_api_resuelto.get("tabla", {}).get("g"), g_local_fallback)
        home_api_resuelto["tabla"]["e"] = _resolver_valor(home_api_resuelto.get("tabla", {}).get("e"), e_local_fallback)
        home_api_resuelto["tabla"]["p"] = _resolver_valor(home_api_resuelto.get("tabla", {}).get("p"), p_local_fallback)
        away_api_resuelto["tabla"]["g"] = _resolver_valor(away_api_resuelto.get("tabla", {}).get("g"), g_visit_fallback)
        away_api_resuelto["tabla"]["e"] = _resolver_valor(away_api_resuelto.get("tabla", {}).get("e"), e_visit_fallback)
        away_api_resuelto["tabla"]["p"] = _resolver_valor(away_api_resuelto.get("tabla", {}).get("p"), p_visit_fallback)

        if step_actual >= 2:
            with st.expander("Ver ficha tecnica consolidada", expanded=False):
                st.caption("Asi quedaria la ficha despues de tus correcciones manuales")
                df_api = pd.DataFrame(
                    [
                        {
                            "Equipo": home_api_resuelto.get("equipo", ""),
                            "GF": home_api_resuelto.get("goles_favor", 0),
                            "GC": home_api_resuelto.get("goles_contra", 0),
                            "% Over 2.5": home_api_resuelto.get("over25_pct", 0),
                            "% BTTS": home_api_resuelto.get("btts_pct", 0),
                            "Tiros puerta": home_api_resuelto.get("shots_on_goal", 0),
                            "Tiros totales": home_api_resuelto.get("shots_total", 0),
                            "Corners": home_api_resuelto.get("corners", 0),
                            "Posesion": home_api_resuelto.get("possession", 0),
                            "Amarillas": home_api_resuelto.get("yellow", 0),
                            "Rojas": home_api_resuelto.get("red", 0),
                            "Pos": home_api_resuelto.get("tabla", {}).get("pos", ""),
                            "Pts": home_api_resuelto.get("tabla", {}).get("puntos", ""),
                            "G/E/P": f"{home_api_resuelto.get('tabla', {}).get('g', '')}/{home_api_resuelto.get('tabla', {}).get('e', '')}/{home_api_resuelto.get('tabla', {}).get('p', '')}",
                        },
                        {
                            "Equipo": away_api_resuelto.get("equipo", ""),
                            "GF": away_api_resuelto.get("goles_favor", 0),
                            "GC": away_api_resuelto.get("goles_contra", 0),
                            "% Over 2.5": away_api_resuelto.get("over25_pct", 0),
                            "% BTTS": away_api_resuelto.get("btts_pct", 0),
                            "Tiros puerta": away_api_resuelto.get("shots_on_goal", 0),
                            "Tiros totales": away_api_resuelto.get("shots_total", 0),
                            "Corners": away_api_resuelto.get("corners", 0),
                            "Posesion": away_api_resuelto.get("possession", 0),
                            "Amarillas": away_api_resuelto.get("yellow", 0),
                            "Rojas": away_api_resuelto.get("red", 0),
                            "Pos": away_api_resuelto.get("tabla", {}).get("pos", ""),
                            "Pts": away_api_resuelto.get("tabla", {}).get("puntos", ""),
                            "G/E/P": f"{away_api_resuelto.get('tabla', {}).get('g', '')}/{away_api_resuelto.get('tabla', {}).get('e', '')}/{away_api_resuelto.get('tabla', {}).get('p', '')}",
                        },
                    ]
                )
                st.dataframe(df_api, width="stretch")

                verif_tab1, verif_tab2, verif_tab3, verif_tab4 = st.tabs(["Forma final", "H2H final", "Lesiones final", "Odds final"])
                with verif_tab1:
                    col_f1, col_f2 = st.columns(2)
                    col_f1.markdown(f"**{home_api.get('equipo', 'Local')}**")
                    df_home_forma = pd.DataFrame(home_api.get("forma", []))
                    if not df_home_forma.empty:
                        col_f1.dataframe(df_home_forma, width="stretch")
                    else:
                        col_f1.info("Sin forma reciente disponible")
                    col_f2.markdown(f"**{away_api.get('equipo', 'Visitante')}**")
                    df_away_forma = pd.DataFrame(away_api.get("forma", []))
                    if not df_away_forma.empty:
                        col_f2.dataframe(df_away_forma, width="stretch")
                    else:
                        col_f2.info("Sin forma reciente disponible")
                with verif_tab2:
                    df_h2h = pd.DataFrame(datos_preparados.get("h2h", []))
                    if not df_h2h.empty:
                        st.dataframe(df_h2h, width="stretch")
                    else:
                        st.info("Sin H2H disponible")
                with verif_tab3:
                    col_i1, col_i2 = st.columns(2)
                    col_i1.markdown(f"**{home_api.get('equipo', 'Local')}**")
                    df_i1 = pd.DataFrame(home_api.get("lesiones", []))
                    if not df_i1.empty:
                        col_i1.dataframe(df_i1, width="stretch")
                    else:
                        col_i1.info("Sin bajas registradas")
                    col_i2.markdown(f"**{away_api.get('equipo', 'Visitante')}**")
                    df_i2 = pd.DataFrame(away_api.get("lesiones", []))
                    if not df_i2.empty:
                        col_i2.dataframe(df_i2, width="stretch")
                    else:
                        col_i2.info("Sin bajas registradas")
                with verif_tab4:
                    resumen_odds = datos_preparados.get("odds", {}).get("resumen", {})
                    filas_odds = []
                    for mercado, items in resumen_odds.items():
                        if not items:
                            filas_odds.append({"Mercado": mercado, "Bookmaker": "-", "Valores": "Sin datos"})
                            continue
                    primero = items[0]
                    valores = ", ".join(f"{v.get('value', '')} @ {v.get('odd', '')}" for v in primero.get("valores", [])[:6])
                    filas_odds.append({"Mercado": mercado, "Bookmaker": primero.get("bookmaker", ""), "Valores": valores})
                st.dataframe(pd.DataFrame(filas_odds), width="stretch")

        if step_actual >= 2:
            st.markdown("---")
            st.subheader("Campos manuales que completan los 8 sistemas")
        col_m1, col_m2 = st.columns(2)
        xg_local = col_m1.text_input("xG local", key="prep_xg_local", placeholder="Ej: 1.62")
        xg_visitante = col_m2.text_input("xG visitante", key="prep_xg_visitante", placeholder="Ej: 0.94")
        col_m3, col_m4 = st.columns(2)
        elo_local = col_m3.text_input("ELO local", key="prep_elo_local", placeholder="Ej: 1642")
        elo_visitante = col_m4.text_input("ELO visitante", key="prep_elo_visitante", placeholder="Ej: 1510")
        promedio_tarjetas_arbitro = st.text_input(
            "Promedio amarillas arbitro (manual)",
            key="prep_arbitro_cards_avg",
            placeholder="Ej: 5.4",
            help="Usalo si quieres ponderar mejor mercados de tarjetas o tension del partido.",
        )
        st.markdown("### Contexto externo para Perplexity")
        prompt_perplexity = (
            f"Analiza el partido {datos_preparados.get('partido', '')} del {datos_preparados.get('fecha', '')} en "
            f"{datos_preparados.get('liga_nombre', '')}. No quiero pick ni prediccion, solo contexto reciente y verificable.\n\n"
            "Devuelveme en espanol y de forma concreta:\n"
            "1. Situacion competitiva real de ambos equipos.\n"
            "2. Si es eliminatoria, fase, ida o vuelta y marcador global o de ida si aplica.\n"
            "3. Que necesita cada equipo en este partido.\n"
            "4. Lesiones, suspensiones, rotaciones o dudas recientes importantes.\n"
            "5. Noticias de ultima hora que cambien el contexto.\n"
            "6. Perfil relevante del arbitro si influye en tension o tarjetas.\n"
            "7. Un resumen final del contexto del local y otro del visitante.\n\n"
            "No inventes nada. Si algo no lo encuentras, dilo explicitamente."
        )
        st.text_area(
            "Prompt personalizado para Perplexity",
            value=prompt_perplexity,
            key="prep_prompt_perplexity",
            height=210,
            help="Copialo y pegalo directo en Perplexity para pedir el contexto del partido que elegiste.",
        )
        respuesta_perplexity = st.text_area(
            "Resultado pegado desde Perplexity",
            key="prep_perplexity_resultado",
            height=180,
            placeholder="Pega aqui la respuesta de Perplexity para enriquecer el contexto del partido.",
        )
        col_px1, col_px2 = st.columns([1.1, 1])
        if col_px1.button("Usar respuesta de Perplexity como contexto base", use_container_width=True):
            if str(st.session_state.get("prep_perplexity_resultado", "")).strip():
                st.session_state.prep_contexto_extra = st.session_state.get("prep_perplexity_resultado", "").strip()
                st.success("La respuesta de Perplexity se copio al contexto adicional.")
                st.rerun()
            else:
                st.warning("Primero pega la respuesta de Perplexity.")
        col_px2.caption("Luego Ollama puede procesar este bloque para sugerir mejor motivacion y contexto.")
        st.caption("Si no quieres redactar el contexto a mano, puedes pedirle a Ollama local que te lo sugiera con lo que ya trae la ficha.")
        ctx_auto_1, ctx_auto_2 = st.columns([1.2, 1])
        if ctx_auto_1.button("Autocompletar contexto con Ollama", use_container_width=True):
            contexto_fuente = "\n".join(
                [
                    f"Partido: {datos_preparados.get('partido', '')}",
                    f"Fecha: {datos_preparados.get('fecha', '')}",
                    f"Liga: {datos_preparados.get('liga_nombre', '')}",
                    f"Arbitro: {arbitro_manual or datos_preparados.get('arbitro', '')}",
                    f"Promedio tarjetas arbitro: {promedio_tarjetas_arbitro}",
                    f"Forma local: {forma_local_manual or str(home_api_resuelto.get('forma', []))}",
                    f"Forma visitante: {forma_visitante_manual or str(away_api_resuelto.get('forma', []))}",
                    f"H2H: {h2h_manual or str(datos_preparados.get('h2h', []))}",
                    f"Lesiones local: {lesiones_local_manual or str(home_api_resuelto.get('lesiones', []))}",
                    f"Lesiones visitante: {lesiones_visitante_manual or str(away_api_resuelto.get('lesiones', []))}",
                    f"Alineacion local: {alineacion_local_manual or str((datos_preparados.get('lineups') or {}).get('home', ''))}",
                    f"Alineacion visitante: {alineacion_visitante_manual or str((datos_preparados.get('lineups') or {}).get('away', ''))}",
                    f"Contexto externo Perplexity: {st.session_state.get('prep_perplexity_resultado', '')}",
                ]
            ).strip()
            sugerencia_ctx, error_ctx = sugerir_campos_contexto_ollama(contexto_fuente)
            if error_ctx:
                st.warning(error_ctx)
            elif sugerencia_ctx:
                st.session_state.prep_motivacion_local = sugerencia_ctx.get("motivacion_local", "")
                st.session_state.prep_motivacion_visitante = sugerencia_ctx.get("motivacion_visitante", "")
                st.session_state.prep_contexto_extra = sugerencia_ctx.get("contexto_adicional", "")
                st.success("Contexto sugerido por Ollama cargado en los campos.")
                st.rerun()
        if ctx_auto_2.button("Limpiar contexto sugerido", use_container_width=True):
            st.session_state.prep_motivacion_local = ""
            st.session_state.prep_motivacion_visitante = ""
            st.session_state.prep_contexto_extra = ""
            st.rerun()
        motivacion_local = st.text_area("Motivacion / contexto local", key="prep_motivacion_local", height=90)
        motivacion_visitante = st.text_area("Motivacion / contexto visitante", key="prep_motivacion_visitante", height=90)
        contexto_extra = st.text_area("Contexto adicional del partido", key="prep_contexto_extra", height=90)

        manual_data = {
            "xg_local": xg_local,
            "xg_visitante": xg_visitante,
            "elo_local": elo_local,
            "elo_visitante": elo_visitante,
            "promedio_tarjetas_arbitro": promedio_tarjetas_arbitro,
            "contexto_perplexity": st.session_state.get("prep_perplexity_resultado", ""),
            "motivacion_local": motivacion_local,
            "motivacion_visitante": motivacion_visitante,
            "contexto_extra": contexto_extra,
            "forma_local_manual": forma_local_manual,
            "forma_visitante_manual": forma_visitante_manual,
            "h2h_manual": h2h_manual,
            "over25_local_fallback": over25_local_fallback,
            "over25_visit_fallback": over25_visit_fallback,
            "btts_local_fallback": btts_local_fallback,
            "btts_visit_fallback": btts_visit_fallback,
            "g_local_fallback": g_local_fallback,
            "e_local_fallback": e_local_fallback,
            "p_local_fallback": p_local_fallback,
            "g_visit_fallback": g_visit_fallback,
            "e_visit_fallback": e_visit_fallback,
            "p_visit_fallback": p_visit_fallback,
            "posesion_local_fallback": posesion_local_fallback,
            "posesion_visit_fallback": posesion_visit_fallback,
            "arbitro_manual": arbitro_manual,
            "lesiones_local_manual": lesiones_local_manual,
            "lesiones_visitante_manual": lesiones_visitante_manual,
            "alineacion_local_manual": alineacion_local_manual,
            "alineacion_visitante_manual": alineacion_visitante_manual,
            "cuotas_manual_resumen": cuotas_manual_resumen,
        }

        contexto_fuente_prep = "\n".join(
            [
                f"Partido: {datos_preparados.get('partido', '')}",
                f"Fecha: {datos_preparados.get('fecha', '')}",
                f"Liga: {datos_preparados.get('liga_nombre', '')}",
                f"Arbitro: {arbitro_manual or datos_preparados.get('arbitro', '')}",
                f"Promedio tarjetas arbitro: {promedio_tarjetas_arbitro}",
                f"Forma local: {forma_local_manual or str(home_api_resuelto.get('forma', []))}",
                f"Forma visitante: {forma_visitante_manual or str(away_api_resuelto.get('forma', []))}",
                f"H2H: {h2h_manual or str(datos_preparados.get('h2h', []))}",
                f"Lesiones local: {lesiones_local_manual or str(home_api_resuelto.get('lesiones', []))}",
                f"Lesiones visitante: {lesiones_visitante_manual or str(away_api_resuelto.get('lesiones', []))}",
                f"Alineacion local: {alineacion_local_manual or str((datos_preparados.get('lineups') or {}).get('home', ''))}",
                f"Alineacion visitante: {alineacion_visitante_manual or str((datos_preparados.get('lineups') or {}).get('away', ''))}",
                f"Contexto externo Perplexity: {st.session_state.get('prep_perplexity_resultado', '')}",
            ]
        ).strip()

        completos_manual = sum(
            1 for clave, valor in manual_data.items() if not clave.endswith("_fallback") and str(valor or "").strip()
        )
        if step_actual == 2 and completos_manual >= 4:
            st.success("Ya tienes buena base manual. Puedes pasar a generar la ficha.")
        col_c_manual_1, col_c_manual_2 = st.columns(2)
        col_c_manual_1.metric("Campos manuales completados", f"{completos_manual}/7")
        col_c_manual_2.metric("Campos manuales pendientes", f"{7 - completos_manual}/7")

        with st.expander("Ver checklist manual"):
            checklist = [
                ("xG local", xg_local),
                ("xG visitante", xg_visitante),
                ("ELO local", elo_local),
                ("ELO visitante", elo_visitante),
                ("Motivacion local", motivacion_local),
                ("Motivacion visitante", motivacion_visitante),
                ("Contexto adicional", contexto_extra),
            ]
            for etiqueta, valor in checklist:
                st.write(f"{'OK' if str(valor or '').strip() else '-'} {etiqueta}")

        if step_actual >= 3:
            st.markdown("---")
            st.subheader("Mapa de cobertura del analisis")
        api_odds = datos_preparados.get("odds", {}).get("resumen", {})
        cobertura_rows = [
            {
                "Campo": "Goles anotados por partido",
                "Fuente": "API",
                "Estado": _estado_campo(home_api.get("goles_favor"), zero_is_missing=True) if _estado_campo(away_api.get("goles_favor"), zero_is_missing=True) == "Completo" else "Pendiente",
                "Sistema": "Poisson / Dixon-Coles",
            },
            {
                "Campo": "Goles recibidos por partido",
                "Fuente": "API",
                "Estado": _estado_campo(home_api.get("goles_contra"), zero_is_missing=True) if _estado_campo(away_api.get("goles_contra"), zero_is_missing=True) == "Completo" else "Pendiente",
                "Sistema": "Poisson / Dixon-Coles",
            },
            {
                "Campo": "% Over 2.5",
                "Fuente": "API",
                "Estado": "Completo" if (home_api_resuelto.get("over25_pct") or away_api_resuelto.get("over25_pct")) else "Pendiente",
                "Sistema": "Apoyo mercado goles",
            },
            {
                "Campo": "% BTTS",
                "Fuente": "API",
                "Estado": "Completo" if (home_api_resuelto.get("btts_pct") or away_api_resuelto.get("btts_pct")) else "Pendiente",
                "Sistema": "Apoyo BTTS",
            },
            {
                "Campo": "Ultimos 5 partidos",
                "Fuente": "API",
                "Estado": "Completo" if home_api.get("forma") and away_api.get("forma") else "Pendiente",
                "Sistema": "Forma ponderada",
            },
            {
                "Campo": "H2H ultimos 5",
                "Fuente": "API",
                "Estado": "Completo" if datos_preparados.get("h2h") else "Pendiente",
                "Sistema": "Forma / apoyo historico",
            },
            {
                "Campo": "Posicion actual",
                "Fuente": "API",
                "Estado": "Completo" if home_api.get("tabla", {}).get("pos") and away_api.get("tabla", {}).get("pos") else "Pendiente",
                "Sistema": "Contexto competitivo",
            },
            {
                "Campo": "Puntos",
                "Fuente": "API",
                "Estado": "Completo" if home_api.get("tabla", {}).get("puntos") and away_api.get("tabla", {}).get("puntos") else "Pendiente",
                "Sistema": "Contexto competitivo",
            },
            {
                "Campo": "Partidos jugados",
                "Fuente": "API",
                "Estado": "Completo" if home_api.get("tabla", {}).get("pj") and away_api.get("tabla", {}).get("pj") else "Pendiente",
                "Sistema": "Contexto competitivo",
            },
            {
                "Campo": "G / E / P",
                "Fuente": "API",
                "Estado": "Completo" if home_api_resuelto.get("tabla", {}).get("g") not in ("", None) and away_api_resuelto.get("tabla", {}).get("g") not in ("", None) else "Pendiente",
                "Sistema": "Forma estructural",
            },
            {
                "Campo": "Tiros a puerta",
                "Fuente": "API",
                "Estado": "Completo" if home_api.get("shots_on_goal") or away_api.get("shots_on_goal") else "Pendiente",
                "Sistema": "Mercados secundarios / apoyo xG",
            },
            {
                "Campo": "Tiros totales",
                "Fuente": "API",
                "Estado": "Completo" if home_api.get("shots_total") or away_api.get("shots_total") else "Pendiente",
                "Sistema": "Mercados secundarios / apoyo xG",
            },
            {
                "Campo": "Corners",
                "Fuente": "API",
                "Estado": "Completo" if home_api.get("corners") or away_api.get("corners") else "Pendiente",
                "Sistema": "Mercados secundarios",
            },
            {
                "Campo": "Tarjetas amarillas y rojas",
                "Fuente": "API",
                "Estado": "Completo" if home_api.get("yellow") or away_api.get("yellow") or home_api.get("red") or away_api.get("red") else "Pendiente",
                "Sistema": "Mercados secundarios",
            },
            {
                "Campo": "Posesion",
                "Fuente": "API",
                "Estado": "Completo" if (home_api_resuelto.get("possession") or away_api_resuelto.get("possession")) else "Pendiente",
                "Sistema": "Apoyo contextual",
            },
            {
                "Campo": "Faltas",
                "Fuente": "API",
                "Estado": "Completo" if home_api.get("fouls") or away_api.get("fouls") else "Pendiente",
                "Sistema": "Tarjetas / contexto",
            },
            {
                "Campo": "Cuotas 1X2",
                "Fuente": "API",
                "Estado": "Completo" if (api_odds.get("1X2") or cuotas_manual_resumen.strip()) else "Pendiente",
                "Sistema": "Mercado eficiente / arbitraje",
            },
            {
                "Campo": "Cuotas Over/Under 2.5",
                "Fuente": "API",
                "Estado": "Completo" if (api_odds.get("Over/Under") or cuotas_manual_resumen.strip()) else "Pendiente",
                "Sistema": "Mercado eficiente / arbitraje",
            },
            {
                "Campo": "Cuotas BTTS",
                "Fuente": "API",
                "Estado": "Completo" if (api_odds.get("BTTS") or cuotas_manual_resumen.strip()) else "Pendiente",
                "Sistema": "Mercado eficiente / arbitraje",
            },
            {
                "Campo": "Handicap asiatico",
                "Fuente": "API",
                "Estado": "Completo" if (api_odds.get("Handicap") or cuotas_manual_resumen.strip()) else "Pendiente",
                "Sistema": "Arbitraje de lineas",
            },
            {
                "Campo": "Cuotas corners",
                "Fuente": "API",
                "Estado": "Completo" if (api_odds.get("Corners") or cuotas_manual_resumen.strip()) else "Pendiente",
                "Sistema": "Mercados secundarios",
            },
            {
                "Campo": "Cuotas tarjetas",
                "Fuente": "API",
                "Estado": "Completo" if (api_odds.get("Tarjetas") or cuotas_manual_resumen.strip()) else "Pendiente",
                "Sistema": "Mercados secundarios",
            },
            {
                "Campo": "Alineaciones probables",
                "Fuente": "API",
                "Estado": "Completo" if (_alineaciones_api_ok() or alineacion_local_manual.strip() or alineacion_visitante_manual.strip()) else "Pendiente",
                "Sistema": "Motivacion / contexto",
            },
            {
                "Campo": "Lesiones y suspensiones",
                "Fuente": "API",
                "Estado": "Completo" if (home_api.get("lesiones") or away_api.get("lesiones") or lesiones_local_manual.strip() or lesiones_visitante_manual.strip()) else "Pendiente",
                "Sistema": "Motivacion / contexto",
            },
            {
                "Campo": "Arbitro",
                "Fuente": "API",
                "Estado": "Completo" if (datos_preparados.get("arbitro") or arbitro_manual.strip()) else "Pendiente",
                "Sistema": "Tarjetas / contexto",
            },
            {
                "Campo": "xG local",
                "Fuente": "Manual",
                "Estado": _estado_campo(xg_local),
                "Sistema": "Regresion xG",
            },
            {
                "Campo": "xG visitante",
                "Fuente": "Manual",
                "Estado": _estado_campo(xg_visitante),
                "Sistema": "Regresion xG",
            },
            {
                "Campo": "ELO local",
                "Fuente": "Manual",
                "Estado": _estado_campo(elo_local),
                "Sistema": "ELO Rating",
            },
            {
                "Campo": "ELO visitante",
                "Fuente": "Manual",
                "Estado": _estado_campo(elo_visitante),
                "Sistema": "ELO Rating",
            },
            {
                "Campo": "Motivacion local",
                "Fuente": "Manual",
                "Estado": _estado_campo(motivacion_local),
                "Sistema": "Motivacion cuantificada",
            },
            {
                "Campo": "Motivacion visitante",
                "Fuente": "Manual",
                "Estado": _estado_campo(motivacion_visitante),
                "Sistema": "Motivacion cuantificada",
            },
        ]
        df_cobertura = pd.DataFrame(cobertura_rows)
        completos_totales = int((df_cobertura["Estado"] == "Completo").sum())
        pendientes_totales = int((df_cobertura["Estado"] == "Pendiente").sum())
        cobertura_pct = (completos_totales / max(1, len(df_cobertura))) * 100
        if step_actual < 3 and cobertura_pct >= 70:
            st.info("La cobertura ya esta alta. Puedes entrar al paso 3 para generar la ficha final.")
        if step_actual >= 3:
            st.dataframe(df_cobertura, width="stretch")
            col_cov1, col_cov2, col_cov3 = st.columns(3)
            col_cov1.metric("Campos cubiertos", completos_totales)
            col_cov2.metric("Campos pendientes", pendientes_totales)
            col_cov3.metric("Cobertura actual", f"{cobertura_pct:.0f}%")
            st.progress(int(cobertura_pct))

            with st.expander("Ver solo pendientes"):
                st.dataframe(df_cobertura[df_cobertura["Estado"] == "Pendiente"], width="stretch")

            col_g1, col_g2 = st.columns([1.2, 1])
            if col_g1.button("Generar ficha estructurada", use_container_width=True):
                # Validacion preventiva de campos manuales
                if not xg_local.strip() or not xg_visitante.strip():
                    st.warning("Faltan datos de xG (Expected Goals). Son vitales para el motor Poisson.")
                elif not elo_local.strip() or not elo_visitante.strip():
                    st.warning("Faltan datos de ELO Rating. Son necesarios para el sistema 1.")
                elif not str(motivacion_local or "").strip() and not str(motivacion_visitante or "").strip() and not str(contexto_extra or "").strip():
                    st.info("Intentando autocompletar contexto con Ollama antes de generar...")
                    sugerencia_auto, error_auto = sugerir_campos_contexto_ollama(contexto_fuente_prep)
                    if sugerencia_auto and not error_auto:
                        motivacion_local = sugerencia_auto.get("motivacion_local", "")
                        motivacion_visitante = sugerencia_auto.get("motivacion_visitante", "")
                        contexto_extra = sugerencia_auto.get("contexto_adicional", "")
                        st.session_state.prep_motivacion_local = motivacion_local
                        st.session_state.prep_motivacion_visitante = motivacion_visitante
                        st.session_state.prep_contexto_extra = contexto_extra
                        st.success("Contexto autocompletado.")
                    else:
                        st.error("No se pudo autocompletar el contexto. Por favor, redacta brevemente la motivacion de los equipos.")
                        st.stop()
                
                with st.spinner("Construyendo ficha final operativa..."):
                    datos_ficha = dict(datos_preparados)
                    datos_ficha["home"] = home_api_resuelto
                    datos_ficha["away"] = away_api_resuelto
                    manual_data["motivacion_local"] = motivacion_local
                    manual_data["motivacion_visitante"] = motivacion_visitante
                    manual_data["contexto_extra"] = contexto_extra
                    manual_data["contexto_libre"] = "\n".join(
                        [x for x in [motivacion_local, motivacion_visitante, contexto_extra] if str(x or "").strip()]
                    ).strip()
                    ficha_generada = construir_ficha_preparada(datos_ficha, manual_data)
                    st.session_state.prepared_match_manual_data = dict(manual_data)
                    st.session_state.prepared_match_last_manual_data = dict(manual_data)
                    st.session_state.prepared_match_last_data = dict(datos_preparados)
                    st.session_state.prepared_match_text = ficha_generada
                    st.session_state.prompt_auto = ficha_generada
                    save_prepared_match(
                        datos_preparados.get("partido", ""),
                        datos_preparados.get("fecha", ""),
                        datos_preparados.get("liga_nombre", ""),
                        round(cobertura_pct, 2),
                        ficha_generada,
                    )
                st.success("✓ Ficha generada y guardada. Listo para el analisis del Motor Propio.")
                st.session_state.prepared_match_step = 4
                st.rerun()

            if col_g2.button("Limpiar partido preparado", use_container_width=True):
                _reset_prepared_widgets()
                st.session_state.prepared_match_data = None
                st.session_state.prepared_match_fixture_loaded = None
                st.session_state.prepared_match_manual_data = {}
                st.session_state.prepared_match_last_data = None
                st.session_state.prepared_match_last_manual_data = {}
                st.session_state.prepared_match_text = ""
                st.session_state.prepared_match_step = 1
                st.session_state.motor_pick_result = None
                st.session_state.motor_context_result = None
                st.rerun()

            if st.session_state.get("prepared_match_text"):
                st.markdown("---")
                st.subheader("Ficha final del partido")
                st.text_area(
                    "Vista previa de la ficha estructurada",
                    value=st.session_state.get("prepared_match_text", ""),
                    height=420,
                    key="prepared_match_preview",
                )
                if st.button("Cargar esta ficha en Analisis Automatico", use_container_width=True):
                    st.session_state.prompt_auto = st.session_state.get("prepared_match_text", "")
                    st.success("Ficha cargada. Ahora ve a Analisis Automatico y ejecuta el motor.")

            st.markdown("---")
            st.subheader("Historial de fichas preparadas")
            historial_preparado = get_prepared_matches(limit=12)
            if historial_preparado.empty:
                st.info("Aun no has guardado fichas preparadas.")
            else:
                for _, fila_hist in historial_preparado.iterrows():
                    titulo_hist = f"{fila_hist.get('partido', '')} | {fila_hist.get('fecha', '')}"
                    chip_hist = f"{fila_hist.get('liga', '') or 'Sin liga'} | Cobertura {float(fila_hist.get('cobertura', 0) or 0):.0f}%"
                    with st.expander(titulo_hist, expanded=False):
                        st.caption(chip_hist)
                        st.text_area(
                            "Ficha guardada",
                            value=str(fila_hist.get("ficha_texto", "") or ""),
                            height=220,
                            key=f"prepared_history_{fila_hist.get('id')}",
                        )
                        if st.button("Usar esta ficha en Analisis Automatico", key=f"use_prepared_{fila_hist.get('id')}", use_container_width=True):
                            st.session_state.prepared_match_text = str(fila_hist.get("ficha_texto", "") or "")
                            st.session_state.prompt_auto = st.session_state.prepared_match_text
                            st.success("Ficha historica cargada en Analisis Automatico.")

        # ====================== PASO 4: MOTOR PROPIO (integrado) ======================
        if step_actual >= 4:
            st.markdown("---")
            _render_section_banner(
                "Motor propio",
                "Ejecuta el motor matematico propio para que el pick salga del sistema y no de IAs externas.",
                "Motor Core",
            )
            st.subheader("Motor de picks autonomo")
            st.markdown(
                "Esta capa usa **Poisson, Dixon-Coles, ELO, forma ponderada y mercado eficiente**. "
                "La idea es que el cerebro principal del pick viva aqui y las IAs queden solo para redactar."
            )

            datos_motor = st.session_state.get("prepared_match_data") or st.session_state.get("prepared_match_last_data")
            if not datos_motor:
                st.info("Genera la ficha en el Paso 3 para poder correr el motor propio.")
            else:
                manual_preparado = _collect_prepared_manual_bridge()
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Partido", datos_motor.get("partido", "-"))
                m2.metric("Fecha", datos_motor.get("fecha", "-"))
                m3.metric("Liga", datos_motor.get("liga_nombre", "-"))
                m4.metric("Fixture", datos_motor.get("fixture_id", "-"))

                st.caption("El motor toma los datos del Paso 2. Aqui puedes revisar, ajustar o reforzar antes de ejecutarlo.")
                resumen_cols = st.columns(4)
                resumen_cols[0].metric("xG listos", sum(1 for v in [manual_preparado.get("xg_local"), manual_preparado.get("xg_visitante")] if str(v or "").strip()), "/2")
                resumen_cols[1].metric("ELO listos", sum(1 for v in [manual_preparado.get("elo_local"), manual_preparado.get("elo_visitante")] if str(v or "").strip()), "/2")
                resumen_cols[2].metric("Contexto listo", "Si" if any(str(manual_preparado.get(k) or "").strip() for k in ["motivacion_local", "motivacion_visitante", "contexto_extra"]) else "No")
                resumen_cols[3].metric("Odds API", "Si" if datos_motor.get("odds", {}).get("resumen") else "No")

                st.markdown("### Entradas manuales que usa el motor")
                c1, c2 = st.columns(2)
                xg_local_motor = c1.text_input(
                    "xG local",
                    value=str(manual_preparado.get("xg_local", "") or ""),
                    key="motor_xg_local",
                    placeholder="Ej: 1.62",
                )
                xg_visit_motor = c2.text_input(
                    "xG visitante",
                    value=str(manual_preparado.get("xg_visitante", "") or ""),
                    key="motor_xg_visitante",
                    placeholder="Ej: 0.94",
                )
                c3, c4 = st.columns(2)
                elo_local_motor = c3.text_input(
                    "ELO local",
                    value=str(manual_preparado.get("elo_local", "") or ""),
                    key="motor_elo_local",
                    placeholder="Ej: 1642",
                )
                elo_visit_motor = c4.text_input(
                    "ELO visitante",
                    value=str(manual_preparado.get("elo_visitante", "") or ""),
                    key="motor_elo_visitante",
                    placeholder="Ej: 1510",
                )
                contexto_motor = st.text_area(
                    "Contexto libre",
                    value=str(manual_preparado.get("contexto_libre", "") or ""),
                    key="motor_contexto_libre",
                    height=100,
                    placeholder="Lesiones, motivacion, noticias o rotaciones. Si tienes Ollama local, puedes estructurarlo aqui mismo.",
                )
                col_ctx1, col_ctx2 = st.columns([1.2, 1])
                if col_ctx1.button("Analizar contexto con Ollama", use_container_width=True):
                    contexto_json, error_ctx = analizar_contexto_ollama(contexto_motor)
                    if error_ctx:
                        st.warning(error_ctx)
                        st.session_state.motor_context_result = None
                    else:
                        st.session_state.motor_context_result = contexto_json
                        st.success("Contexto analizado con Ollama local.")
                if col_ctx2.button("Limpiar contexto estructurado", use_container_width=True):
                    st.session_state.motor_context_result = None
                    st.rerun()

                contexto_estructurado = st.session_state.get("motor_context_result")
                if contexto_estructurado:
                    st.markdown("### Contexto estructurado")
                    st.json(contexto_estructurado)

                manual_motor = {
                    "xg_local": xg_local_motor,
                    "xg_visitante": xg_visit_motor,
                    "elo_local": elo_local_motor,
                    "elo_visitante": elo_visit_motor,
                    "promedio_tarjetas_arbitro": str(manual_preparado.get("promedio_tarjetas_arbitro", "") or ""),
                    "contexto_perplexity": str(manual_preparado.get("contexto_perplexity", "") or ""),
                    "contexto_libre": contexto_motor,
                    "contexto_ollama": contexto_estructurado,
                }

                if st.button("Ejecutar motor propio", type="primary", use_container_width=True):
                    st.session_state.prepared_match_manual_data = {
                        **manual_preparado,
                        "xg_local": xg_local_motor,
                        "xg_visitante": xg_visit_motor,
                        "elo_local": elo_local_motor,
                        "elo_visitante": elo_visit_motor,
                        "promedio_tarjetas_arbitro": str(manual_preparado.get("promedio_tarjetas_arbitro", "") or ""),
                        "motivacion_local": str(manual_preparado.get("motivacion_local", "") or ""),
                        "motivacion_visitante": str(manual_preparado.get("motivacion_visitante", "") or ""),
                        "contexto_extra": str(manual_preparado.get("contexto_extra", "") or ""),
                        "contexto_libre": contexto_motor,
                        "contexto_perplexity": str(manual_preparado.get("contexto_perplexity", "") or ""),
                    }
                    st.session_state.motor_pick_result = analizar_partido_motor(datos_motor, manual_motor)
                    st.session_state.motor_last_log_id = save_motor_pick_log(
                        st.session_state.motor_pick_result,
                        datos_motor=datos_motor,
                        manual_data=manual_motor,
                        saved_to_picks=False,
                        saved_batch=None,
                    )

                resultado_motor = st.session_state.get("motor_pick_result")
                if resultado_motor:
                    pick_motor = resultado_motor.get("pick", {})
                    consenso_motor = resultado_motor.get("consenso", {})
                    prob_motor = resultado_motor.get("probabilidad_final", {})
                    decision_motor = resultado_motor.get("decision_motor", {})
                    calidad_input = resultado_motor.get("calidad_input", {})
                    favorito_estructural = resultado_motor.get("favorito_estructural", {})
                    motor_log_id = st.session_state.get("motor_last_log_id")
                    st.markdown("---")
                    st.subheader("Resumen del motor")
                    if motor_log_id:
                        st.caption(f"Log de motor guardado: #{motor_log_id}")
                    rm1, rm2, rm3, rm4, rm5 = st.columns(5)
                    rm1.metric("Sistemas a favor", f"{consenso_motor.get('sistemas_a_favor', 0)}/{consenso_motor.get('sistemas_total', 0)}")
                    rm2.metric("No disponibles", consenso_motor.get("sistemas_no_disponibles", 0))
                    rm3.metric("Prob. final", f"{prob_motor.get('final', 0)*100:.1f}%")
                    rm4.metric("Confianza", f"{pick_motor.get('confianza', 0)*100:.1f}%")
                    rm5.metric("Calidad input", f"{int(calidad_input.get('score', 0) or 0)}/100")

                    pm1, pm2, pm3, pm4, pm5 = st.columns(5)
                    pm1.metric("Mercado", pick_motor.get("mercado", "-") or "-")
                    pm2.metric("Seleccion", pick_motor.get("seleccion", "-") or "-")
                    pm3.metric("Cuota", f"{pick_motor.get('cuota', 0):.2f}")
                    pm4.metric("EV", f"{pick_motor.get('valor_esperado', 0)*100:.1f}%")
                    pm5.metric("Stake", pick_motor.get("stake_recomendado", "NO BET"))

                    if pick_motor.get("emitido"):
                        st.success(pick_motor.get("razonamiento", "Pick emitido por el motor propio."))
                    else:
                        st.warning(pick_motor.get("razonamiento", "El motor no emitio pick."))

                    decision_cols = st.columns([1.15, 1, 1])
                    with decision_cols[0]:
                        st.markdown("### Decision")
                        st.write(f"**Estado:** {decision_motor.get('decision', 'NO BET')}")
                        for motivo in decision_motor.get("motivos_clave", []):
                            st.write(f"- {motivo}")
                    with decision_cols[1]:
                        st.markdown("### Bloqueos")
                        bloqueos = decision_motor.get("bloqueos", [])
                        if bloqueos:
                            for bloqueo in bloqueos:
                                st.write(f"- {bloqueo}")
                        else:
                            st.write("- Sin bloqueos duros")
                    with decision_cols[2]:
                        st.markdown("### Entrada usada")
                        entrada = resultado_motor.get("entrada_utilizada", {})
                        datos_base = entrada.get("datos_base", {})
                        manuales = entrada.get("manuales", {})
                        st.write(f"- Goles base: {datos_base.get('goles_local', 'faltante')} / {datos_base.get('goles_visitante', 'faltante')}")
                        st.write(f"- Forma: {datos_base.get('forma_local', 'faltante')} / {datos_base.get('forma_visitante', 'faltante')}")
                        st.write(f"- xG: {manuales.get('xg_local', 'faltante')} / {manuales.get('xg_visitante', 'faltante')}")
                        st.write(f"- ELO: {manuales.get('elo_local', 'faltante')} / {manuales.get('elo_visitante', 'faltante')}")
                        st.write(f"- Contexto: {manuales.get('contexto_estructurado', 'faltante')}")
                        st.write(f"- Favorito estructural: {str(favorito_estructural.get('dominante', 'parejo')).title()}")

                    with st.expander("Ver calidad del input"):
                        st.write(f"Nivel: **{str(calidad_input.get('nivel', 'baja')).title()}**")
                        bloques = calidad_input.get("bloques", {})
                        if bloques:
                            filas_calidad = [{"Bloque": k, "Puntos": v} for k, v in bloques.items()]
                            st.dataframe(pd.DataFrame(filas_calidad), width="stretch", hide_index=True)
                        st.write(
                            f"Senal estructural -> Local: {favorito_estructural.get('score_local', 0)} | "
                            f"Visitante: {favorito_estructural.get('score_visitante', 0)}"
                        )

                    sistemas_rows = []
                    for nombre_sistema, detalle in resultado_motor.get("sistemas", {}).items():
                        fila = {
                            "Sistema": nombre_sistema,
                            "Veredicto": detalle.get("veredicto", ""),
                        }
                        for clave, valor in detalle.items():
                            if clave != "veredicto":
                                fila[clave] = "-" if valor is None else valor
                        sistemas_rows.append(fila)
                    st.markdown("### Lectura por sistema")
                    st.caption("`-` significa que ese dato no aplica para ese sistema especifico. No es necesariamente un error.")
                    st.dataframe(pd.DataFrame(sistemas_rows), width="stretch", hide_index=True)

                    candidatos_motor = resultado_motor.get("candidatos", [])
                    if candidatos_motor:
                        st.markdown("### Mercados evaluados por el motor")
                        filas_candidatos = []
                        for item in candidatos_motor:
                            filas_candidatos.append(
                                {
                                    "Mercado": item.get("mercado", ""),
                                    "Seleccion": item.get("seleccion", ""),
                                    "Cuota": item.get("cuota", 0),
                                    "Prob. modelo": round((item.get("prob_modelo", 0) or 0) * 100, 1),
                                    "Prob. calibrada": round((item.get("prob_calibrada", item.get("prob_modelo", 0)) or 0) * 100, 1),
                                    "Prob. implicita": round((item.get("prob_implicita", 0) or 0) * 100, 1),
                                    "EV %": round((item.get("ev", 0) or 0) * 100, 1),
                                    "EV calibrado %": round((item.get("ev_calibrado", item.get("ev", 0)) or 0) * 100, 1),
                                    "Sistemas a favor": item.get("sistemas_a_favor", 0),
                                    "Fit mercado": round((item.get("market_fit_score", 0) or 0) * 100, 1),
                                    "Shrink %": round((item.get("shrink_factor", 0) or 0) * 100, 1),
                                    "Empirico %": round((item.get("empirical_adjustment", 0) or 0) * 100, 1),
                                    "Muestra emp.": item.get("empirical_sample", 0),
                                    "Penalizacion": round((item.get("guardrail_penalty", 0) or 0) * 100, 1),
                                    "Score": item.get("score_candidato", 0),
                                    "Score ajustado": item.get("score_ajustado", 0),
                                }
                            )
                        st.dataframe(pd.DataFrame(filas_candidatos), width="stretch", hide_index=True)

                    if resultado_motor.get("riesgos"):
                        st.markdown("### Riesgos")
                        for riesgo in resultado_motor.get("riesgos", []):
                            st.write(f"- {riesgo}")

                    if resultado_motor.get("datos_insuficientes"):
                        st.markdown("### Datos insuficientes")
                        st.write(", ".join(resultado_motor.get("datos_insuficientes", [])))

                    with st.expander("Ver salida tecnica del motor"):
                        st.json(resultado_motor)

                    if pick_motor.get("emitido"):
                        pick_motor_publicable = {
                            "partido": resultado_motor.get("partido", ""),
                            "mercado": pick_motor.get("mercado", ""),
                            "seleccion": pick_motor.get("seleccion", ""),
                            "cuota": float(pick_motor.get("cuota", 0) or 0),
                            "confianza": float(pick_motor.get("confianza", 0) or 0),
                            "analisis_breve": pick_motor.get("razonamiento", ""),
                            "competicion": datos_motor.get("liga_nombre", ""),
                            "ia": "Motor-Propio",
                        }
                        st.markdown("### Publicacion del motor")
                        from pdf_generator import generar_pdf_pick_social
                        from services.telegram_service import telegram_config_ok, enviar_paquete_telegram
                        copy_motor = _copy_pick_social(
                            pick_motor_publicable,
                            pick_motor.get("razonamiento", ""),
                            int(float(pick_motor.get("confianza", 0) or 0) * 100),
                            float(pick_motor.get("cuota", 0) or 0),
                        )
                        pdf_motor_social = generar_pdf_pick_social(pick_motor_publicable)
                        pub1, pub2, pub3 = st.columns(3)
                        pub1.download_button(
                            "Descargar copy",
                            copy_motor,
                            file_name=f"motor_pick_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                            mime="text/plain",
                            use_container_width=True,
                        )
                        pub2.download_button(
                            "Descargar PDF social",
                            pdf_motor_social,
                            file_name=f"motor_pick_social_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                            mime="application/pdf",
                            use_container_width=True,
                        )
                        if telegram_config_ok():
                            if pub3.button("Enviar pack a Telegram", use_container_width=True):
                                ok, mensaje = enviar_paquete_telegram(
                                    copy_motor,
                                    pdf_motor_social,
                                    f"motor_pick_social_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                                    caption=f"Motor propio | {pick_motor_publicable.get('partido', '')}",
                                )
                                if ok:
                                    st.success(mensaje)
                                else:
                                    st.error(mensaje)
                        else:
                            pub3.caption("Telegram no configurado")

                        if st.button("Guardar pick del motor en la base", use_container_width=True):
                            df_motor = pd.DataFrame([
                                {
                                    "fecha": resultado_motor.get("fecha", datetime.now().strftime("%Y-%m-%d")),
                                    "partido": resultado_motor.get("partido", ""),
                                    "ia": "Motor-Propio",
                                    "mercado": pick_motor.get("mercado", ""),
                                    "seleccion": pick_motor.get("seleccion", ""),
                                    "cuota": float(pick_motor.get("cuota", 0) or 0),
                                    "confianza": float(pick_motor.get("confianza", 0) or 0),
                                    "analisis_breve": pick_motor.get("razonamiento", ""),
                                    "competicion": datos_motor.get("liga_nombre", ""),
                                    "tipo_pick": "principal",
                                }
                            ])
                            batch_motor = f"motor_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                            resultado_save = save_picks(df_motor, batch_motor)
                            insertados = resultado_save.get("insertados", 0)
                            duplicados = resultado_save.get("duplicados", 0)
                            save_motor_pick_log(
                                resultado_motor,
                                datos_motor=datos_motor,
                                manual_data=manual_motor,
                                saved_to_picks=True,
                                saved_batch=batch_motor,
                            )
                            auto_pub = _enviar_pick_telegram_si_activo(pick_motor_publicable)
                            mensaje_extra = ""
                            if auto_pub:
                                ok_pub, detalle_pub = auto_pub
                                mensaje_extra = f" | Telegram: {detalle_pub}"
                            st.success(f"Motor guardado. Insertados: {insertados} | Duplicados: {duplicados} | batch: {batch_motor}{mensaje_extra}")


                    st.markdown("---")
                    with st.expander("🤖 Validación Cruzada Multi-IA (Sólo consulta)", expanded=False):
                        st.markdown(
                            "Consulta la opinión de **3 analistas automáticos** configurados con perfiles distintos. "
                            "El Motor Propio sigue siendo la única fuente oficial de decisión; esto es solo contraste."
                        )
                        try:
                            from services.ai_analysis import ejecutar_analisis_automatico, verificar_apis_configuradas, PERSONALIDADES
                        except ImportError:
                            st.error("No se encontró services/ai_analysis.py.")
                            st.stop()
                        
                        st.markdown("### Pega aquí el análisis del Investigador (Perplexity)")
                        
                        valor_contexto = ""
                        try:
                            if "contexto_motor" in locals() or "contexto_motor" in globals():
                                valor_contexto = contexto_motor
                        except: pass
                        
                        if "prompt_auto_operacion" not in st.session_state:
                            st.session_state.prompt_auto_operacion = valor_contexto
                            
                        prompt_investigador = st.text_area(
                            "Análisis base",
                            value=st.session_state.prompt_auto_operacion,
                            height=200,
                            key="prompt_auto_operacion_input"
                        )
                        
                        if "auto_resultados_op" not in st.session_state:
                            st.session_state.auto_resultados_op = None
                        
                        if st.button("Ejecutar validación con IAs", type="secondary"):
                            if not prompt_investigador.strip():
                                st.warning("Carga el análisis base primero.")
                            else:
                                prompt_base = cargar_prompt_automatico()
                                prompt_final = prompt_base.replace(
                                    "[resumen compacto del investigador]",
                                    prompt_investigador.strip(),
                                )
                                import time
                                import queue as queue_module
                                import threading
                                
                                t_inicio = time.time()
                                cola = queue_module.Queue()
                                resultado_container = [None]
                                def correr():
                                    def on_resultado(r): cola.put(r)
                                    resultado_container[0] = ejecutar_analisis_automatico(prompt_final, callback=on_resultado)
                                    cola.put("__FIN__")
                                hilo = threading.Thread(target=correr)
                                hilo.start()
                                st.markdown("#### Progreso")
                                panel = st.empty()
                                estados_ia = {n: "evaluando..." for n in ["Auto-Ollama-Conservador", "Auto-Gemini-Contextual", "Auto-Groq-Contraste"]}
                                def render_panel(estados_dict):
                                    filas = ["| IA | Veredicto |", "|---|---|"]
                                    for n, s in estados_dict.items():
                                        filas.append(f"| {n} | {s} |")
                                    panel.markdown("\n".join(filas))
                                render_panel(estados_ia)
                                while True:
                                    try:
                                        item = cola.get(timeout=1)
                                        if item == "__FIN__": break
                                        ia_name = item.get("ia", "desconocida")
                                        if item.get("status") == "ok":
                                            estados_ia[ia_name] = f"✅ {item.get('data', {}).get('decision', 'NO BET')}"
                                        else:
                                            estados_ia[ia_name] = "❌ Error"
                                    except: pass
                                    render_panel(estados_ia)
                                hilo.join()
                                panel.empty()
                                if resultado_container[0]:
                                    st.session_state.auto_resultados_op = resultado_container[0][0]
                        
                        resultados = st.session_state.auto_resultados_op
                        if resultados:
                            st.success(f"{len(resultados)} analistas contestaron.")
                            for r in resultados:
                                if r.get("status") == "ok":
                                    p = r["data"]
                                    st.markdown(f"**{p.get('ia', '?')}** - {p.get('decision', 'NO BET')}")
                                    st.write(f"- Mercado: {p.get('mercado', '-')} | Selección: {p.get('seleccion', '-')}")
                                    try:
                                        cuota_f = float(p.get('cuota', 0) or 0)
                                        confianza_f = float(p.get('confianza', 0) or 0)
                                    except:
                                        cuota_f = 0.0
                                        confianza_f = 0.0
                                    st.write(f"- Cuota: {cuota_f:.2f} | Confianza: {confianza_f*100:.0f}%")
                                    st.info(p.get('razonamiento', 'Sin razonamiento'))
                                else:
                                    st.error(f"**{r.get('ia')}**: Falló - {r.get('error')}")

# ====================== JUEZ PONDERADO ======================
with tab_lab:
    st.divider()
    st.header("Laboratorio de Consenso")
    _render_section_banner(
        "Lab de consenso",
        "Herramienta secundaria para contrastar salidas multi-IA. Ya no es el motor principal del producto.",
        "Lab",
    )
    st.subheader("Consenso ponderado multi-IA")
    st.markdown("Consolida todos los picks pendientes usando los pesos de cada IA basados en su rendimiento historico.")

    pesos = {}
    if os.path.exists('pesos_ia.json'):
        with open('pesos_ia.json', 'r') as f:
            pesos = json.load(f)
        st.success("Pesos cargados desde pesos_ia.json")
        df_pesos = pd.DataFrame(list(pesos.items()), columns=['IA', 'Peso'])
        st.dataframe(df_pesos, width='stretch')
    else:
        st.warning("No se encontro pesos_ia.json. Se utilizaran pesos neutros (1.0) para todas las IAs.")

    df = fetch_backend_picks()
    if df is None:
        st.error("Motor no disponible: backend no responde")
        st.stop()
    if df.empty:
        st.info("No hay picks almacenados en la base de datos.")
    else:
        pendientes = df[(df['resultado'] == 'pendiente') & (df['tipo_pick'] == 'principal')]
        total_base = len(df)
        total_pend = len(pendientes)
        total_cerr = int((df['resultado'] != 'pendiente').sum())
        ccp1, ccp2, ccp3, ccp4 = st.columns(4)
        ccp1.metric("Base total", total_base)
        ccp2.metric("Pendientes", total_pend)
        ccp3.metric("Cerrados", total_cerr)
        ccp4.metric("Pesos cargados", len(pesos) if pesos else 0)
        if pendientes.empty:
            st.info("No hay picks principales pendientes de consolidacion.")
        else:
            st.info(f"{len(pendientes)} picks principales pendientes.")
            resultados = consolidar_picks(pendientes, pesos)
            df_resultados = pd.DataFrame(resultados)
            st.subheader("Picks consolidados")
            if not df_resultados.empty:
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Publicables", int((df_resultados.get("veredicto", pd.Series(dtype=str)) == "Publicable").sum()))
                k2.metric("En vigilancia", int((df_resultados.get("veredicto", pd.Series(dtype=str)) == "Vigilar").sum()))
                k3.metric("Debiles", int((df_resultados.get("veredicto", pd.Series(dtype=str)).isin(["Debil", "Descartar"])).sum()))
                k4.metric("Score medio", f"{df_resultados.get('Score', pd.Series([0])).mean():.2f}")
                filtro_veredicto = st.selectbox("Filtrar veredicto", ["Todos"] + sorted(df_resultados["veredicto"].astype(str).unique().tolist()) if "veredicto" in df_resultados.columns else ["Todos"], key="consenso_filtro_veredicto")
                if filtro_veredicto != "Todos" and "veredicto" in df_resultados.columns:
                    df_resultados = df_resultados[df_resultados["veredicto"].astype(str) == filtro_veredicto]
                st.caption(f"Filas visibles: {len(df_resultados)}")
                st.caption("El score mezcla consenso real, peso historico y confianza ponderada. Ya no depende solo del numero bruto de votos.")
            st.dataframe(df_resultados, width='stretch')

            if st.button("Exportar veredicto a JSON"):
                guardar_veredicto(resultados)
                st.success("Veredicto exportado en veredicto_final.json")

# ====================== APRENDIZAJE ======================
    st.divider()
    st.header("Laboratorio de Aprendizaje")
    _render_section_banner(
        "Aprendizaje del motor",
        "Lee el rendimiento historico del Motor Propio y detecta que mercados, niveles de confianza y perfiles de pick estan funcionando mejor.",
        "Motor",
    )
    st.subheader("Tablero de aprendizaje del Motor Propio")
    st.caption("Aqui ya no miramos pesos de IAs. Miramos como se esta comportando el motor cuando sus picks se cierran en la base.")

    df_learning = fetch_backend_picks(incluir_alternativas=True)
    if df_learning is None:
        st.error("Aprendizaje no disponible: backend no responde")
        st.stop()
    df_motor_logs = get_motor_pick_logs(limit=1000)
    if df_learning.empty:
        st.info("Todavia no hay picks en base para construir aprendizaje.")
    else:
        df_motor_all = df_learning[
            (df_learning["ia"].astype(str) == "Motor-Propio")
            & (df_learning["tipo_pick"].astype(str) == "principal")
        ].copy()
        df_motor_closed = df_motor_all[df_motor_all["resultado"].isin(["ganada", "perdida", "media"])].copy() if not df_motor_all.empty else pd.DataFrame()

        if df_motor_all.empty:
            st.info("Aun no hay picks guardados del Motor Propio.")
        else:
            total_motor = len(df_motor_all)
            cerrados_motor = len(df_motor_closed)
            pendientes_motor = int((df_motor_all["resultado"] == "pendiente").sum()) if "resultado" in df_motor_all.columns else 0
            ganadas_motor = int((df_motor_closed["resultado"] == "ganada").sum()) if not df_motor_closed.empty else 0
            medias_motor = int((df_motor_closed["resultado"] == "media").sum()) if not df_motor_closed.empty else 0
            perdidas_motor = int((df_motor_closed["resultado"] == "perdida").sum()) if not df_motor_closed.empty else 0
            acierto_motor = ((ganadas_motor + (medias_motor * 0.5)) / max(1, cerrados_motor) * 100) if cerrados_motor else 0
            roi_motor = (float(df_motor_closed["ganancia"].sum()) / float(df_motor_closed["stake"].sum()) * 100) if cerrados_motor and float(df_motor_closed["stake"].sum() or 0) else 0

            am1, am2, am3, am4, am5 = st.columns(5)
            am1.metric("Picks del motor", total_motor)
            am2.metric("Cerrados", cerrados_motor)
            am3.metric("Pendientes", pendientes_motor)
            am4.metric("Acierto ponderado", f"{acierto_motor:.1f}%")
            am5.metric("ROI motor", f"{roi_motor:.2f}%")

            am6, am7, am8 = st.columns(3)
            am6.metric("Ganadas", ganadas_motor)
            am7.metric("Medias", medias_motor)
            am8.metric("Perdidas", perdidas_motor)

            if not df_motor_logs.empty:
                logs_total = len(df_motor_logs)
                logs_pick = int(pd.to_numeric(df_motor_logs["emitido"], errors="coerce").fillna(0).sum())
                logs_no_bet = logs_total - logs_pick
                logs_saved = int(pd.to_numeric(df_motor_logs["saved_to_picks"], errors="coerce").fillna(0).sum())
                lg1, lg2, lg3 = st.columns(3)
                lg1.metric("Corridas del motor", logs_total)
                lg2.metric("PICK emitidos", logs_pick)
                lg3.metric("NO BET", logs_no_bet)
                st.caption(f"Corridas guardadas en log: {logs_total} | Corridas que terminaron en pick guardado: {logs_saved}")

                def _safe_json_payload(value, fallback):
                    if isinstance(value, (dict, list)):
                        return value
                    if isinstance(value, str) and value.strip():
                        try:
                            return json.loads(value)
                        except Exception:
                            return fallback
                    return fallback

                df_logs_view = df_motor_logs.copy()
                df_logs_view["mercado"] = df_logs_view["mercado"].fillna("Sin mercado").replace("", "Sin mercado")
                df_logs_view["emitido"] = pd.to_numeric(df_logs_view["emitido"], errors="coerce").fillna(0).astype(int)
                df_logs_view["saved_to_picks"] = pd.to_numeric(df_logs_view["saved_to_picks"], errors="coerce").fillna(0).astype(int)
                df_logs_view["valor_esperado"] = pd.to_numeric(df_logs_view["valor_esperado"], errors="coerce")
                df_logs_view["confianza"] = pd.to_numeric(df_logs_view["confianza"], errors="coerce")
                df_logs_view["calidad_input"] = pd.to_numeric(df_logs_view["calidad_input"], errors="coerce")
                df_logs_view["market_fit_score"] = pd.to_numeric(df_logs_view["market_fit_score"], errors="coerce")
                df_logs_view["guardrail_penalty"] = pd.to_numeric(df_logs_view["guardrail_penalty"], errors="coerce")
                df_logs_view["decision_payload"] = df_logs_view["decision_json"].apply(lambda v: _safe_json_payload(v, {}))
                df_logs_view["bloqueos_list"] = df_logs_view["decision_payload"].apply(
                    lambda d: d.get("bloqueos", []) if isinstance(d, dict) else []
                )
                df_logs_view["motivos_list"] = df_logs_view["decision_payload"].apply(
                    lambda d: d.get("motivos_clave", []) if isinstance(d, dict) else []
                )
                df_logs_view["bloqueos_count"] = df_logs_view["bloqueos_list"].apply(lambda x: len(x) if isinstance(x, list) else 0)
                df_logs_view["decision_text"] = df_logs_view["decision_payload"].apply(
                    lambda d: d.get("decision", "NO BET") if isinstance(d, dict) else "NO BET"
                )

                st.markdown("### Lectura operativa de logs")
                oper1, oper2, oper3, oper4 = st.columns(4)
                pick_rate = (logs_pick / max(1, logs_total)) * 100
                ev_emitidos = float(df_logs_view.loc[df_logs_view["emitido"] == 1, "valor_esperado"].mean()) if logs_pick else 0.0
                confianza_emitidos = float(df_logs_view.loc[df_logs_view["emitido"] == 1, "confianza"].mean()) if logs_pick else 0.0
                calidad_media = float(df_logs_view["calidad_input"].mean()) if not df_logs_view.empty else 0.0
                oper1.metric("Pick rate", f"{pick_rate:.1f}%")
                oper2.metric("EV medio emitidos", f"{ev_emitidos * 100:.1f}%")
                oper3.metric("Confianza media emitidos", f"{confianza_emitidos * 100:.1f}%")
                oper4.metric("Calidad input media", f"{calidad_media:.1f}/100")

                st.markdown("### Donde emite y donde se bloquea")
                resumen_logs_mercado = (
                    df_logs_view.groupby("mercado", dropna=False)
                    .agg(
                        corridas=("mercado", "count"),
                        picks_emitidos=("emitido", "sum"),
                        saved_a_base=("saved_to_picks", "sum"),
                        confianza_media=("confianza", "mean"),
                        ev_medio=("valor_esperado", "mean"),
                        calidad_media=("calidad_input", "mean"),
                        fit_medio=("market_fit_score", "mean"),
                        penalizacion_media=("guardrail_penalty", "mean"),
                    )
                    .reset_index()
                )
                resumen_logs_mercado["pick_rate"] = (
                    resumen_logs_mercado["picks_emitidos"] / resumen_logs_mercado["corridas"].clip(lower=1) * 100
                ).round(1)
                for col in ["confianza_media", "ev_medio", "calidad_media", "fit_medio", "penalizacion_media"]:
                    resumen_logs_mercado[col] = pd.to_numeric(resumen_logs_mercado[col], errors="coerce").fillna(0)
                resumen_logs_mercado["confianza_media"] = (resumen_logs_mercado["confianza_media"] * 100).round(1)
                resumen_logs_mercado["ev_medio"] = (resumen_logs_mercado["ev_medio"] * 100).round(1)
                resumen_logs_mercado["calidad_media"] = resumen_logs_mercado["calidad_media"].round(1)
                resumen_logs_mercado["fit_medio"] = resumen_logs_mercado["fit_medio"].round(2)
                resumen_logs_mercado["penalizacion_media"] = resumen_logs_mercado["penalizacion_media"].round(2)
                st.dataframe(
                    resumen_logs_mercado.sort_values(["corridas", "pick_rate"], ascending=[False, False]),
                    width='stretch',
                    hide_index=True,
                )

                bloqueos_flat = []
                for items in df_logs_view["bloqueos_list"]:
                    if isinstance(items, list):
                        bloqueos_flat.extend([str(x).strip() for x in items if str(x).strip()])
                if bloqueos_flat:
                    st.markdown("### Bloqueos mas repetidos del motor")
                    df_bloqueos = (
                        pd.Series(bloqueos_flat, name="bloqueo")
                        .value_counts()
                        .reset_index()
                    )
                    df_bloqueos.columns = ["bloqueo", "veces"]
                    df_bloqueos["% logs"] = (df_bloqueos["veces"] / max(1, logs_total) * 100).round(1)
                    st.dataframe(df_bloqueos, width='stretch', hide_index=True)

                    top_bloqueo = df_bloqueos.iloc[0]
                    st.info(
                        f"Bloqueo dominante actual: {top_bloqueo['bloqueo']} "
                        f"({int(top_bloqueo['veces'])} veces, {top_bloqueo['% logs']:.1f}% de las corridas)."
                    )

                st.markdown("### Sensibilidad por calidad del input")
                df_logs_view["calidad_bucket"] = pd.cut(
                    df_logs_view["calidad_input"].fillna(0),
                    bins=[-0.01, 59.99, 74.99, 89.99, 100.0],
                    labels=["<=59", "60-74", "75-89", "90-100"],
                )
                resumen_calidad_logs = (
                    df_logs_view.groupby("calidad_bucket", dropna=False)
                    .agg(
                        corridas=("calidad_bucket", "count"),
                        picks_emitidos=("emitido", "sum"),
                        confianza_media=("confianza", "mean"),
                        ev_medio=("valor_esperado", "mean"),
                    )
                    .reset_index()
                )
                resumen_calidad_logs["pick_rate"] = (
                    resumen_calidad_logs["picks_emitidos"] / resumen_calidad_logs["corridas"].clip(lower=1) * 100
                ).round(1)
                resumen_calidad_logs["confianza_media"] = (
                    pd.to_numeric(resumen_calidad_logs["confianza_media"], errors="coerce").fillna(0) * 100
                ).round(1)
                resumen_calidad_logs["ev_medio"] = (
                    pd.to_numeric(resumen_calidad_logs["ev_medio"], errors="coerce").fillna(0) * 100
                ).round(1)
                st.dataframe(resumen_calidad_logs, width='stretch', hide_index=True)

                st.markdown("### Calibracion sugerida por el laboratorio")
                recomendaciones = []

                if pick_rate < 12:
                    recomendaciones.append("El motor esta demasiado conservador: revisa umbrales globales de confianza y sistemas minimos a favor.")
                elif pick_rate > 45:
                    recomendaciones.append("El motor esta emitiendo demasiado: conviene endurecer guardrails o fit de mercado antes de deteriorar ROI.")

                if calidad_media >= 80 and pick_rate < 18:
                    recomendaciones.append("Con calidad de input alta el pick rate sigue bajo: el cuello parece estar en reglas de emision, no en datos.")

                if bloqueos_flat:
                    bloqueo_dominante = str(df_bloqueos.iloc[0]["bloqueo"]).lower()
                    if "menos de 5 sistemas" in bloqueo_dominante:
                        recomendaciones.append("Prueba una regla condicional de 4 apoyos cuando el mercado tenga fit alto y la penalizacion estructural sea baja.")
                    if "confianza por debajo" in bloqueo_dominante:
                        recomendaciones.append("Revisa la formula de confianza: el motor podria estar descontando demasiado aun con EV y calidad altos.")
                    if "calidad de input" in bloqueo_dominante:
                        recomendaciones.append("El principal freno es la calidad del partido preparado: conviene priorizar autocompletado y datos faltantes antes de tocar el motor.")
                    if "sin confirmacion especifica" in bloqueo_dominante:
                        recomendaciones.append("Falta especializacion por mercado: refuerza reglas propias de 1X2, BTTS y Over/Under antes de bajar umbrales.")

                mercados_a_premiar = resumen_logs_mercado[
                    (resumen_logs_mercado["corridas"] >= 5)
                    & (resumen_logs_mercado["pick_rate"] >= 20)
                    & (resumen_logs_mercado["fit_medio"] >= 0.18)
                    & (resumen_logs_mercado["penalizacion_media"] <= 0.25)
                ].sort_values(["pick_rate", "ev_medio"], ascending=[False, False])
                if not mercados_a_premiar.empty:
                    mejor_lab = mercados_a_premiar.iloc[0]
                    recomendaciones.append(
                        f"Mercado con mejor perfil operativo actual: {mejor_lab['mercado']}. "
                        f"Puedes testear un trato algo mas agresivo ahi porque ya muestra fit medio {mejor_lab['fit_medio']:.2f} y pick rate {mejor_lab['pick_rate']:.1f}%."
                    )

                mercados_atascados = resumen_logs_mercado[
                    (resumen_logs_mercado["corridas"] >= 5)
                    & (resumen_logs_mercado["pick_rate"] <= 10)
                    & (resumen_logs_mercado["ev_medio"] >= 8)
                ].sort_values(["ev_medio", "corridas"], ascending=[False, False])
                if not mercados_atascados.empty:
                    atascado = mercados_atascados.iloc[0]
                    recomendaciones.append(
                        f"Mercado atascado pese a EV alto: {atascado['mercado']}. "
                        f"Revisa si el fit o la penalizacion lo estan frenando demasiado."
                    )

                calidad_alta_row = resumen_calidad_logs[resumen_calidad_logs["calidad_bucket"] == "90-100"]
                if not calidad_alta_row.empty:
                    pick_rate_calidad_alta = float(calidad_alta_row.iloc[0]["pick_rate"])
                    if pick_rate_calidad_alta < 20:
                        recomendaciones.append("Incluso con calidad 90-100 el motor emite poco: toca recalibrar decision, no solo seguir pidiendo mejores datos.")

                if recomendaciones:
                    for rec in recomendaciones[:5]:
                        st.write(f"- {rec}")
                else:
                    st.success("Aun no hay patron fuerte de bloqueo. Sigue acumulando logs para calibrar con una muestra mas estable.")

            if cerrados_motor < 5:
                st.warning("Aun hay poca muestra cerrada. Usa esta lectura como orientacion, no como verdad estadistica fuerte.")

            if not df_motor_closed.empty:
                df_motor_closed["mercado"] = df_motor_closed["mercado"].fillna("Sin mercado").astype(str)
                df_motor_closed["confianza_bucket"] = pd.cut(
                    pd.to_numeric(df_motor_closed["confianza"], errors="coerce").fillna(0),
                    bins=[-0.01, 0.60, 0.70, 0.80, 1.00],
                    labels=["<=60%", "61-70%", "71-80%", ">80%"],
                )
                df_motor_closed["acierto_score"] = df_motor_closed["resultado"].map({"ganada": 1.0, "media": 0.5, "perdida": 0.0}).fillna(0)

                st.markdown("### Lectura por mercado")
                resumen_mercado = (
                    df_motor_closed.groupby("mercado", dropna=False)
                    .agg(
                        picks=("mercado", "count"),
                        acierto=("acierto_score", "mean"),
                        roi=("ganancia", lambda s: float(s.sum()) / max(1e-9, float(df_motor_closed.loc[s.index, "stake"].sum()))),
                        cuota_media=("cuota", "mean"),
                    )
                    .reset_index()
                )
                resumen_mercado["acierto"] = (resumen_mercado["acierto"] * 100).round(1)
                resumen_mercado["roi"] = (resumen_mercado["roi"] * 100).round(2)
                resumen_mercado["cuota_media"] = resumen_mercado["cuota_media"].round(2)
                st.dataframe(resumen_mercado.sort_values(["picks", "roi"], ascending=[False, False]), width='stretch', hide_index=True)

                st.markdown("### Lectura por confianza declarada")
                resumen_conf = (
                    df_motor_closed.groupby("confianza_bucket", dropna=False)
                    .agg(
                        picks=("confianza_bucket", "count"),
                        acierto=("acierto_score", "mean"),
                        roi=("ganancia", lambda s: float(s.sum()) / max(1e-9, float(df_motor_closed.loc[s.index, "stake"].sum()))),
                    )
                    .reset_index()
                )
                resumen_conf["acierto"] = (resumen_conf["acierto"] * 100).round(1)
                resumen_conf["roi"] = (resumen_conf["roi"] * 100).round(2)
                st.dataframe(resumen_conf, width='stretch', hide_index=True)

                st.markdown("### Reglas sugeridas para la siguiente calibracion")
                top_markets = resumen_mercado[resumen_mercado["picks"] >= 2].sort_values("roi", ascending=False)
                weak_markets = resumen_mercado[resumen_mercado["picks"] >= 2].sort_values("roi", ascending=True)
                if not top_markets.empty:
                    mejor = top_markets.iloc[0]
                    st.success(f"Mercado a premiar: {mejor['mercado']} | ROI {mejor['roi']:.2f}% | Acierto {mejor['acierto']:.1f}%")
                if not weak_markets.empty:
                    peor = weak_markets.iloc[0]
                    st.warning(f"Mercado a vigilar: {peor['mercado']} | ROI {peor['roi']:.2f}% | Acierto {peor['acierto']:.1f}%")

                conf_floja = resumen_conf[resumen_conf["roi"] < 0]
                if not conf_floja.empty:
                    st.info("Si una banda de confianza sigue en negativo con suficiente muestra, conviene endurecer el stake o exigir mas filtros ahi.")

                with st.expander("Ver picks cerrados del motor"):
                    cols_motor = [c for c in ["fecha", "partido", "mercado", "seleccion", "cuota", "confianza", "stake", "resultado", "ganancia"] if c in df_motor_closed.columns]
                    st.dataframe(df_motor_closed[cols_motor].copy(), width='stretch', hide_index=True)

                with st.expander("Comparativa rapida: Motor vs resto del sistema"):
                    df_otros = df_learning[
                        (df_learning["ia"].astype(str) != "Motor-Propio")
                        & (df_learning["tipo_pick"].astype(str) == "principal")
                        & (df_learning["resultado"].isin(["ganada", "perdida", "media"]))
                    ].copy()
                    if df_otros.empty:
                        st.info("Aun no hay muestra comparable del resto del sistema.")
                    else:
                        otros_acierto = (df_otros["resultado"].map({"ganada": 1.0, "media": 0.5, "perdida": 0.0}).fillna(0).mean() * 100)
                        otros_roi = (float(df_otros["ganancia"].sum()) / max(1e-9, float(df_otros["stake"].sum())) * 100)
                        cmp1, cmp2 = st.columns(2)
                        cmp1.metric("Acierto Motor vs resto", f"{acierto_motor:.1f}%", f"{acierto_motor - otros_acierto:+.1f}%")
                        cmp2.metric("ROI Motor vs resto", f"{roi_motor:.2f}%", f"{roi_motor - otros_roi:+.2f}%")
            else:
                st.info("El Motor Propio ya tiene picks guardados, pero aun no hay cierres para aprender.")

# ====================== COMPARATIVA ESPEJO ======================
    st.divider()
    st.header("Comparativa de Modelos IA")
    _render_section_banner(
        "Lab comparativo",
        "Compara metodologias y deja evidencia historica. Idealmente migrara a Motor Propio vs Analisis IA.",
        "Lab",
    )
    st.subheader("Comparativa espejo")
    st.markdown("Registra solo el pick principal manual y el pick principal automatico. La idea es comparar cual flujo rindio mejor cuando el partido cierre.")

    comparativas = cargar_comparativas()
    if comparativas:
        df_comp_preview = pd.DataFrame(comparativas)
        total_casos = len(df_comp_preview)
        cerrados_preview = int((df_comp_preview["estado_caso"] == "Cerrado").sum()) if "estado_caso" in df_comp_preview.columns else 0
        manual_preview = int((df_comp_preview["ganador_caso"] == "Manual").sum()) if "ganador_caso" in df_comp_preview.columns else 0
        auto_preview = int((df_comp_preview["ganador_caso"] == "Automatico").sum()) if "ganador_caso" in df_comp_preview.columns else 0
        ce1, ce2, ce3, ce4 = st.columns(4)
        ce1.metric("Casos", total_casos)
        ce2.metric("Cerrados", cerrados_preview)
        ce3.metric("Manual gana", manual_preview)
        ce4.metric("Automatico gana", auto_preview)

    with st.form("comparativa_espejo_form"):
        partido = st.text_input("Partido", placeholder="Ej: Atletico Nacional vs Llaneros")
        fecha_partido = st.text_input("Fecha del partido", value=datetime.now().strftime("%Y-%m-%d"))

        st.markdown("### Flujo manual")
        col_m1, col_m2, col_m3 = st.columns(3)
        manual_mercado = col_m1.text_input("Mercado manual")
        manual_seleccion = col_m2.text_input("Seleccion manual")
        manual_cuota = col_m3.number_input("Cuota manual", min_value=0.0, value=0.0, step=0.01)
        manual_nota = st.text_input("Nota manual corta", placeholder="Ej: Pick principal del flujo manual")

        st.markdown("### Flujo automatico")
        col_a1, col_a2, col_a3 = st.columns(3)
        auto_mercado = col_a1.text_input("Mercado automatico")
        auto_seleccion = col_a2.text_input("Seleccion automatica")
        auto_cuota = col_a3.number_input("Cuota automatica", min_value=0.0, value=0.0, step=0.01)
        auto_consenso = st.text_input("Consenso automatico", placeholder="Ej: 3/6")
        auto_nota = st.text_input("Nota automatica corta", placeholder="Ej: Consenso principal al local")

        st.markdown("### Cierre del caso")
        col_c1, col_c2, col_c3 = st.columns(3)
        resultado_real = col_c1.text_input("Resultado real", placeholder="Ej: 2-0")
        ganador_caso = col_c2.selectbox(
            "Quien estuvo mejor",
            ["Pendiente", "Manual", "Automatico", "Empate", "Ambos fallaron"],
        )
        estado_caso = col_c3.selectbox("Estado", ["Pendiente", "Cerrado"])
        notas = st.text_area("Notas", height=70)

        guardar_caso = st.form_submit_button("Guardar caso espejo")

    if guardar_caso:
        if not partido.strip():
            st.warning("Escribe el partido para guardar la comparativa.")
        else:
            comparativas.append({
                "fecha_registro": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "fecha_partido": fecha_partido,
                "partido": partido.strip(),
                "manual_mercado": manual_mercado.strip(),
                "manual_seleccion": manual_seleccion.strip(),
                "manual_cuota": manual_cuota,
                "manual_nota": manual_nota.strip(),
                "auto_mercado": auto_mercado.strip(),
                "auto_seleccion": auto_seleccion.strip(),
                "auto_cuota": auto_cuota,
                "auto_consenso": auto_consenso.strip(),
                "auto_nota": auto_nota.strip(),
                "resultado_real": resultado_real.strip(),
                "ganador_caso": ganador_caso,
                "estado_caso": estado_caso,
                "notas": notas.strip(),
            })
            guardar_comparativas(comparativas)
            st.success("Caso espejo guardado.")
            st.rerun()

    if comparativas:
        st.markdown("---")
        st.subheader("Historial de comparativas")
        df_comp = pd.DataFrame(comparativas)
        col_fc1, col_fc2 = st.columns([1.1, 1.5])
        filtro_estado_comp = col_fc1.selectbox("Filtrar por estado", ["Todos", "Pendiente", "Cerrado"], key="comp_filtro_estado")
        busqueda_comp = col_fc2.text_input("Buscar partido", placeholder="Ej: Nacional, Milan, Liverpool...", key="comp_busqueda")
        if filtro_estado_comp != "Todos" and "estado_caso" in df_comp.columns:
            df_comp = df_comp[df_comp["estado_caso"] == filtro_estado_comp]
        if busqueda_comp.strip():
            patron = busqueda_comp.strip().lower()
            df_comp = df_comp[df_comp["partido"].fillna("").astype(str).str.lower().str.contains(patron, na=False)]
        cols_tabla = [
            "fecha_partido",
            "partido",
            "manual_mercado",
            "manual_seleccion",
            "auto_mercado",
            "auto_seleccion",
            "resultado_real",
            "ganador_caso",
            "estado_caso",
        ]
        cols_tabla = [c for c in cols_tabla if c in df_comp.columns]
        st.caption(f"Casos visibles: {len(df_comp)}")
        st.dataframe(df_comp[cols_tabla].astype(str), width='stretch')

        if "estado_caso" in df_comp.columns:
            cerrados = df_comp[df_comp["estado_caso"] == "Cerrado"]
            if not cerrados.empty:
                col_s1, col_s2, col_s3, col_s4 = st.columns(4)
                col_s1.metric("Casos cerrados", len(cerrados))
                col_s2.metric("Manual gana", int((cerrados["ganador_caso"] == "Manual").sum()))
                col_s3.metric("Automatico gana", int((cerrados["ganador_caso"] == "Automatico").sum()))
                col_s4.metric(
                    "Empates / ambos fallan",
                    int((cerrados["ganador_caso"] == "Empate").sum()) + int((cerrados["ganador_caso"] == "Ambos fallaron").sum()),
                )
    else:
        _render_empty_state("Sin comparativas registradas", "Aqui apareceran los casos espejo (Manual vs Automatico) para medir el rendimiento de tus flujos.", "⚖️")

# ====================== USUARIOS ======================
with tab_users:
    _render_section_banner(
        "Gestion de usuarios",
        "Administra miembros reales, crea accesos, controla estados y revisa rapidamente la base de cuentas activas.",
        "Usuarios",
    )
    st.subheader("Gestion de usuarios")
    st.markdown("Crea, revisa y activa/desactiva usuarios reales para la vista publica.")

    df_users = get_all_users()
    total_users = len(df_users) if not df_users.empty else 0
    users_activos = int(df_users["active"].fillna(0).astype(int).sum()) if not df_users.empty and "active" in df_users.columns else 0
    users_inactivos = total_users - users_activos
    admins_total = int((df_users["role"].astype(str) == "admin").sum()) if not df_users.empty and "role" in df_users.columns else 0
    uu1, uu2, uu3, uu4 = st.columns(4)
    uu1.metric("Usuarios", total_users)
    uu2.metric("Activos", users_activos)
    uu3.metric("Inactivos", users_inactivos)
    uu4.metric("Admins", admins_total)

    with st.form("crear_usuario_admin_form"):
        col_u1, col_u2 = st.columns(2)
        nuevo_username = col_u1.text_input("Usuario")
        nuevo_display = col_u2.text_input("Nombre visible")
        col_u3, col_u4, col_u5 = st.columns(3)
        nuevo_email = col_u3.text_input("Email")
        nuevo_password = col_u4.text_input("Clave", type="password")
        nuevo_role = col_u5.selectbox("Rol", ["user", "admin"])
        crear_usuario_btn = st.form_submit_button("Crear usuario")

    if crear_usuario_btn:
        ok, mensaje = create_user(
            nuevo_username,
            nuevo_display,
            nuevo_password,
            nuevo_email,
            role=nuevo_role,
            must_change_password=(nuevo_role == "admin"),
        )
        if ok:
            st.success(mensaje)
            st.rerun()
        else:
            st.error(mensaje)

    st.markdown("---")
    if df_users.empty:
        st.info("Todavia no hay usuarios registrados.")
    else:
        col_fu1, col_fu2 = st.columns([1.2, 1.2])
        filtro_rol = col_fu1.selectbox("Filtrar por rol", ["Todos", "admin", "user"], key="usuarios_filtro_rol")
        busqueda_usuario = col_fu2.text_input("Buscar usuario", placeholder="Usuario, nombre o email", key="usuarios_busqueda")
        df_users_view = df_users.copy()
        if filtro_rol != "Todos":
            df_users_view = df_users_view[df_users_view["role"].astype(str) == filtro_rol]
        if busqueda_usuario.strip():
            patron = busqueda_usuario.strip().lower()
            df_users_view = df_users_view[
                df_users_view["username"].fillna("").astype(str).str.lower().str.contains(patron, na=False)
                | df_users_view["display_name"].fillna("").astype(str).str.lower().str.contains(patron, na=False)
                | df_users_view["email"].fillna("").astype(str).str.lower().str.contains(patron, na=False)
            ]
        st.caption(f"Usuarios visibles: {len(df_users_view)}")
        columnas_users = [c for c in ["id", "username", "display_name", "email", "role", "active", "subscription_plan", "must_change_password", "last_login", "created_at"] if c in df_users_view.columns]
        st.dataframe(df_users_view[columnas_users].astype(str), width="stretch")
        st.markdown("### Cambiar estado")
        usuarios_opciones = {
            f"{row['display_name']} (@{row['username']}) | {'Activo' if int(row['active']) == 1 else 'Inactivo'}": int(row["id"])
            for _, row in df_users.iterrows()
        }
        col_ug1, col_ug2 = st.columns(2)
        usuario_label = col_ug1.selectbox("Selecciona el usuario", list(usuarios_opciones.keys()))
        accion_estado = col_ug2.selectbox("Nuevo estado", ["Activar", "Desactivar"])
        if st.button("Aplicar cambio de estado"):
            ok, mensaje = update_user_status(
                usuarios_opciones[usuario_label],
                accion_estado == "Activar",
            )
            if ok:
                st.success(mensaje)
                st.rerun()

    st.markdown("---")
    st.subheader("Gestión de Suscripciones")
    
    # Estadísticas de suscripciones
    subscription_stats = get_subscription_stats()
    if subscription_stats:
        ss_col1, ss_col2, ss_col3, ss_col4 = st.columns(4)
        free_count = next((s['total'] for s in subscription_stats if s.get('subscription_plan') == 'free'), 0)
        premium_count = next((s['total'] for s in subscription_stats if s.get('subscription_plan') == 'premium'), 0)
        vip_count = next((s['total'] for s in subscription_stats if s.get('subscription_plan') == 'vip'), 0)
        activos_count = sum(s.get('activos', 0) for s in subscription_stats)
        ss_col1.metric("Free", free_count)
        ss_col2.metric("Premium", premium_count)
        ss_col3.metric("VIP", vip_count)
        ss_col4.metric("Total activos", activos_count)
    
    # Formulario para cambiar plan de suscripción
    with st.form("suscripcion_form"):
        col_sub1, col_sub2, col_sub3 = st.columns([1.5, 1, 1])
        
        # Crear diccionario de opciones para obtener ID fácilmente
        opciones_usuarios = {f"{row['display_name']} (@{row['username']}) - {row.get('subscription_plan', 'free')}": int(row['id']) for _, row in df_users.iterrows()}
        lista_opciones = list(opciones_usuarios.keys())
        
        usuario_suscripcion = col_sub1.selectbox(
            "Usuario a modificar",
            lista_opciones,
            key="suscripcion_usuario"
        )
        usuario_id = opciones_usuarios.get(usuario_suscripcion, 0)
        
        nuevo_plan = col_sub2.selectbox("Nuevo plan", ["free", "premium", "vip"])
        dias_suscripcion = col_sub3.number_input("Días de suscripción", min_value=1, max_value=365, value=30)
        
        aplicar_suscripcion = st.form_submit_button("Aplicar plan")
        
        if aplicar_suscripcion:
            ok = update_subscription(usuario_id, nuevo_plan, dias_suscripcion)
            if ok:
                st.success(f"Plan actualizado a {nuevo_plan} por {dias_suscripcion} días")
                st.rerun()
            else:
                st.error("Error al actualizar la suscripción")


# ============================================
# BARRA LATERAL
# ============================================
with st.sidebar:
    st.markdown("---")
    st.markdown("### Sesion activa")
    st.caption(f"Panel actual: {panel_activo}")

    if st.session_state.get("admin_user"):
        st.success(f"Admin activo: {st.session_state['admin_user'].get('display_name', st.session_state['admin_user'].get('username', 'admin'))}")
        if st.button("Cerrar sesion"):
            _clear_admin_session()
            st.rerun()
    elif st.session_state.get("public_user"):
        st.info(f"Miembro activo: {st.session_state['public_user'].get('display_name', st.session_state['public_user'].get('username', 'usuario'))}")
        if st.button("Cerrar sesion", key="sidebar_close_public"):
            _clear_public_session()
            st.rerun()

    if st.session_state.get("admin_user"):
        auto_pick_actual = _config_bool("auto_publicar_pick_telegram", False)
        auto_res_actual = _config_bool("auto_publicar_resultado_telegram", False)

        auto_pick_nuevo = st.checkbox(
            "Auto-publicar picks a Telegram",
            value=auto_pick_actual,
            help="Cuando guardes un pick principal nuevo, se enviara automaticamente el pack social a Telegram.",
        )
        auto_res_nuevo = st.checkbox(
            "Auto-publicar resultados a Telegram",
            value=auto_res_actual,
            help="Cuando cierres un pick principal, se enviara automaticamente el resultado a Telegram.",
        )

        if auto_pick_nuevo != auto_pick_actual:
            update_config("auto_publicar_pick_telegram", "1" if auto_pick_nuevo else "0")
            st.success("Configuracion de auto-publicacion de picks actualizada.")
            st.rerun()

        if auto_res_nuevo != auto_res_actual:
            update_config("auto_publicar_resultado_telegram", "1" if auto_res_nuevo else "0")
            st.success("Configuracion de auto-publicacion de resultados actualizada.")
            st.rerun()

        st.markdown("---")
        st.markdown("### Configuracion de bankroll")

        bankroll_actual = get_bankroll_inicial()
        stake_porc_actual = get_stake_porcentaje()

        nuevo_bankroll = st.number_input(
            "Bankroll inicial (COP)",
            min_value=10_000, max_value=100_000_000,
            value=int(bankroll_actual), step=10_000, format="%d"
        )
        nuevo_stake = st.number_input(
            "Stake (% del bankroll)",
            min_value=0.5, max_value=5.0,
            value=float(stake_porc_actual), step=0.1, format="%.1f"
        )

        if st.button("Guardar configuracion"):
            update_config('bankroll_inicial', nuevo_bankroll)
            update_config('stake_porcentaje', nuevo_stake)
            st.success("Configuracion guardada.")
            st.rerun()

        st.markdown("---")
        st.markdown("### Creditos The Odds API")
        from obtener_cuotas_api import obtener_creditos_restantes
        creditos, error_creditos = obtener_creditos_restantes()
        if creditos:
            st.metric("Restantes", creditos['remaining'])
            st.metric("Usados", creditos['used'])
        else:
            st.warning(f"No se pudo obtener creditos: {error_creditos}")

        st.markdown("### API-Football")
        if API_FOOTBALL_KEY:
            st.info("Plan gratuito estimado: 100 peticiones por dia")
        else:
            st.warning("API-Football no configurada")

    st.markdown("### Telegram")
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        st.success("Telegram listo para envios")
    else:
        st.warning("Telegram no configurado")

    st.markdown("---")
    st.success("Jr AI 11 v3.0 | 8 modelos | Multi-IA")



