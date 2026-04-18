"""
Componentes UI de la app.
"""
import streamlit as st


def render_public_card(titulo, cuerpo, etiqueta="", tono="normal", meta_left="", meta_right="", footer_hint=""):
    """Renderiza un card público."""
    color_etiqueta = "#29d764" if tono == "win" else "#ef4444" if tono == "loss" else "#6366f1" if tono == "push" else "#64748b"
    
    st.markdown(
        f"""
        <div style="background:linear-gradient(135deg, rgba(255,255,255,.035), rgba(255,255,255,.02)); border:1px solid rgba(255,255,255,.06); border-radius:24px; padding:18px 20px; margin-bottom:14px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                <span style="background:{color_etiqueta}; color:#fff; padding:4px 10px; border-radius:8px; font-size:11px; font-weight:700;">{etiqueta}</span>
                <span style="color:#7f8ca8; font-size:11px;">{meta_right}</span>
            </div>
            <div style="color:#f7f9fb; font-size:18px; font-weight:700; margin-bottom:6px;">{titulo}</div>
            <div style="color:#94a3b8; font-size:13px; white-space:pre-wrap; margin-bottom:10px;">{cuerpo}</div>
            <div style="display:flex; justify-content:space-between; color:#64748b; font-size:11px;">
                <span>{meta_left}</span>
                <span>{footer_hint}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def market_icon(texto):
    """Retorna icono según tipo de mercado."""
    texto_lower = str(texto).lower()
    if "ganador" in texto_lower or "1x2" in texto_lower:
        return "🏆"
    elif "over" in texto_lower or "under" in texto_lower:
        return "⚽"
    elif "handicap" in texto_lower:
        return "🎯"
    elif "corners" in texto_lower:
        return "📐"
    elif "tarjetas" in texto_lower or "cards" in texto_lower:
        return "🟨"
    return "📊"


def team_initials(nombre):
    """Obtiene las iniciales de un equipo."""
    if not nombre:
        return "??"
    palabras = nombre.strip().split()
    if len(palabras) >= 2:
        return (palabras[0][0] + palabras[-1][0]).upper()[:2]
    return nombre[:2].upper()


def team_logo_html(nombre, logo_url="", gradient="linear-gradient(135deg, #29d764, #4f8cff)"):
    """Retorna HTML para el logo de un equipo."""
    iniciales = team_initials(nombre)
    if logo_url:
        return f'<div style="width:40px; height:40px; border-radius:999px; overflow:hidden; display:flex; align-items:center; justify-content:center; background:{gradient};"><img src="{logo_url}" style="width:100%; height:100%; object-fit:contain;" /></div>'
    return f'<div style="width:40px; height:40px; border-radius:999px; background:{gradient}; display:flex; align-items:center; justify-content:center; color:#07111d; font-weight:900; font-size:16px;">{iniciales}</div>'


def get_team_logo_cached(team_name):
    """Obtiene el logo de un equipo (cached)."""
    from database import get_cached_team_logo
    return get_cached_team_logo(team_name)


def render_pick_detail(row, section_key):
    """Renderiza el detalle de un pick."""
    with st.expander("Ver detalle"):
        cols = st.columns([1, 1, 1, 1])
        cols[0].metric("Stake", f"{row.get('stake', 0)}u")
        cols[1].metric("Cuota", f"{float(row.get('cuota', 0) or 0):.2f}")
        cols[2].metric("Confianza", f"{int(float(row.get('confianza', 0) or 0) * 100)}%")
        estado = row.get("resultado", "pendiente")
        cols[3].metric("Estado", estado.upper())
        
        if row.get("analisis_breve"):
            st.markdown("**Análisis:**")
            st.write(row["analisis_breve"])
        
        if row.get("analisis_completo"):
            st.markdown("**Análisis completo:**")
            st.write(row["analisis_completo"])


def render_section_banner(title, text, chip=""):
    """Renderiza un banner de sección."""
    chip_html = f'<span style="background:rgba(79,140,255,.15); color:#4f8cff; padding:4px 10px; border-radius:6px; font-size:11px; font-weight:700; margin-right:10px;">{chip}</span>' if chip else ""
    st.markdown(
        f"""
        <div style="background:linear-gradient(135deg, rgba(79,140,255,.08), rgba(41,215,100,.05)); border:1px solid rgba(255,255,255,.05); border-radius:20px; padding:20px; margin:20px 0;">
            {chip_html}<span style="color:#f7f9fb; font-size:20px; font-weight:700;">{title}</span>
            <div style="color:#94a3b8; font-size:13px; margin-top:6px;">{text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def filtrar_df_por_periodo(df, periodo, fecha_col="fecha"):
    """Filtra DataFrame por período."""
    import pandas as pd
    from datetime import datetime, timedelta
    
    if df is None or df.empty:
        return df
    
    if fecha_col not in df.columns:
        return df
    
    try:
        df = df.copy()
        df[fecha_col] = pd.to_datetime(df[fecha_col], errors="coerce")
        df = df.dropna(subset=[fecha_col])
        
        hoy = datetime.now()
        
        if periodo == "hoy":
            return df[df[fecha_col].dt.date == hoy.date()]
        elif periodo == "ayer":
            ayer = hoy - timedelta(days=1)
            return df[df[fecha_col].dt.date == ayer.date()]
        elif periodo == "semana":
            return df[df[fecha_col] >= hoy - timedelta(days=7)]
        elif periodo == "mes":
            return df[df[fecha_col] >= hoy - timedelta(days=30)]
        elif periodo == "año":
            return df[df[fecha_col] >= hoy - timedelta(days=365)]
        
        return df
    except Exception:
        return df


def resumen_periodo_dashboard(df_periodo):
    """Genera resumen de métricas para un período."""
    import pandas as pd
    
    if df_periodo is None or df_periodo.empty:
        return {
            "picks": 0, "ganadas": 0, "perdidas": 0, "medias": 0,
            "ganancia": 0, "stake_total": 0, "roi": 0
        }
    
    total = len(df_periodo)
    ganadas = len(df_periodo[df_periodo.get("resultado", "") == "ganada"])
    perdidas = len(df_periodo[df_periodo.get("resultado", "") == "perdida"])
    medias = len(df_periodo[df_periodo.get("resultado", "") == "media"])
    
    try:
        df_periodo = df_periodo.copy()
        df_periodo["ganancia"] = pd.to_numeric(df_periodo.get("ganancia", 0), errors="coerce").fillna(0)
        df_periodo["stake"] = pd.to_numeric(df_periodo.get("stake", 0), errors="coerce").fillna(0)
        
        ganancia = df_periodo["ganancia"].sum()
        stake_total = df_periodo["stake"].sum()
        roi = ((ganancia / stake_total) * 100) if stake_total > 0 else 0
    except:
        ganancia = 0
        stake_total = 0
        roi = 0
    
    return {
        "picks": total,
        "ganadas": ganadas,
        "perdidas": perdidas,
        "medias": medias,
        "ganancia": ganancia,
        "stake_total": stake_total,
        "roi": roi
    }


def render_empty_state(mensaje, subtitulo="", icono="📂"):
    """Renderiza un estado vacío con diseño premium."""
    st.markdown(
        f"""
        <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; padding:60px 20px; text-align:center; background:rgba(255,255,255,.02); border:1px dashed rgba(255,255,255,.1); border-radius:30px; margin:20px 0;">
            <div style="font-size:50px; margin-bottom:16px;">{icono}</div>
            <div style="color:#f7f9fb; font-size:20px; font-weight:700;">{mensaje}</div>
            <div style="color:#64748b; font-size:14px; margin-top:8px; max-width:400px;">{subtitulo}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
