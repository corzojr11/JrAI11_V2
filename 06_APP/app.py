import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
import os
import json
import re
import hmac
from pathlib import Path

from database import init_db, get_all_picks, update_resultado_con_cuota, save_picks, get_bankroll_inicial, get_stake_porcentaje, update_config, get_config_value, create_user, authenticate_user, get_all_users, update_user_status, update_user_profile, update_user_password, get_cached_team_logo, save_cached_team_logo, save_prepared_match, get_prepared_matches
from import_utils import validate_and_load_file
from backtest_engine import calcular_metricas, es_handicap_asiatico
from config import IAS_LIST, STAKE_PORCENTAJE, USD_TO_COP, MOSTRAR_USD, API_FOOTBALL_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ADMIN_PASSWORD
from services.league_service import get_league_key, detectar_liga_automatica, LIGAS_NOMBRES
from services.match_prepare_service import parsear_entrada_partido, preparar_partido_desde_api, construir_ficha_preparada, buscar_logo_equipo
from services.ollama_context_service import analizar_contexto_ollama, sugerir_campos_contexto_ollama
from core.judge import consolidar_picks, guardar_veredicto
from motor_picks import analizar_partido_motor

st.set_page_config(page_title="Jr AI 11 - Plataforma de Analisis", layout="wide")
init_db()

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
        usd = cop / USD_TO_COP
        return f"{formato_cop(cop)} COP ({formato_usd(usd)} USD)"
    else:
        return formato_cop(cop)


def cargar_prompt_automatico():
    ruta_prompt = os.path.join(
        os.path.dirname(__file__),
        "..",
        "01_PROMPTS",
        "automatizacion",
        "analista_prompt_automatico.txt",
    )
    with open(ruta_prompt, "r", encoding="utf-8") as archivo:
        return archivo.read()


COMPARATIVA_PATH = Path(__file__).resolve().parent / "data" / "comparativa_espejo.json"


def cargar_comparativas():
    if not COMPARATIVA_PATH.exists():
        return []
    try:
        with open(COMPARATIVA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def guardar_comparativas(registros):
    COMPARATIVA_PATH.parent.mkdir(exist_ok=True)
    with open(COMPARATIVA_PATH, "w", encoding="utf-8") as f:
        json.dump(registros, f, ensure_ascii=False, indent=2)


def _session_expired(last_seen, minutes):
    if not last_seen:
        return True
    try:
        marca = datetime.fromisoformat(str(last_seen))
    except Exception:
        return True
    return datetime.now() - marca > timedelta(minutes=minutes)


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


def _clear_admin_session():
    st.session_state.admin_user = None
    st.session_state.admin_last_password = ""
    st.session_state.admin_last_seen = ""
    st.session_state.admin_login_user = ""
    st.session_state.admin_login_pass = ""
    st.session_state.admin_force_new_password = ""
    st.session_state.admin_force_confirm_password = ""


def _clear_public_session():
    st.session_state.public_user = None
    st.session_state.public_last_password = ""
    st.session_state.public_last_seen = ""
    st.session_state.public_login_user = ""
    st.session_state.public_login_pass = ""


def _set_login_session(user, password):
    role = str(user.get("role", "") or "").strip().lower()
    if role == "admin":
        _clear_public_session()
        st.session_state.admin_user = user
        st.session_state.admin_last_password = password
        st.session_state.admin_last_seen = datetime.now().isoformat()
    else:
        _clear_admin_session()
        st.session_state.public_user = user
        st.session_state.public_last_password = password
        st.session_state.public_last_seen = datetime.now().isoformat()


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
            user = authenticate_user(login_user, login_pass)
            if user:
                _set_login_session(user, login_pass)
                st.success("Acceso concedido.")
                st.rerun()
            else:
                st.error("Credenciales invalidas o usuario inactivo.")

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


def _render_public_card(titulo, cuerpo, etiqueta="", tono="normal", meta_left="", meta_right="", footer_hint=""):
    color = "#d6aa4c"
    borde = "#253041"
    fondo = "#11161d"
    acento = "linear-gradient(135deg, rgba(41,215,100,.18), rgba(214,170,76,.18))"
    if tono == "win":
        color = "#31b36b"
        acento = "linear-gradient(135deg, rgba(49,179,107,.20), rgba(255,255,255,.04))"
    elif tono == "loss":
        color = "#d14b4b"
        acento = "linear-gradient(135deg, rgba(209,75,75,.20), rgba(255,255,255,.04))"
    elif tono == "push":
        color = "#d6aa4c"
        acento = "linear-gradient(135deg, rgba(214,170,76,.20), rgba(255,255,255,.04))"
    meta_l = str(meta_left or "").lower()
    if "1x2" in meta_l:
        acento = "linear-gradient(135deg, rgba(41,215,100,.16), rgba(52,111,255,.16))"
    elif "over" in meta_l or "under" in meta_l:
        acento = "linear-gradient(135deg, rgba(255,145,77,.18), rgba(214,170,76,.16))"
    elif "btts" in meta_l:
        acento = "linear-gradient(135deg, rgba(129,92,255,.18), rgba(52,111,255,.16))"
    elif "corner" in meta_l:
        acento = "linear-gradient(135deg, rgba(52,111,255,.18), rgba(41,215,100,.14))"
    elif "tarjet" in meta_l:
        acento = "linear-gradient(135deg, rgba(255,196,61,.20), rgba(255,145,77,.16))"
    local, visitante = _extraer_equipos_partido(titulo)
    logo_local = _get_team_logo_cached(local)
    logo_visitante = _get_team_logo_cached(visitante)
    st.markdown(
        f"""
        <div style="background:{fondo}; border:1px solid {borde}; border-radius:26px; padding:20px; margin-bottom:18px; box-shadow:0 14px 34px rgba(0,0,0,.22);">
            <div style="display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:12px;">
                <div style="display:flex; align-items:center; gap:12px;">
                    <div style="width:46px; height:46px; border-radius:999px; background:linear-gradient(135deg, #29d764, #d6aa4c); display:flex; align-items:center; justify-content:center; color:#07111d; font-weight:900; font-size:18px;">JR</div>
                    <div>
                        <div style="color:#f5f7fa; font-size:15px; font-weight:800;">Jr AI 11</div>
                        <div style="color:#8fa1b9; font-size:12px;">Actualizado hace instantes</div>
                    </div>
                </div>
                <div style="color:{color}; font-weight:800; font-size:12px; letter-spacing:1.3px; text-transform:uppercase; background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.06); padding:10px 12px; border-radius:999px;">{etiqueta}</div>
            </div>
            <div style="display:flex; justify-content:space-between; gap:14px; align-items:flex-start; flex-wrap:wrap;">
                <div style="flex:1 1 360px;">
                    <div style="color:#f5f7fa; font-weight:800; font-size:28px; line-height:1.15;">{titulo}</div>
                    <div style="color:#c6d0da; font-size:15px; line-height:1.6; margin-top:12px; white-space:pre-line;">{cuerpo}</div>
                    <div style="display:flex; gap:10px; flex-wrap:wrap; margin-top:14px;">
                        <div style="display:flex; align-items:center; gap:10px; background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.06); border-radius:999px; padding:8px 12px;">
                            {_team_logo_html(local, logo_local, "linear-gradient(135deg, #29d764, #4f8cff)")}
                            <div style="color:#dbe5ee; font-size:13px; font-weight:700;">{local or "Local"}</div>
                        </div>
                        <div style="display:flex; align-items:center; gap:10px; background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.06); border-radius:999px; padding:8px 12px;">
                            {_team_logo_html(visitante, logo_visitante, "linear-gradient(135deg, #d6aa4c, #ff9150)")}
                            <div style="color:#dbe5ee; font-size:13px; font-weight:700;">{visitante or "Visitante"}</div>
                        </div>
                    </div>
                </div>
                <div style="min-width:150px; background:{acento}; border:1px solid rgba(255,255,255,.08); border-radius:20px; padding:14px 16px;">
                    <div style="color:#8fa1b9; font-size:11px; font-weight:800; letter-spacing:1px; text-transform:uppercase;">Dato clave</div>
                    <div style="color:#f7fbff; font-size:15px; font-weight:800; margin-top:8px;">{meta_right or "Seguimiento real"}</div>
                </div>
            </div>
            <div style="display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; margin-top:16px;">
                <div style="display:flex; gap:10px; flex-wrap:wrap;">
                    <div style="background:#141d2a; border:1px solid rgba(255,255,255,.06); color:#dce6ef; padding:9px 12px; border-radius:999px; font-size:13px; font-weight:700;">{meta_left or "Publicacion oficial"}</div>
                    <div style="background:#141d2a; border:1px solid rgba(255,255,255,.06); color:#dce6ef; padding:9px 12px; border-radius:999px; font-size:13px; font-weight:700;">{footer_hint or "Feed privado"}</div>
                </div>
                <div style="color:#7f95ad; font-size:13px;">Compartible en Telegram y PDF social</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _market_icon(texto):
    valor = str(texto or "").lower()
    if "1x2" in valor:
        return "1X2"
    if "over" in valor or "under" in valor:
        return "Goles"
    if "btts" in valor:
        return "BTTS"
    if "corner" in valor:
        return "Corners"
    if "tarjet" in valor:
        return "Tarjetas"
    if "handicap" in valor:
        return "Handicap"
    return "Pick"


def _team_initials(nombre):
    palabras = [p for p in str(nombre or "").replace("-", " ").split() if p.strip()]
    if not palabras:
        return "JR"
    if len(palabras) == 1:
        return palabras[0][:2].upper()
    return (palabras[0][:1] + palabras[1][:1]).upper()


def _team_logo_html(nombre, logo_url="", gradient="linear-gradient(135deg, #29d764, #4f8cff)"):
    logo = str(logo_url or "").strip()
    iniciales = _team_initials(nombre)
    if logo:
        return (
            f"<div style=\"width:34px; height:34px; border-radius:999px; background:#ffffff; display:flex; "
            f"align-items:center; justify-content:center; overflow:hidden; border:1px solid rgba(255,255,255,.14);\">"
            f"<img src=\"{logo}\" style=\"width:100%; height:100%; object-fit:contain; background:#fff;\" /></div>"
        )
    return (
        f"<div style=\"width:34px; height:34px; border-radius:999px; background:{gradient}; display:flex; "
        f"align-items:center; justify-content:center; color:#07111d; font-weight:900;\">{iniciales}</div>"
    )


def _get_team_logo_cached(team_name):
    nombre = str(team_name or "").strip()
    if not nombre:
        return ""
    if "team_logo_cache" not in st.session_state:
        st.session_state.team_logo_cache = {}
    cache = st.session_state.team_logo_cache
    if nombre in cache:
        return cache[nombre]
    logo_db = get_cached_team_logo(nombre)
    if logo_db:
        cache[nombre] = logo_db
        st.session_state.team_logo_cache = cache
        return logo_db
    try:
        logo = buscar_logo_equipo(nombre)
    except Exception:
        logo = ""
    if logo:
        save_cached_team_logo(nombre, logo)
    cache[nombre] = logo or ""
    st.session_state.team_logo_cache = cache
    return cache[nombre]


def _render_pick_detail(row, section_key):
    partido = str(row.get("partido", "") or "Partido")
    mercado = str(row.get("mercado", "") or "Sin mercado")
    seleccion = str(row.get("seleccion", "") or "Sin seleccion")
    cuota = float(row.get("cuota", 0) or 0)
    confianza = int(float(row.get("confianza", 0) or 0) * 100)
    analisis = str(row.get("analisis_breve", "") or "").strip()
    ia = str(row.get("ia", "") or "Sistema")
    competicion = str(row.get("competicion", "") or "").strip()
    resultado = str(row.get("resultado", "") or "").strip()
    ganancia = float(row.get("ganancia", 0) or 0)
    local, visitante = _extraer_equipos_partido(partido)
    logo_local = row.get("logo_local") or row.get("home_logo") or row.get("team_logo_home") or ""
    logo_visitante = row.get("logo_visitante") or row.get("away_logo") or row.get("team_logo_away") or ""
    if not logo_local and local:
        logo_local = _get_team_logo_cached(local)
    if not logo_visitante and visitante:
        logo_visitante = _get_team_logo_cached(visitante)
    row_id = row.get("id", f"{partido}_{mercado}_{section_key}")
    with st.expander(f"Ver detalle | {partido} | {mercado}", expanded=False):
        st.markdown(
            f"""
            <div style="background:linear-gradient(135deg, #0f1725, #162234 72%, #192c39); border:1px solid rgba(255,255,255,.06); border-radius:24px; padding:20px; margin-bottom:14px;">
                <div style="display:flex; justify-content:space-between; gap:14px; flex-wrap:wrap; align-items:flex-start;">
                    <div>
                        <div style="color:#29d764; font-size:12px; font-weight:800; letter-spacing:1px; text-transform:uppercase;">Post del pick</div>
                        <div style="color:#f7f9fb; font-size:28px; font-weight:900; line-height:1.08; margin-top:8px;">{partido}</div>
                        <div style="color:#9fb0c5; font-size:15px; margin-top:10px;">{mercado}: {seleccion}</div>
                        <div style="display:flex; gap:12px; flex-wrap:wrap; margin-top:16px;">
                            <div style="display:flex; align-items:center; gap:10px; background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.06); border-radius:999px; padding:8px 12px;">
                                {_team_logo_html(local, logo_local, "linear-gradient(135deg, #29d764, #4f8cff)")}
                                <div style="color:#dbe5ee; font-size:13px; font-weight:700;">{local or "Local"}</div>
                            </div>
                            <div style="display:flex; align-items:center; gap:10px; background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.06); border-radius:999px; padding:8px 12px;">
                                {_team_logo_html(visitante, logo_visitante, "linear-gradient(135deg, #d6aa4c, #ff9150)")}
                                <div style="color:#dbe5ee; font-size:13px; font-weight:700;">{visitante or "Visitante"}</div>
                            </div>
                        </div>
                    </div>
                    <div style="background:linear-gradient(135deg, rgba(41,215,100,.18), rgba(214,170,76,.18)); border:1px solid rgba(255,255,255,.08); border-radius:20px; padding:14px 16px; min-width:180px;">
                        <div style="color:#8fa1b9; font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:1px;">Dato destacado</div>
                        <div style="color:#f7fbff; font-size:16px; font-weight:800; margin-top:8px;">Cuota {cuota:.2f} | Confianza {confianza}%</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        col_d1, col_d2, col_d3 = st.columns(3)
        col_d1.metric("Mercado", mercado)
        col_d2.metric("Seleccion", seleccion)
        col_d3.metric("Cuota", f"{cuota:.2f}")
        col_d4, col_d5, col_d6 = st.columns(3)
        col_d4.metric("Confianza", f"{confianza}%")
        col_d5.metric("Fuente", ia)
        col_d6.metric("Resultado", resultado or "Pendiente")
        if competicion:
            st.caption(f"Competicion: {competicion}")
        if analisis:
            st.markdown("**Lectura del pick**")
            st.write(analisis)
        if resultado and resultado != "pendiente":
            st.caption(f"Ganancia registrada: {ganancia:.2f}")
        try:
            from pdf_generator import generar_pdf_pick_social, generar_pdf_resultado_social
            from services.telegram_service import telegram_config_ok, enviar_paquete_telegram
            resumen = analisis[:220] + ("..." if len(analisis) > 220 else "") if analisis else "Lectura breve del sistema."
            if resultado and resultado != "pendiente":
                etiqueta = "WIN"
                if resultado.lower() == "perdida":
                    etiqueta = "LOSS"
                elif resultado.lower() == "media":
                    etiqueta = "PUSH"
                copy_social = _copy_resultado_social(row, etiqueta, cuota, ganancia)
                pdf_social = generar_pdf_resultado_social(row)
                social_name = f"resultado_social_{row_id}.pdf"
            else:
                copy_social = _copy_pick_social(row, resumen, confianza, cuota)
                pdf_social = generar_pdf_pick_social(row)
                social_name = f"pick_social_{row_id}.pdf"
            st.markdown("**Salida social individual**")
            col_s1, col_s2, col_s3 = st.columns(3)
            col_s1.download_button(
                "Descargar copy",
                copy_social,
                file_name=f"copy_social_{row_id}.txt",
                mime="text/plain",
                key=f"download_copy_{section_key}_{row_id}",
                use_container_width=True,
            )
            col_s2.download_button(
                "Descargar PDF social",
                pdf_social,
                file_name=social_name,
                mime="application/pdf",
                key=f"download_pdf_{section_key}_{row_id}",
                use_container_width=True,
            )
            if telegram_config_ok():
                if col_s3.button("Enviar a Telegram", key=f"send_tg_{section_key}_{row_id}", use_container_width=True):
                    ok, mensaje = enviar_paquete_telegram(copy_social, pdf_social, social_name, caption=f"{partido} | {mercado}")
                    if ok:
                        st.success(mensaje)
                    else:
                        st.error(mensaje)
        except Exception:
            pass


def _render_section_banner(title, text, chip=""):
    chip_html = (
        f"<div style='display:inline-block; background:rgba(41,215,100,.10); color:#5bf089; border:1px solid rgba(59,226,111,.16); border-radius:999px; padding:7px 12px; font-size:11px; font-weight:800; letter-spacing:1px; text-transform:uppercase; margin-bottom:10px;'>{chip}</div>"
        if chip else ""
    )
    st.markdown(
        f"""
        <div style="background:linear-gradient(135deg, rgba(255,255,255,.035), rgba(255,255,255,.02)); border:1px solid rgba(255,255,255,.06); border-radius:24px; padding:18px 20px; margin-bottom:14px;">
            {chip_html}
            <div style="color:#f7f9fb; font-size:22px; font-weight:900;">{title}</div>
            <div style="color:#9fb0c5; font-size:14px; line-height:1.6; margin-top:6px;">{text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _filtrar_df_por_periodo(df, periodo, fecha_col="fecha"):
    if df is None or df.empty or fecha_col not in df.columns or periodo == "Todo":
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    out = df.copy()
    fechas = pd.to_datetime(out[fecha_col], errors="coerce")
    hoy = pd.Timestamp(datetime.now().date())
    if periodo == "7 dias":
        mask = fechas >= (hoy - pd.Timedelta(days=7))
    elif periodo == "30 dias":
        mask = fechas >= (hoy - pd.Timedelta(days=30))
    elif periodo == "Mes actual":
        mask = (fechas.dt.year == hoy.year) & (fechas.dt.month == hoy.month)
    elif periodo == "Ano actual":
        mask = fechas.dt.year == hoy.year
    elif periodo == "Mes anterior":
        base = (hoy - pd.offsets.MonthBegin(1)).to_period("M")
        mask = fechas.dt.to_period("M") == base
    elif periodo == "Ano anterior":
        mask = fechas.dt.year == (hoy.year - 1)
    else:
        return out
    return out[mask.fillna(False)].copy()


def _resumen_periodo_dashboard(df_periodo):
    if df_periodo is None or df_periodo.empty:
        return {"total": 0, "cerrados": 0, "pendientes": 0, "roi": 0.0, "yield": 0.0, "acierto": 0.0}
    cerrados = df_periodo[df_periodo["resultado"].isin(["ganada", "perdida", "media"])].copy()
    pendientes = df_periodo[df_periodo["resultado"] == "pendiente"].copy()
    ganadas = int((cerrados["resultado"] == "ganada").sum()) if not cerrados.empty else 0
    medias = int((cerrados["resultado"] == "media").sum()) if not cerrados.empty else 0
    stake_sum = float(cerrados["stake"].sum()) if not cerrados.empty and "stake" in cerrados.columns else 0
    gan_sum = float(cerrados["ganancia"].sum()) if not cerrados.empty and "ganancia" in cerrados.columns else 0
    roi = round((gan_sum / stake_sum) * 100, 2) if stake_sum else 0.0
    acierto = round(((ganadas + medias / 2) / max(1, len(cerrados))) * 100, 1) if len(cerrados) else 0.0
    return {
        "total": len(df_periodo),
        "cerrados": len(cerrados),
        "pendientes": len(pendientes),
        "roi": roi,
        "yield": roi,
        "acierto": acierto,
    }


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

    df_publico = get_all_picks(incluir_alternativas=True)
    metrics = calcular_metricas(incluir_alternativas=False)
    total_picks = metrics.get("total_picks", 0)
    acierto = (metrics.get("ganadas", 0) + metrics.get("medias", 0) / 2) / max(1, total_picks) * 100
    roi = metrics.get("roi_global", 0)
    yield_global = metrics.get("yield_global", 0)

    pendientes = df_publico[
        (df_publico["tipo_pick"] == "principal")
        & (df_publico["resultado"] == "pendiente")
    ].copy() if not df_publico.empty else pd.DataFrame()
    cerrados = df_publico[
        (df_publico["tipo_pick"] == "principal")
        & (df_publico["resultado"].isin(["ganada", "perdida", "media"]))
    ].copy() if not df_publico.empty else pd.DataFrame()

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
                <div class="public-kpi"><div class="public-kpi-label">Picks</div><div class="public-kpi-value">{total_picks}</div></div>
                <div class="public-kpi"><div class="public-kpi-label">Win Rate</div><div class="public-kpi-value">{acierto:.1f}%</div></div>
                <div class="public-kpi"><div class="public-kpi-label">ROI</div><div class="public-kpi-value">{roi}%</div></div>
                <div class="public-kpi"><div class="public-kpi-label">Pendientes</div><div class="public-kpi-value">{len(pendientes)}</div></div>
            </div>
            <div class="public-chips">
                <div class="public-chip public-chip-muted">Picks oficiales</div>
                <div class="public-chip public-chip-muted">Resultados</div>
                <div class="public-chip public-chip-muted">Historico</div>
                <div class="public-chip public-chip-muted">Yield: {yield_global}%</div>
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
                usuario_actualizado = authenticate_user(usuario_publico.get("username", ""), st.session_state.get("public_last_password", ""))
                if usuario_actualizado:
                    st.session_state.public_user = usuario_actualizado
                else:
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
                st.session_state.public_last_password = clave_nueva
                st.success(mensaje)
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
                limite_pendientes = 6 if public_logged else 2
                for _, row in pendientes.head(limite_pendientes).iterrows():
                    cuota = float(row.get("cuota", 0) or 0)
                    confianza = int(float(row.get("confianza", 0) or 0) * 100)
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
                        meta_right=f"Confianza {confianza}%",
                        footer_hint=str(row.get("ia", "Analista")),
                    )
                    _render_pick_detail(row, "feed")
                if not public_logged and len(pendientes) > limite_pendientes:
                    st.info("Inicia sesion para ver todos los picks pendientes.")
            if not cerrados.empty:
                st.markdown("### Ultimos cierres")
                limite_cerrados = 4 if public_logged else 2
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
                    cuerpo = (
                        f"{row.get('mercado', '')}: {row.get('seleccion', '')}\n"
                        f"Cuota: {float(row.get('cuota', 0) or 0):.2f}\n"
                        f"Ganancia: {float(row.get('ganancia', 0) or 0):.2f}"
                    )
                    _render_public_card(
                        str(row.get("partido", "Partido")),
                        cuerpo,
                        etiqueta,
                        tono,
                        meta_left=f"{_market_icon(row.get('mercado', ''))} | {etiqueta}",
                        meta_right=f"Ganancia {float(row.get('ganancia', 0) or 0):.2f}",
                        footer_hint=str(row.get("ia", "Analista")),
                    )
                    _render_pick_detail(row, "feed")
                if not public_logged and len(cerrados) > limite_cerrados:
                    st.info("Accede con tu usuario para ver el historial reciente completo.")

    elif member_section == "Pendientes":
        _render_section_banner(
            "Picks pendientes",
            "Filtra los picks activos por mercado y revisa el detalle completo antes del cierre.",
            "Pendientes",
        )
        if not public_logged:
            st.warning("Pendientes completos solo para usuarios registrados.")
            st.info("Registrate o inicia sesion para acceder al detalle completo.")
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
        if not public_logged:
            st.warning("Resultados completos solo para usuarios registrados.")
            st.info("Inicia sesion para seguir todos los cierres y etiquetas del sistema.")
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
        if not public_logged:
            st.warning("El historico completo es exclusivo para usuarios registrados.")
            st.info("Crea una cuenta para ver la evolucion del sistema por dia, mes o ano.")
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
        with st.form("bootstrap_admin_form"):
            boot_user = st.text_input("Usuario admin")
            boot_name = st.text_input("Nombre visible")
            boot_email = st.text_input("Email admin")
            boot_pass = st.text_input("Clave admin", type="password")
            crear_bootstrap = st.form_submit_button("Crear admin inicial", use_container_width=True)
        if crear_bootstrap:
            ok, mensaje = create_user(boot_user, boot_name, boot_pass, boot_email, role="admin", must_change_password=True)
            if ok:
                st.success("Admin creado correctamente. Ahora inicia sesion.")
                st.rerun()
            else:
                st.error(mensaje)
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
    nueva_admin_pass = st.text_input("Nueva clave admin", type="password", key="admin_force_new_password")
    confirmar_admin_pass = st.text_input("Confirma la nueva clave", type="password", key="admin_force_confirm_password")
    if st.button("Actualizar clave admin"):
        if not nueva_admin_pass or len(nueva_admin_pass) < 8:
            st.error("La nueva clave debe tener al menos 8 caracteres.")
        elif nueva_admin_pass != confirmar_admin_pass:
            st.error("La confirmacion no coincide.")
        else:
            ok, mensaje = update_user_password(
                st.session_state.admin_user["id"],
                st.session_state.get("admin_last_password", ""),
                nueva_admin_pass,
            )
            if ok:
                st.session_state.admin_last_password = nueva_admin_pass
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

try:
    _df_admin_overview = get_all_picks(incluir_alternativas=True)
except Exception:
    _df_admin_overview = pd.DataFrame()

_pend_admin = _df_admin_overview[
    (_df_admin_overview["tipo_pick"] == "principal") & (_df_admin_overview["resultado"] == "pendiente")
].copy() if not _df_admin_overview.empty else pd.DataFrame()
_cerr_admin = _df_admin_overview[
    (_df_admin_overview["tipo_pick"] == "principal") & (_df_admin_overview["resultado"].isin(["ganada", "perdida", "media"]))
].copy() if not _df_admin_overview.empty else pd.DataFrame()
_users_count = len(df_usuarios) if not df_usuarios.empty else 0
_admin_kpis = calcular_metricas(incluir_alternativas=False)

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
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10, tab11, tab12 = st.tabs([
    "Panel General",
    "Carga de Picks",
    "Registro de Resultados",
    "Base y Exportacion",
    "Consulta de Cuotas",
    "Preparar Partido",
    "Analisis Automatico",
    "Consenso Ponderado",
    "Aprendizaje",
    "Comparativa Espejo",
    "Usuarios",
    "Motor Propio"
])

# ====================== DASHBOARD ======================
with tab1:
    incluir_alternativas = st.checkbox("Incluir picks alternativos en las metricas", value=False)
    metrics = calcular_metricas(incluir_alternativas=incluir_alternativas)
    df_dash = get_all_picks(incluir_alternativas=incluir_alternativas)
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
                    <div style="color:#f7fbff; font-size:18px; font-weight:900; margin-top:8px;">{len(picks_pendientes_dash)} pendientes | {len(picks_cerrados_dash)} cerrados</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3, col4 = st.columns(4)
    bankroll_cop = metrics['bankroll_actual']
    bankroll_inicial = get_bankroll_inicial()
    delta_pct = ((bankroll_cop / bankroll_inicial) - 1) * 100
    col1.metric("Bankroll Actual", mostrar_valor(bankroll_cop), f"{delta_pct:+.1f}%")
    total_picks_dash = len(df_dash_periodo)
    ganadas_dash = int((picks_cerrados_dash["resultado"] == "ganada").sum()) if not picks_cerrados_dash.empty else 0
    medias_dash = int((picks_cerrados_dash["resultado"] == "media").sum()) if not picks_cerrados_dash.empty else 0
    col2.metric("Total Picks", total_picks_dash)
    acierto_ponderado = (ganadas_dash + medias_dash/2) / max(1, len(picks_cerrados_dash)) * 100 if len(picks_cerrados_dash) else 0
    col3.metric("Acierto", f"{acierto_ponderado:.1f}%")
    roi_dash = round(float(picks_cerrados_dash["ganancia"].sum() / picks_cerrados_dash["stake"].sum() * 100), 2) if not picks_cerrados_dash.empty and picks_cerrados_dash["stake"].sum() else 0
    col4.metric("ROI Global", f"{roi_dash}%")
    col1b, col2b, col3b, col4b = st.columns(4)
    col1b.metric("Yield", f"{roi_dash}%")
    col2b.metric("Pendientes", len(picks_pendientes_dash))
    col3b.metric("Cerrados", len(picks_cerrados_dash))
    if not metrics['df_ia'].empty and "roi" in metrics["df_ia"].columns:
        df_ia_sorted = metrics["df_ia"].sort_values("roi", ascending=False)
        ia_top = str(df_ia_sorted.iloc[0].get("ia", "-"))
        roi_ia_top = float(df_ia_sorted.iloc[0].get("roi", 0) or 0)
    else:
        ia_top = "-"
        roi_ia_top = 0
    col4b.metric("IA top", ia_top, f"{roi_ia_top:.1f}%")

    st.subheader("Metricas avanzadas de riesgo")
    riesgo = metrics['metricas_riesgo']
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
        st.info("No hay informacion suficiente para calcular metricas de riesgo.")

    colA, colB = st.columns(2)
    with colA:
        if not metrics['evolucion'].empty:
            fig_bank = px.line(metrics['evolucion'], x='fecha', y='bankroll',
                               title="Evolucion del Bankroll", markers=True)
            st.plotly_chart(fig_bank, width='stretch')
        else:
            st.info("No hay informacion suficiente para visualizar la evolucion del bankroll.")
    with colB:
        if not metrics['df_ia'].empty:
            fig_roi = px.bar(metrics['df_ia'], x='ia', y='roi',
                             title="ROI por IA", color='roi', color_continuous_scale='RdYlGn')
            st.plotly_chart(fig_roi, width='stretch')
        else:
            st.info("No hay informacion suficiente para calcular ROI por IA.")

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
with tab2:
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
            st.warning("Completa al menos partido, mercado y seleccion.")
        else:
            try:
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
                        "competicion": pm_competicion.strip() or None,
                        "tipo_pick": pm_tipo,
                    }
                ])
                batch_manual = datetime.now().strftime("%Y%m%d_%H%M%S") + "_manual"
                resultado_manual = save_picks(df_manual, batch_manual)
                insertados = resultado_manual.get("insertados", 0) if isinstance(resultado_manual, dict) else 0
                duplicados = resultado_manual.get("duplicados", 0) if isinstance(resultado_manual, dict) else 0
                if insertados > 0:
                    pick_publicado = None
                    if pm_tipo == "principal":
                        df_lote = get_all_picks(incluir_alternativas=True)
                        lote = df_lote[df_lote["import_batch"] == batch_manual].copy() if not df_lote.empty and "import_batch" in df_lote.columns else pd.DataFrame()
                        if not lote.empty:
                            pick_publicado = lote.iloc[0].to_dict()
                    st.success(
                        f"Pick manual guardado. Insertados: {insertados} | Duplicados: {duplicados} | batch: {batch_manual}"
                    )
                    if pick_publicado:
                        auto_pub = _enviar_pick_telegram_si_activo(pick_publicado)
                        if auto_pub:
                            ok, mensaje = auto_pub
                            if ok:
                                st.success(f"Auto-publicacion Telegram: {mensaje}")
                            else:
                                st.warning(mensaje)
                else:
                    st.warning(
                        f"No se insertaron picks nuevos. Duplicados detectados: {duplicados}."
                    )
                st.rerun()
            except Exception as e:
                st.error(f"No se pudo guardar el pick manual: {e}")

# ====================== REGISTRAR RESULTADOS ======================
with tab3:
    df = get_all_picks(incluir_alternativas=True)
    if df.empty:
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
                            st.success(f"Registro actualizado: {row['seleccion']} -> {nuevo} @ {cuota_real}")
                            actualizado = get_all_picks(incluir_alternativas=True)
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
with tab4:
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
    df_publicacion = get_all_picks(incluir_alternativas=True)
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
    df_pick_oficial = get_all_picks(incluir_alternativas=True)
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
    df_resultado_post = get_all_picks(incluir_alternativas=True)
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
    df_boletin = get_all_picks(incluir_alternativas=True)
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

        if df_export.empty:
            st.info("No hay picks en la base con ese filtro para generar boletin.")
        else:
            st.caption(f"Picks incluidos en el boletin: {len(df_export)}")
            if st.button("Generar PDF desde la base"):
                with st.spinner("Preparando boletin PDF..."):
                    try:
                        pdf_base = generar_pdf_desde_dataframe(
                            df_export,
                            titulo=titulo_boletin,
                            subtitulo=subtitulo_boletin,
                        )
                        fecha_pdf = datetime.now().strftime("%Y%m%d_%H%M")
                        st.download_button(
                            "Descargar boletin PDF",
                            data=pdf_base,
                            file_name=f"boletin_picks_{fecha_pdf}.pdf",
                            mime="application/pdf",
                        )
                        if telegram_config_ok():
                            ok, mensaje = enviar_documento_telegram(
                                pdf_base,
                                f"boletin_picks_{fecha_pdf}.pdf",
                                caption=titulo_boletin,
                            )
                            if ok:
                                st.success(f"Boletin PDF generado y enviado a Telegram.")
                            else:
                                st.warning(f"Boletin generado, pero Telegram fallo: {mensaje}")
                        st.success("Boletin PDF generado correctamente desde la base.")
                    except Exception as e:
                        st.error(f"Error al generar el boletin desde la base: {e}")
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
    df = get_all_picks(incluir_alternativas=True)
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
        st.info("No hay datos disponibles. Carga picks para continuar.")

# ====================== CUOTAS REALES ======================
with tab5:
    st.subheader("Consulta operativa de cuotas")

    from obtener_cuotas_api import obtener_ligas_futbol, obtener_cuotas_de_liga, obtener_creditos_restantes
    from config import ODDS_API_KEY

    if 'liga_actual' not in st.session_state:
        st.session_state.liga_actual = None
    if 'partidos_disponibles' not in st.session_state:
        st.session_state.partidos_disponibles = []
    if 'busqueda_realizada' not in st.session_state:
        st.session_state.busqueda_realizada = False
    if 'nombre_buscado' not in st.session_state:
        st.session_state.nombre_buscado = ""

    if not ODDS_API_KEY:
        st.error("No has configurado la API key de The Odds API. Revisa el archivo .env.")
        st.stop()

    # Deteccion automatica de liga
    nombre_partido_input = st.text_input("Nombre del partido (ej: Atletico Nacional vs Millonarios)", key="nombre_input_cuotas")
    if nombre_partido_input:
        liga_detectada_key, liga_detectada_nombre = detectar_liga_automatica(nombre_partido_input)
        if liga_detectada_key:
            st.success(f"Liga detectada automaticamente: **{liga_detectada_nombre}**")

    with st.spinner("Cargando ligas..."):
        ligas = obtener_ligas_futbol()
        if ligas is None:
            st.error("Error al cargar ligas. Revisa tu conexion o API key.")
            st.stop()
        else:
            nombres_ligas = [f"{liga['title']} ({liga['key']})" for liga in ligas]
            nombres_ligas.insert(0, "Liga BetPlay (soccer_colombia_primera_a)")
            nombres_ligas.insert(1, "Primera B (soccer_colombia_primera_b)")
            nombres_ligas.insert(2, "Champions League (soccer_uefa_champions_league)")
            nombres_ligas.insert(3, "Copa Libertadores (soccer_conmebol_libertadores)")

            # Si se detecto automaticamente, preseleccionar
            idx_default = 0
            if nombre_partido_input and liga_detectada_key:
                for i, nl in enumerate(nombres_ligas):
                    if liga_detectada_key in nl:
                        idx_default = i
                        break

            liga_seleccionada = st.selectbox("Liga", nombres_ligas, index=idx_default, key="liga_selector")
            liga_key = liga_seleccionada.split('(')[-1].strip(')')

            region = st.selectbox("Region", ["eu", "uk", "us", "au"],
                                  help="'eu' para casas europeas como Betsson. 'uk' para Bet365.")
            bookmaker_filtro = st.text_input("Casa de apuestas (vacio = todas)")
            st.session_state.bookmaker_filtro = bookmaker_filtro.strip()
            nombre_partido = nombre_partido_input or st.text_input("Nombre del partido", key="nombre_input2")

            if st.button("Buscar partido"):
                st.session_state.busqueda_realizada = True
                st.session_state.nombre_buscado = nombre_partido
                st.session_state.liga_actual = liga_key
                st.session_state.region_actual = region
                st.session_state.partidos_disponibles = []
                st.rerun()

            if st.session_state.busqueda_realizada and st.session_state.liga_actual == liga_key:
                with st.spinner(f"Buscando..."):
                    archivo, error, partidos = obtener_cuotas_de_liga(
                        st.session_state.liga_actual,
                        st.session_state.nombre_buscado,
                        region=st.session_state.region_actual,
                        bookmaker_filtro=st.session_state.get("bookmaker_filtro", "")
                    )
                    if archivo:
                        st.success(f"Partido localizado. Archivo generado: {archivo}")
                        with open(archivo, "rb") as f:
                            st.download_button("Descargar archivo", f, archivo, "text/plain")
                        with open(archivo, "r", encoding="utf-8") as f:
                            st.text_area("Vista previa:", f.read(), height=300)
                        st.session_state.busqueda_realizada = False
                    elif partidos:
                        st.warning(f"No se encontro '{st.session_state.nombre_buscado}'.")
                        st.info("Partidos disponibles para seleccion:")
                        st.session_state.partidos_disponibles = partidos
                    else:
                        st.error(f"Error: {error}")
                        st.session_state.busqueda_realizada = False

            if st.session_state.partidos_disponibles:
                partido_elegido = st.selectbox("Selecciona un partido:", st.session_state.partidos_disponibles)
                if st.button("Usar este partido"):
                    st.session_state.nombre_buscado = partido_elegido
                    st.session_state.busqueda_realizada = True
                    st.session_state.partidos_disponibles = []
                    st.rerun()

    # Seccion manual para mercados no disponibles en API (corners, tarjetas)
    st.markdown("---")
    st.subheader("Registro manual de cuotas")
    st.markdown("Utiliza este bloque para mercados especiales como **corners**, **tarjetas** o **BTTS** que no esten disponibles en la API.")
    with st.expander("Abrir formulario manual"):
        m_partido = st.text_input("Partido")
        m_mercado = st.text_input("Mercado (ej: Corners Over 9.5)")
        col_m1, col_m2, col_m3 = st.columns(3)
        m_c1 = col_m1.number_input("Cuota opcion 1", min_value=1.01, value=1.90, step=0.01)
        m_c2 = col_m2.number_input("Cuota opcion 2", min_value=1.01, value=1.90, step=0.01)
        m_c3 = col_m3.number_input("Cuota opcion 3 (opcional)", min_value=1.01, value=1.01, step=0.01)
        m_fuente = st.selectbox("Casa de apuestas", ["Bet365", "Betano", "RushBet", "Pinnacle", "Betsson", "Otra"])
        if st.button("Guardar cuotas manuales"):
            if m_partido and m_mercado:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M")
                nombre_archivo = f"cuotas/manual_{m_partido.replace(' ', '_')}_{timestamp}.txt"
                os.makedirs("cuotas", exist_ok=True)
                with open(nombre_archivo, "w", encoding="utf-8") as f:
                    f.write(f"# CUOTAS MANUALES - {m_partido}\n")
                    f.write(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
                    f.write(f"Fuente: {m_fuente}\n\n")
                    f.write(f"--- {m_fuente.upper()} ---\n")
                    f.write(f"{m_mercado} - Opcion 1: {m_c1}\n")
                    f.write(f"{m_mercado} - Opcion 2: {m_c2}\n")
                    if m_c3 > 1.01:
                        f.write(f"{m_mercado} - Opcion 3: {m_c3}\n")
                st.success(f"Cuotas guardadas en {nombre_archivo}")
            else:
                st.warning("Completa al menos el nombre del partido y el mercado objetivo.")

# ====================== PREPARAR PARTIDO ======================
with tab6:
    st.subheader("Preparar Partido")
    st.markdown(
        "Automatiza la recoleccion previa del partido con **API-Football**, completa los campos "
        "que siguen siendo manuales y genera una ficha lista para el motor automatico."
    )
    api_status = "Conectada" if API_FOOTBALL_KEY else "Sin key"
    st.markdown(
        f"""
        <div style="background:radial-gradient(circle at top right, rgba(41,215,100,.12), transparent 34%), linear-gradient(135deg, #0d1523, #121a28 68%, #172437); border:1px solid rgba(255,255,255,.06); border-radius:28px; padding:22px 24px; margin-bottom:16px;">
            <div style="display:flex; justify-content:space-between; gap:18px; flex-wrap:wrap; align-items:flex-start;">
                <div>
                    <div style="display:inline-block; background:rgba(41,215,100,.10); color:#5bf089; border:1px solid rgba(59,226,111,.16); border-radius:999px; padding:7px 12px; font-size:11px; font-weight:800; letter-spacing:1px; text-transform:uppercase; margin-bottom:10px;">Centro de preparacion</div>
                    <div style="color:#f7f9fb; font-size:28px; font-weight:900; line-height:1.08;">Arma la ficha del partido antes del analisis</div>
                    <div style="color:#9fb0c5; font-size:15px; margin-top:8px;">Paso 1: localiza el fixture. Paso 2: valida lo que trajo la API. Paso 3: completa xG, ELO y contexto. Paso 4: genera la ficha final.</div>
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
    if "motor_pick_result" not in st.session_state:
        st.session_state.motor_pick_result = None
    if "motor_context_result" not in st.session_state:
        st.session_state.motor_context_result = None

    step_actual = st.session_state.get("prepared_match_step", 1)
    st.caption("Pasos del flujo")
    step_cols = st.columns(4)
    if step_cols[0].button("1. Buscar fixture", use_container_width=True, type="primary" if step_actual == 1 else "secondary", key="prep_step_1"):
        st.session_state.prepared_match_step = 1
        st.rerun()
    if step_cols[1].button("2. Revisar API", use_container_width=True, type="primary" if step_actual == 2 else "secondary", key="prep_step_2"):
        st.session_state.prepared_match_step = 2
        st.rerun()
    if step_cols[2].button("3. Completar manual", use_container_width=True, type="primary" if step_actual == 3 else "secondary", key="prep_step_3"):
        st.session_state.prepared_match_step = 3
        st.rerun()
    if step_cols[3].button("4. Generar ficha", use_container_width=True, type="primary" if step_actual == 4 else "secondary", key="prep_step_4"):
        st.session_state.prepared_match_step = 4
        st.rerun()

    entrada_partido = st.text_input(
        "Partido a preparar",
        value=st.session_state.get("prepared_match_input", ""),
        placeholder="Ej: Atletico Nacional vs Llaneros - 14/03/2026",
        key="prep_match_input",
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

    if col_p3.button("Consultar API-Football", type="primary", use_container_width=True):
        if not entrada_partido.strip():
            st.warning("Escribe primero el partido.")
        else:
            st.session_state.prepared_match_input = entrada_partido.strip()
            with st.spinner("Consultando fixture, forma, H2H, tabla, lesiones, alineaciones y odds..."):
                datos_prep, error_prep = preparar_partido_desde_api(
                    entrada_partido.strip(),
                    fecha_iso=fecha_iso_manual,
                    liga_key=liga_detectada_key,
                )
            if error_prep:
                st.error(f"No se pudo preparar el partido: {error_prep}")
                st.session_state.prepared_match_data = None
            else:
                nuevo_fixture_id = datos_prep.get("fixture_id")
                fixture_anterior = st.session_state.get("prepared_match_fixture_loaded")
                if nuevo_fixture_id and nuevo_fixture_id != fixture_anterior:
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
                        "prep_motivacion_local",
                        "prep_motivacion_visitante",
                        "prep_contexto_extra",
                    ]
                    for clave_reset in prep_keys_to_reset:
                        if clave_reset in st.session_state:
                            del st.session_state[clave_reset]
                st.session_state.prepared_match_data = datos_prep
                st.session_state.prepared_match_fixture_loaded = nuevo_fixture_id
                st.session_state.prepared_match_step = 2
                st.success("Partido localizado y datos base cargados.")
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
            ("Alineaciones", _estado_compuesto(debug_api.get("alineaciones", {}).get("ok"))),
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
                st.dataframe(
                    pd.DataFrame(resumen_bloques, columns=["Bloque", "Estado"]),
                    width="stretch",
                    hide_index=True,
                )
            with col_e2:
                st.markdown("**Campos que aun debes completar manualmente**")
                st.write("- xG local")
                st.write("- xG visitante")
                st.write("- ELO local")
                st.write("- ELO visitante")
                st.write("- Motivacion / contexto local")
                st.write("- Motivacion / contexto visitante")
                st.write("- Contexto adicional del partido")
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
        for item in lineups_api:
            equipo_norm = str(item.get("equipo", "")).strip().lower()
            titulares = ", ".join([x for x in item.get("titulares", []) if x])
            bloque = f"Formacion: {item.get('formacion', '')}\nTitulares: {titulares}"
            if equipo_norm == str(home_api.get("equipo", "")).strip().lower():
                lineup_local_api_txt = bloque
            elif equipo_norm == str(away_api.get("equipo", "")).strip().lower():
                lineup_visit_api_txt = bloque
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

        st.markdown("---")
        st.subheader("1. Lo que realmente trajo la API")
        st.caption("Esta zona es solo lectura. Aqui ves exactamente lo que llego antes de tocar nada manualmente.")
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
                if "Free plans do not have access" in detalle:
                    plan_limit_msgs.append(f"{etiquetas_debug.get(clave, clave)}: {detalle}")
                debug_rows.append(
                    {
                        "Bloque": etiquetas_debug.get(clave, clave),
                        "Estado": "OK" if info.get("ok") else "Sin datos",
                        "Detalle": detalle,
                    }
                )
            if plan_limit_msgs:
                st.warning(
                    "Tu plan free de API-Football esta limitando varios bloques para esta temporada/consulta.\n\n"
                    + "\n".join(f"- {msg}" for msg in plan_limit_msgs)
                )
            st.markdown("**Diagnostico de respuesta API**")
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
        st.caption("Aqui corriges lo que vino mal, llenas lo vacio y dejas lista la ficha final. Si un campo vino desde API, aparecera precargado.")
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
        df_api_editor = st.data_editor(
            df_api_editor,
            width="stretch",
            hide_index=True,
            key="prep_data_editor",
            disabled=["Equipo"],
            use_container_width=True,
        )

        st.markdown("**Bloques editables o completables**")
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
        arbitro_manual = st.text_input(
            "Arbitro",
            key="prep_arbitro_manual",
            value=str(datos_preparados.get("arbitro", "") or ""),
            placeholder="Ej: Andres Rojas",
        )
        col_form1, col_form2 = st.columns(2)
        forma_local_manual = col_form1.text_area(
            f"Forma reciente {home_api.get('equipo', 'Local')}",
            key="prep_forma_local_manual",
            value=home_forma_txt,
            height=130,
            placeholder="Fecha | Rival | Marcador",
        )
        forma_visitante_manual = col_form2.text_area(
            f"Forma reciente {away_api.get('equipo', 'Visitante')}",
            key="prep_forma_visit_manual",
            value=away_forma_txt,
            height=130,
            placeholder="Fecha | Rival | Marcador",
        )
        h2h_manual = st.text_area(
            "H2H ultimos enfrentamientos",
            key="prep_h2h_manual",
            value=h2h_txt,
            height=120,
            placeholder="Fecha | Partido | Marcador",
        )
        col_les1, col_les2 = st.columns(2)
        lesiones_local_manual = col_les1.text_area(
            "Lesiones / suspensiones local",
            key="prep_lesiones_local_manual",
            value=lesiones_local_api_txt,
            height=90,
            placeholder="Jugadores ausentes o suspensiones",
        )
        lesiones_visitante_manual = col_les2.text_area(
            "Lesiones / suspensiones visitante",
            key="prep_lesiones_visitante_manual",
            value=lesiones_visit_api_txt,
            height=90,
            placeholder="Jugadores ausentes o suspensiones",
        )
        col_al1, col_al2 = st.columns(2)
        alineacion_local_manual = col_al1.text_area(
            "Alineacion probable local",
            key="prep_alineacion_local_manual",
            value=lineup_local_api_txt,
            height=90,
            placeholder="Formacion y titulares probables",
        )
        alineacion_visitante_manual = col_al2.text_area(
            "Alineacion probable visitante",
            key="prep_alineacion_visitante_manual",
            value=lineup_visit_api_txt,
            height=90,
            placeholder="Formacion y titulares probables",
        )
        cuotas_manual_resumen = st.text_area(
            "Cuotas / resumen de mercado",
            key="prep_cuotas_manual_resumen",
            value=odds_api_txt,
            height=120,
            placeholder="Ej: 1X2 Bet365: Local 1.80, Empate 3.40, Visitante 4.90\nOver 2.5: 1.95 | Under 2.5: 1.80\nBTTS: Si 1.87 | No 1.90",
        )

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

        if step_actual >= 3:
            st.markdown("---")
            st.subheader("Campos manuales que completan los 8 sistemas")
        col_m1, col_m2 = st.columns(2)
        xg_local = col_m1.text_input("xG local", key="prep_xg_local", placeholder="Ej: 1.62")
        xg_visitante = col_m2.text_input("xG visitante", key="prep_xg_visitante", placeholder="Ej: 0.94")
        col_m3, col_m4 = st.columns(2)
        elo_local = col_m3.text_input("ELO local", key="prep_elo_local", placeholder="Ej: 1642")
        elo_visitante = col_m4.text_input("ELO visitante", key="prep_elo_visitante", placeholder="Ej: 1510")
        st.caption("Si no quieres redactar el contexto a mano, puedes pedirle a Ollama local que te lo sugiera con lo que ya trae la ficha.")
        ctx_auto_1, ctx_auto_2 = st.columns([1.2, 1])
        if ctx_auto_1.button("Autocompletar contexto con Ollama", use_container_width=True):
            contexto_fuente = "\n".join(
                [
                    f"Partido: {datos_preparados.get('partido', '')}",
                    f"Fecha: {datos_preparados.get('fecha', '')}",
                    f"Liga: {datos_preparados.get('liga_nombre', '')}",
                    f"Arbitro: {arbitro_manual or datos_preparados.get('arbitro', '')}",
                    f"Forma local: {forma_local_manual or str(home_api_resuelto.get('forma', []))}",
                    f"Forma visitante: {forma_visitante_manual or str(away_api_resuelto.get('forma', []))}",
                    f"H2H: {h2h_manual or str(datos_preparados.get('h2h', []))}",
                    f"Lesiones local: {lesiones_local_manual or str(home_api_resuelto.get('lesiones', []))}",
                    f"Lesiones visitante: {lesiones_visitante_manual or str(away_api_resuelto.get('lesiones', []))}",
                    f"Alineacion local: {alineacion_local_manual or str((datos_preparados.get('lineups') or {}).get('home', ''))}",
                    f"Alineacion visitante: {alineacion_visitante_manual or str((datos_preparados.get('lineups') or {}).get('away', ''))}",
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
                f"Forma local: {forma_local_manual or str(home_api_resuelto.get('forma', []))}",
                f"Forma visitante: {forma_visitante_manual or str(away_api_resuelto.get('forma', []))}",
                f"H2H: {h2h_manual or str(datos_preparados.get('h2h', []))}",
                f"Lesiones local: {lesiones_local_manual or str(home_api_resuelto.get('lesiones', []))}",
                f"Lesiones visitante: {lesiones_visitante_manual or str(away_api_resuelto.get('lesiones', []))}",
                f"Alineacion local: {alineacion_local_manual or str((datos_preparados.get('lineups') or {}).get('home', ''))}",
                f"Alineacion visitante: {alineacion_visitante_manual or str((datos_preparados.get('lineups') or {}).get('away', ''))}",
            ]
        ).strip()

        completos_manual = sum(
            1 for clave, valor in manual_data.items() if not clave.endswith("_fallback") and str(valor or "").strip()
        )
        if step_actual == 3 and completos_manual >= 4:
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

        if step_actual >= 4:
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
                "Estado": "Completo" if (datos_preparados.get("lineups") or alineacion_local_manual.strip() or alineacion_visitante_manual.strip()) else "Pendiente",
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
        if step_actual < 4 and cobertura_pct >= 70:
            st.info("La cobertura ya esta alta. Puedes entrar al paso 4 para generar la ficha final.")
        if step_actual >= 4:
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
                if not str(motivacion_local or "").strip() and not str(motivacion_visitante or "").strip() and not str(contexto_extra or "").strip():
                    sugerencia_auto, error_auto = sugerir_campos_contexto_ollama(contexto_fuente_prep)
                    if sugerencia_auto and not error_auto:
                        motivacion_local = sugerencia_auto.get("motivacion_local", "")
                        motivacion_visitante = sugerencia_auto.get("motivacion_visitante", "")
                        contexto_extra = sugerencia_auto.get("contexto_adicional", "")
                        st.session_state.prep_motivacion_local = motivacion_local
                        st.session_state.prep_motivacion_visitante = motivacion_visitante
                        st.session_state.prep_contexto_extra = contexto_extra
                datos_ficha = dict(datos_preparados)
                datos_ficha["home"] = home_api_resuelto
                datos_ficha["away"] = away_api_resuelto
                manual_data["motivacion_local"] = motivacion_local
                manual_data["motivacion_visitante"] = motivacion_visitante
                manual_data["contexto_extra"] = contexto_extra
                ficha_generada = construir_ficha_preparada(datos_ficha, manual_data)
                st.session_state.prepared_match_manual_data = dict(manual_data)
                st.session_state.prepared_match_text = ficha_generada
                st.session_state.prompt_auto = ficha_generada
                save_prepared_match(
                    datos_preparados.get("partido", ""),
                    datos_preparados.get("fecha", ""),
                    datos_preparados.get("liga_nombre", ""),
                    round(cobertura_pct, 2),
                    ficha_generada,
                )
                if str(motivacion_local or "").strip() or str(motivacion_visitante or "").strip() or str(contexto_extra or "").strip():
                    st.success("Ficha estructurada generada y cargada para Analisis Automatico.")
                else:
                    st.success("Ficha estructurada generada y cargada para Analisis Automatico.")

            if col_g2.button("Limpiar partido preparado", use_container_width=True):
                st.session_state.prepared_match_data = None
                st.session_state.prepared_match_fixture_loaded = None
                st.session_state.prepared_match_manual_data = {}
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

# ====================== ANALISIS AUTOMATICO ======================
with tab7:
    _render_section_banner(
        "Analisis automatico",
        "Lanza el motor multi-IA, audita calidad, revisa consenso y decide si el escenario merece guardarse o publicarse.",
        "Motor IA",
    )
    st.subheader("Motor de analisis automatico Multi-IA")
    st.markdown(
        "Envia el analisis base del Investigador a **7 analistas automaticos** en paralelo. "
        "Cada motor opera con un perfil distinto y el modulo de consenso consolida los resultados."
    )

    # Estado de APIs
    try:
        from ai_providers import ejecutar_analisis_automatico, verificar_apis_configuradas, PERSONALIDADES
        apis_ok = verificar_apis_configuradas()
        cols_api = st.columns(len(apis_ok))
        for i, (nombre, estado) in enumerate(apis_ok.items()):
            icono = "OK" if estado else "NO"
            cols_api[i].metric(nombre, icono)
        api_disponibles = sum(1 for v in apis_ok.values() if v)
        api_no_disponibles = len(apis_ok) - api_disponibles
        s1, s2, s3 = st.columns(3)
        s1.metric("Proveedores listos", api_disponibles)
        s2.metric("Proveedores con fallo", api_no_disponibles)
        s3.metric("Analistas esperados", len(PERSONALIDADES))
    except ImportError:
        st.error("No se encontro ai_providers.py. Asegurate de haberlo anadido al proyecto.")
        st.stop()

    st.markdown("---")

    # Personalidades disponibles
    with st.expander("Ver perfiles de los analistas automaticos"):
        for nombre, datos in PERSONALIDADES.items():
            st.markdown(f"**{nombre}**: {datos['descripcion']}")

    st.markdown("---")

    # Input del analisis
    st.markdown("### Pega aqui el analisis del Investigador (Perplexity)")
    prompt_investigador = st.text_area(
        "Analisis completo del Investigador",
        height=300,
        placeholder="Pega aqui el output del Investigador v3.0 con todos los datos del partido...",
        key="prompt_auto"
    )

    if "auto_resultados_cache" not in st.session_state:
        st.session_state.auto_resultados_cache = None
    if "auto_error_cache" not in st.session_state:
        st.session_state.auto_error_cache = None
    if "auto_import_feedback" not in st.session_state:
        st.session_state.auto_import_feedback = None

    if st.button("Ejecutar analisis automatico", type="primary"):
        if not prompt_investigador.strip():
            st.warning("Carga primero el analisis base del Investigador.")
        else:
            try:
                prompt_base = cargar_prompt_automatico()
                prompt_final = prompt_base.replace(
                    "[resumen compacto del investigador]",
                    prompt_investigador.strip(),
                )
            except FileNotFoundError:
                st.error("No se encontro el prompt automatico del analista en 01_PROMPTS/automatizacion.")
                st.stop()

            import time
            import queue as queue_module
            import threading

            t_inicio = time.time()
            cola = queue_module.Queue()
            resultado_container = [None]

            def correr():
                def on_resultado(r):
                    cola.put(r)
                resultado_container[0] = ejecutar_analisis_automatico(prompt_final, callback=on_resultado)
                cola.put("__FIN__")

            hilo = threading.Thread(target=correr)
            hilo.start()

            # Panel de estado en tiempo real
            st.markdown("#### Estado de ejecucion en tiempo real")
            estados = {}
            panel = st.empty()

            def render_panel():
                filas = ["| IA | Estado | Tiempo | Decision |", "|---|---|---|---|"]
                for nombre, info in estados.items():
                    t = info.get("tiempo", "?")
                    if info["estado"] == "esperando":
                        filas.append(f"| {nombre} | En espera | {t}s | ... |")
                    elif info["estado"] == "ok":
                        decision = info.get("decision", "?")
                        estado_label = "Procesado" if decision == "PICK" else "Sin entrada"
                        filas.append(f"| {nombre} | {estado_label} | {t}s | **{decision}** |")
                    else:
                        filas.append(f"| {nombre} | Error | {t}s | - |")
                panel.markdown("\n".join(filas) if len(filas) > 2 else "Iniciando...")

            # Inicializar todos como esperando
            from ai_providers import PERSONALIDADES
            for nombre in PERSONALIDADES:
                estados[nombre] = {"estado": "esperando", "tiempo": 0}
            render_panel()

            while True:
                # Actualizar tiempos
                ahora = int(time.time() - t_inicio)
                for nombre in estados:
                    if estados[nombre]["estado"] == "esperando":
                        estados[nombre]["tiempo"] = ahora

                try:
                    item = cola.get(timeout=1)
                    if item == "__FIN__":
                        break
                    ia = item.get("ia", "desconocida")
                    t_ia = int(time.time() - t_inicio)
                    if item.get("status") == "ok":
                        decision = item.get("data", {}).get("decision", "?")
                        estados[ia] = {"estado": "ok", "tiempo": t_ia, "decision": decision}
                    else:
                        estados[ia] = {"estado": "error", "tiempo": t_ia}
                except:
                    pass

                render_panel()

            hilo.join()
            panel.empty()
            resultados, error = resultado_container[0]

            st.session_state.auto_resultados_cache = resultados
            st.session_state.auto_error_cache = error
            st.session_state.auto_import_feedback = None

    resultados = st.session_state.auto_resultados_cache
    error = st.session_state.auto_error_cache

    if st.session_state.auto_import_feedback:
        feedback = st.session_state.auto_import_feedback
        if feedback.get("tipo") == "ok":
            st.success(feedback.get("mensaje", "Importacion completada."))
        else:
            st.error(feedback.get("mensaje", "Error en la importacion."))

    if resultados is not None:
        if error:
            st.error(f"Error: {error}")
        else:
            st.success(f"{len(resultados)} analistas respondieron correctamente")

            picks_validos = []
            errores_ia = []
            picks_invalidos = []

            for r in resultados:
                if r.get("status") == "ok":
                    if r.get("valid", True):
                        picks_validos.append(r["data"])
                    else:
                        picks_invalidos.append(r)
                else:
                    errores_ia.append(r)

            if errores_ia:
                with st.expander(f"{len(errores_ia)} IAs con incidencias"):
                    for e in errores_ia:
                        st.error(f"**{e.get('ia', 'desconocida')}**: {e.get('error', 'error desconocido')}")
                        raw_error = e.get("raw_output", "")
                        if raw_error:
                            st.text_area(
                                f"Salida cruda con error - {e.get('ia', 'desconocida')}",
                                value=raw_error,
                                height=180,
                                key=f"raw_error_{e.get('ia', 'desconocida')}",
                                )

            if picks_invalidos:
                with st.expander(f"{len(picks_invalidos)} IAs descartadas por validacion"):
                    for item in picks_invalidos:
                        st.warning(f"**{item.get('ia', 'desconocida')}** no entro al consenso.")
                        errores_val = item.get("validation_errors", [])
                        if errores_val:
                            for err in errores_val:
                                st.write(f"- {err}")
                        raw_invalid = item.get("raw_output", "")
                        if raw_invalid:
                            st.text_area(
                                f"Salida cruda descartada - {item.get('ia', 'desconocida')}",
                                value=raw_invalid,
                                height=180,
                                key=f"raw_invalid_{item.get('ia', 'desconocida')}",
                            )

            if picks_validos:
                picks_auditados = []
                for p in picks_validos:
                    auditoria = _auditar_pick_automatico(p)
                    p["_mercado_norm"] = auditoria["mercado_norm"]
                    p["_seleccion_norm"] = auditoria["seleccion_norm"]
                    p["_alertas_calidad"] = auditoria["alertas"]
                    p["_calidad"] = auditoria["calidad"]
                    picks_auditados.append(p)

                picks_emitidos = [p for p in picks_auditados if p.get("decision") == "PICK"]
                no_bets = [p for p in picks_auditados if p.get("decision") == "NO BET"]
                picks_solidos = len([p for p in picks_auditados if p.get("_calidad") == "Solido"])
                picks_revisar = len([p for p in picks_auditados if p.get("_calidad") == "Revisar"])
                picks_debiles = len([p for p in picks_auditados if p.get("_calidad") == "Debil"])
                quorum_minimo = 4
                quorum_ok = len(picks_validos) >= quorum_minimo

                st.markdown("---")
                st.subheader("Resumen ejecutivo del motor")
                res1, res2, res3, res4, res5 = st.columns(5)
                res1.metric("Validos", len(picks_validos))
                res2.metric("Picks", len(picks_emitidos))
                res3.metric("NO BET", len(no_bets))
                res4.metric("Solidos", picks_solidos)
                res5.metric("Quorum", "OK" if quorum_ok else "Bajo")

                st.markdown("---")
                st.subheader("Resultados por analista")

                # Tabla resumen
                filas_resumen = []
                for p in picks_auditados:
                    filas_resumen.append({
                        "IA": p.get("ia", "?"),
                        "Decision": p.get("decision", "?"),
                        "Mercado": p.get("_mercado_norm", p.get("mercado", "?")),
                        "Seleccion": p.get("_seleccion_norm", p.get("seleccion", "?")),
                        "Cuota": p.get("cuota", 0),
                        "Confianza": f"{p.get('confianza', 0):.0%}",
                        "EV": f"{p.get('ev', 0):.2f}",
                        "Stake": p.get("stake", "?"),
                        "Sistemas OK": f"{p.get('sistemas_favor', 0)}/8",
                        "Calidad": p.get("_calidad", "Revisar"),
                    })
                df_resumen = pd.DataFrame(filas_resumen)
                # Convertir todo a string para evitar errores de Arrow
                df_resumen = df_resumen.astype(str)
                st.dataframe(df_resumen, width='stretch')

                with st.expander("Lectura corta por analista"):
                    for p in picks_auditados:
                        st.markdown(f"**{p.get('ia', '?')}**")
                        col_l1, col_l2, col_l3, col_l4 = st.columns(4)
                        col_l1.metric("Mercado", p.get('_mercado_norm', p.get('mercado', '-')))
                        col_l2.metric("Seleccion", p.get('_seleccion_norm', p.get('seleccion', '-')))
                        col_l3.metric("Cuota", f"{float(p.get('cuota', 0) or 0):.2f}")
                        col_l4.metric("Confianza", f"{float(p.get('confianza', 0) or 0):.0%}")
                        fundamentos = p.get("fundamentos_clave", [])
                        if fundamentos:
                            st.caption("Fundamentos clave:")
                            for f in fundamentos:
                                st.write(f"- {f}")
                        st.warning(f"Riesgo principal: {p.get('riesgo_principal', 'Sin riesgo principal declarado.')}")
                        st.info(f"Lectura del analista: {p.get('razonamiento', 'Sin razonamiento disponible.')}")
                        st.divider()

                col_v1, col_v2 = st.columns(2)
                col_v1.metric("Picks emitidos", len(picks_emitidos))
                col_v2.metric("Escenarios sin entrada", len(no_bets))

                col_v3, col_v4 = st.columns(2)
                col_v3.metric("Analistas validos", len(picks_validos))
                col_v4.metric("Quorum minimo", quorum_minimo)

                if quorum_ok:
                    st.success(f"Quorum alcanzado: {len(picks_validos)} analistas validos.")
                else:
                    st.error(
                        f"Quorum insuficiente: solo {len(picks_validos)} analistas validos. "
                        "No deberias tratar este consenso como pick serio."
                    )

                filas_auditoria = []
                for p in picks_auditados:
                    filas_auditoria.append({
                        "IA": p.get("ia", "?"),
                        "Decision": p.get("decision", "?"),
                        "Mercado normalizado": p.get("_mercado_norm", ""),
                        "Seleccion normalizada": p.get("_seleccion_norm", ""),
                        "Calidad": p.get("_calidad", "Revisar"),
                        "Alertas": " | ".join(p.get("_alertas_calidad", [])) if p.get("_alertas_calidad") else "Sin alertas",
                    })
                df_auditoria = pd.DataFrame(filas_auditoria).astype(str)

                st.markdown("---")
                st.subheader("Lectura operativa")
                col_q1, col_q2, col_q3 = st.columns(3)
                col_q1.metric("Salidas solidas", picks_solidos)
                col_q2.metric("Para revisar", picks_revisar)
                col_q3.metric("Debiles", picks_debiles)

                confianzas = [float(p.get("confianza", 0) or 0) for p in picks_emitidos]
                if confianzas:
                    dispersion = max(confianzas) - min(confianzas)
                    if dispersion <= 0.05 and len(confianzas) >= 3:
                        st.warning("Las confianzas de varias IAs son demasiado parecidas. Eso puede indicar rigidez del prompt mas que criterio independiente.")

                if picks_emitidos and quorum_ok:
                    st.markdown("---")
                    st.subheader("Consolidacion automatica")

                    # Consolidar: mercado con mas consenso
                    from collections import Counter
                    claves_consenso = [
                        (p.get("_mercado_norm", p.get("mercado", "")), p.get("_seleccion_norm", p.get("seleccion", "")))
                        for p in picks_emitidos
                    ]
                    conteo = Counter(claves_consenso)
                    (mercado_consenso, sel_consenso), votos_consenso = conteo.most_common(1)[0]
                    total_votos = len(picks_emitidos)
                    porcentaje_consenso = votos_consenso / total_votos * 100

                    # Calcular EV promedio para la seleccion de consenso
                    evs = [
                        p.get("ev", 0)
                        for p in picks_emitidos
                        if p.get("_seleccion_norm", p.get("seleccion", "")) == sel_consenso
                        and p.get("_mercado_norm", p.get("mercado", "")) == mercado_consenso
                    ]
                    ev_promedio = sum(evs) / len(evs) if evs else 0

                    # Calcular cuota promedio
                    cuotas = [
                        p.get("cuota", 0)
                        for p in picks_emitidos
                        if p.get("_seleccion_norm", p.get("seleccion", "")) == sel_consenso
                        and p.get("_mercado_norm", p.get("mercado", "")) == mercado_consenso
                        and p.get("cuota", 0) > 1
                    ]
                    cuota_prom = sum(cuotas) / len(cuotas) if cuotas else 0

                    # Determinar stake por consenso
                    if votos_consenso == 7:
                        stake_auto = "2u"
                    elif votos_consenso == 6:
                        stake_auto = "1.5u"
                    elif votos_consenso >= 5:
                        stake_auto = "1u"
                    else:
                        stake_auto = "0.5u"

                    col_c1, col_c2, col_c3, col_c4 = st.columns(4)
                    col_c1.metric("Seleccion de consenso", sel_consenso)
                    col_c2.metric("Votos", f"{votos_consenso}/{total_votos} ({porcentaje_consenso:.0f}%)")
                    col_c3.metric("EV promedio", f"{ev_promedio:.2f}")
                    col_c4.metric("Stake sugerido", stake_auto)
                    st.caption(f"Mercado consolidado: {mercado_consenso}")

                    if cuota_prom > 0:
                        st.info(f"Cuota promedio reportada por las IAs: **{cuota_prom:.2f}** (verifica en Bet365/Pinnacle)")

                    with st.expander("Ver mapa de consenso real"):
                        filas_consenso = []
                        for (mercado_key, seleccion_key), votos in conteo.most_common():
                            filas_consenso.append({
                                "Mercado": mercado_key,
                                "Seleccion": seleccion_key,
                                "Votos": votos,
                            })
                        st.dataframe(pd.DataFrame(filas_consenso).astype(str), width='stretch')

                    # Opcion de importar automaticamente
                    st.markdown("---")
                    if st.button("Importar picks automaticos a la base de datos"):
                        try:
                            registros_auto = []
                            fecha_auto = datetime.now().strftime("%Y-%m-%d")
                            for p in picks_emitidos:
                                registros_auto.append({
                                    "ia": p.get("ia", "Auto"),
                                    "fecha": p.get("fecha") or fecha_auto,
                                    "partido": p.get("partido", "Partido"),
                                    "mercado": p.get("_mercado_norm", p.get("mercado", "Mercado")),
                                    "seleccion": p.get("_seleccion_norm", p.get("seleccion", "Seleccion")),
                                    "cuota": p.get("cuota", 0),
                                    "confianza": p.get("confianza", 0),
                                    "analisis_breve": (
                                        f"Sistemas: {p.get('sistemas_favor', 0)}/8 | "
                                        f"EV: {p.get('ev', 0):.2f} | "
                                        f"{p.get('razonamiento', '')[:100]}"
                                    ),
                                    "tipo_pick": "principal",
                                })

                            df_auto = pd.DataFrame(registros_auto)
                            batch = datetime.now().strftime("%Y%m%d_%H%M%S") + "_auto"
                            resultado_guardado = save_picks(df_auto, batch)
                            insertados = resultado_guardado.get("insertados", 0) if isinstance(resultado_guardado, dict) else 0
                            duplicados = resultado_guardado.get("duplicados", 0) if isinstance(resultado_guardado, dict) else 0
                            mensaje_extra = ""
                            if insertados > 0:
                                df_lote_auto = get_all_picks(incluir_alternativas=True)
                                lote_auto = df_lote_auto[df_lote_auto["import_batch"] == batch].copy() if not df_lote_auto.empty and "import_batch" in df_lote_auto.columns else pd.DataFrame()
                                if not lote_auto.empty:
                                    auto_pub = _enviar_pick_telegram_si_activo(lote_auto.iloc[0].to_dict())
                                    if auto_pub:
                                        _, detalle = auto_pub
                                        mensaje_extra = f" | Telegram: {detalle}"
                            st.session_state.auto_import_feedback = {
                                "tipo": "ok",
                                "mensaje": f"Importacion completada. Insertados: {insertados} | Duplicados: {duplicados} | batch: {batch}{mensaje_extra}",
                            }
                            st.rerun()
                        except Exception as e:
                            st.session_state.auto_import_feedback = {
                                "tipo": "error",
                                "mensaje": f"Error al importar: {e}",
                            }
                            st.rerun()
                elif picks_emitidos and not quorum_ok:
                    st.warning("Hay picks emitidos, pero no se habilita consolidacion ni guardado porque el quorum minimo no se cumplio.")

                    st.markdown("---")
                    with st.expander("Diagnostico detallado"):
                        st.markdown("**Auditoria de calidad por IA**")
                        st.dataframe(df_auditoria, width='stretch')

                        if picks_emitidos:
                            with st.expander("Mapa de consenso real"):
                                filas_consenso = []
                                for (mercado_key, seleccion_key), votos in conteo.most_common():
                                    filas_consenso.append({
                                        "Mercado": mercado_key,
                                        "Seleccion": seleccion_key,
                                        "Votos": votos,
                                    })
                                st.dataframe(pd.DataFrame(filas_consenso).astype(str), width='stretch')

                        with st.expander("Salida JSON interpretada"):
                            st.json(picks_auditados)

                        with st.expander("Visualizador de salida cruda por IA"):
                            st.caption("Aqui puedes ver exactamente lo que devolvio cada modelo antes de que la app lo resumiera.")
                            for r in resultados:
                                nombre_ia = r.get("ia", "desconocida")
                                estado_ia = r.get("status", "desconocido")
                                st.markdown(f"**{nombre_ia}**")
                                st.caption(f"Estado: {estado_ia}")

                                if estado_ia == "ok":
                                    data_ia = r.get("data", {})
                                    if data_ia:
                                        col_raw_1, col_raw_2 = st.columns([1, 2])
                                        with col_raw_1:
                                            st.json(data_ia)
                                        with col_raw_2:
                                            st.text_area(
                                                f"Respuesta original - {nombre_ia}",
                                                value=r.get("raw_output", ""),
                                                height=220,
                                                key=f"raw_ok_{nombre_ia}",
                                            )
                                    else:
                                        st.text_area(
                                            f"Respuesta original - {nombre_ia}",
                                            value=r.get("raw_output", ""),
                                            height=220,
                                            key=f"raw_only_{nombre_ia}",
                                        )
                                else:
                                    st.error(r.get("error", "Error desconocido"))
                                    st.text_area(
                                        f"Respuesta original - {nombre_ia}",
                                        value=r.get("raw_output", ""),
                                        height=220,
                                        key=f"raw_fail_{nombre_ia}",
                                    )
                                st.divider()

# ====================== JUEZ PONDERADO ======================
with tab8:
    _render_section_banner(
        "Consenso ponderado",
        "Consolida picks pendientes con aprendizaje historico y revisa rapidamente si la base actual tiene suficiente material para un veredicto serio.",
        "Consenso",
    )
    st.subheader("Consenso ponderado con aprendizaje historico")
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

    df = get_all_picks()
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
with tab9:
    _render_section_banner(
        "Aprendizaje y pesos",
        "Recalibra el sistema segun el rendimiento historico y revisa rapidamente el impacto esperado sobre los pesos por IA.",
        "Aprendizaje",
    )
    st.subheader("Aprendizaje y recalibracion de pesos")
    st.markdown("Recalcula los pesos con base en el rendimiento historico (Shrinkage Bayesiano + Sharpe Ratio).")

    if st.button("Recalcular pesos ahora"):
        with st.spinner("Calculando nuevos pesos..."):
            try:
                from analizar_rendimiento import calcular_metricas
                df_resultados = calcular_metricas()
                st.success("Pesos recalculados correctamente.")
                if not df_resultados.empty:
                    ar1, ar2, ar3, ar4 = st.columns(4)
                    ar1.metric("IAs analizadas", len(df_resultados))
                    ar2.metric("Picks acumulados", int(df_resultados["picks"].fillna(0).sum()) if "picks" in df_resultados.columns else 0)
                    ar3.metric("ROI medio", f"{df_resultados['roi'].fillna(0).mean():.2f}" if "roi" in df_resultados.columns else "0.00")
                    ar4.metric("Sharpe medio", f"{df_resultados['sharpe'].fillna(0).mean():.2f}" if "sharpe" in df_resultados.columns else "0.00")
                    cols_metricas = [c for c in ['ia', 'picks', 'roi', 'sharpe', 'peso_nuevo'] if c in df_resultados.columns]
                    st.dataframe(df_resultados[cols_metricas], width='stretch')
                else:
                    st.info("El recalculo no devolvio filas.")
            except Exception as e:
                st.error(f"Error al recalcular pesos: {e}")

# ====================== COMPARATIVA ESPEJO ======================
with tab10:
    _render_section_banner(
        "Comparativa espejo",
        "Compara flujo manual vs automatico por partido y construye evidencia real de cual metodologia te conviene mas.",
        "Espejo",
    )
    st.subheader("Comparativa espejo: Manual vs Automatico")
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
        st.info("Todavia no hay casos espejo guardados.")

# ====================== USUARIOS ======================
with tab11:
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
        columnas_users = [c for c in ["id", "username", "display_name", "email", "role", "active", "must_change_password", "last_login", "created_at"] if c in df_users_view.columns]
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

# ====================== MOTOR PROPIO ======================
with tab12:
    _render_section_banner(
        "Motor propio",
        "Ejecuta la primera fase del motor matematico propio para que el pick salga del sistema y no de IAs externas.",
        "Motor Core",
    )
    st.subheader("Motor de picks autonomo")
    st.markdown(
        "Esta capa usa **Poisson, Dixon-Coles, ELO, forma ponderada y mercado eficiente**. "
        "La idea es que el cerebro principal del pick viva aqui y las IAs queden solo para redactar."
    )

    datos_motor = st.session_state.get("prepared_match_data")
    if not datos_motor:
        st.info("Primero prepara un partido en la pestana `Preparar Partido`. Luego vuelve aqui para correr el motor propio.")
    else:
        manual_preparado = st.session_state.get("prepared_match_manual_data", {}) or {}
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Partido", datos_motor.get("partido", "-"))
        m2.metric("Fecha", datos_motor.get("fecha", "-"))
        m3.metric("Liga", datos_motor.get("liga_nombre", "-"))
        m4.metric("Fixture", datos_motor.get("fixture_id", "-"))

        st.caption("El motor toma primero lo que dejaste listo en `Preparar Partido`. Aqui puedes revisar, ajustar o reforzar antes de ejecutarlo.")
        resumen_cols = st.columns(4)
        resumen_cols[0].metric("xG listos", sum(1 for v in [manual_preparado.get("xg_local"), manual_preparado.get("xg_visitante")] if str(v or "").strip()), "/2")
        resumen_cols[1].metric("ELO listos", sum(1 for v in [manual_preparado.get("elo_local"), manual_preparado.get("elo_visitante")] if str(v or "").strip()), "/2")
        resumen_cols[2].metric("Contexto listo", "Si" if any(str(manual_preparado.get(k) or "").strip() for k in ["motivacion_local", "motivacion_visitante", "contexto_extra"]) else "No")
        resumen_cols[3].metric("Odds API", "Si" if datos_motor.get("odds", {}).get("resumen") else "No")

        st.markdown("### Entradas manuales que usa el motor")
        c1, c2 = st.columns(2)
        xg_local_motor = c1.text_input(
            "xG local",
            value=str(manual_preparado.get("xg_local", st.session_state.get("prep_xg_local", "")) or ""),
            key="motor_xg_local",
            placeholder="Ej: 1.62",
        )
        xg_visit_motor = c2.text_input(
            "xG visitante",
            value=str(manual_preparado.get("xg_visitante", st.session_state.get("prep_xg_visitante", "")) or ""),
            key="motor_xg_visitante",
            placeholder="Ej: 0.94",
        )
        c3, c4 = st.columns(2)
        elo_local_motor = c3.text_input(
            "ELO local",
            value=str(manual_preparado.get("elo_local", st.session_state.get("prep_elo_local", "")) or ""),
            key="motor_elo_local",
            placeholder="Ej: 1642",
        )
        elo_visit_motor = c4.text_input(
            "ELO visitante",
            value=str(manual_preparado.get("elo_visitante", st.session_state.get("prep_elo_visitante", "")) or ""),
            key="motor_elo_visitante",
            placeholder="Ej: 1510",
        )
        contexto_motor = st.text_area(
            "Contexto libre",
            value=(
                (manual_preparado.get("motivacion_local", st.session_state.get("prep_motivacion_local", "")) or "")
                + ("\n" if (manual_preparado.get("motivacion_local", st.session_state.get("prep_motivacion_local", "")) or "") else "")
                + (manual_preparado.get("motivacion_visitante", st.session_state.get("prep_motivacion_visitante", "")) or "")
                + ("\n" if (manual_preparado.get("contexto_extra", st.session_state.get("prep_contexto_extra", "")) or "") else "")
                + (manual_preparado.get("contexto_extra", st.session_state.get("prep_contexto_extra", "")) or "")
            ).strip(),
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
                "motivacion_local": manual_preparado.get("motivacion_local", ""),
                "motivacion_visitante": manual_preparado.get("motivacion_visitante", ""),
                "contexto_extra": contexto_motor,
            }
            st.session_state.motor_pick_result = analizar_partido_motor(datos_motor, manual_motor)

        resultado_motor = st.session_state.get("motor_pick_result")
        if resultado_motor:
            pick_motor = resultado_motor.get("pick", {})
            consenso_motor = resultado_motor.get("consenso", {})
            prob_motor = resultado_motor.get("probabilidad_final", {})
            decision_motor = resultado_motor.get("decision_motor", {})
            calidad_input = resultado_motor.get("calidad_input", {})
            favorito_estructural = resultado_motor.get("favorito_estructural", {})
            st.markdown("---")
            st.subheader("Resumen del motor")
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
                    f"Señal estructural -> Local: {favorito_estructural.get('score_local', 0)} | "
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
                        fila[clave] = valor
                sistemas_rows.append(fila)
            st.markdown("### Lectura por sistema")
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
                            "Prob. implicita": round((item.get("prob_implicita", 0) or 0) * 100, 1),
                            "EV %": round((item.get("ev", 0) or 0) * 100, 1),
                            "Sistemas a favor": item.get("sistemas_a_favor", 0),
                            "Fit mercado": round((item.get("market_fit_score", 0) or 0) * 100, 1),
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
                    insertados, duplicados, batch_motor = save_picks(df_motor)
                    auto_pub = _enviar_pick_telegram_si_activo(pick_motor_publicable)
                    mensaje_extra = ""
                    if auto_pub:
                        ok_pub, detalle_pub = auto_pub
                        mensaje_extra = f" | Telegram: {detalle_pub}"
                    st.success(f"Motor guardado. Insertados: {insertados} | Duplicados: {duplicados} | batch: {batch_motor}{mensaje_extra}")

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


