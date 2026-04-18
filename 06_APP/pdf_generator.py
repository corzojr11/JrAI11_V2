import glob
import json
import os
from datetime import datetime

from fpdf import FPDF
import pandas as pd

from fonts import get_fuente_emoji

CARPETA_BASE = os.path.join(os.path.dirname(__file__), "..", "07_PICKSREALES")

_FUENTE_EMOJI_RUTA = get_fuente_emoji()


import logging

def _safe_add_font(pdf):
    """Centraliza la carga segura de la fuente, silenciando logs ruidosos y evitando caidas."""
    if not _FUENTE_EMOJI_RUTA:
        return
        
    fpdf_logger = logging.getLogger("fpdf")
    old_lvl = fpdf_logger.level
    fpdf_logger.setLevel(logging.CRITICAL)
    try:
        pdf.add_font("Emoji", "", _FUENTE_EMOJI_RUTA, uni=True)
    except Exception:
        pass
    finally:
        fpdf_logger.setLevel(old_lvl)

def _set_font_segura(pdf, tamano):
    """Establece la fuente de forma segura, con fallback directo a Helvetica."""
    try:
        pdf.set_font("Emoji", "", tamano)
    except Exception:
        pdf.set_font("Helvetica", "", tamano)


def _cargar_json_archivo(ruta_archivo):
    for encoding in ("utf-8", "latin-1"):
        try:
            with open(ruta_archivo, "r", encoding=encoding) as file:
                return json.load(file)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"No se pudo leer {ruta_archivo} por codificacion.")


def obtener_carpetas_partidos():
    if not os.path.exists(CARPETA_BASE):
        return []
    return [
        carpeta
        for carpeta in os.listdir(CARPETA_BASE)
        if os.path.isdir(os.path.join(CARPETA_BASE, carpeta))
    ]


def leer_picks_de_partido(nombre_carpeta):
    ruta_carpeta = os.path.join(CARPETA_BASE, nombre_carpeta)
    archivos = glob.glob(os.path.join(ruta_carpeta, "*.json"))
    if not archivos:
        archivos = glob.glob(os.path.join(ruta_carpeta, "*.txt"))

    principales = []
    alternativas = []

    for archivo in archivos:
        try:
            datos = _cargar_json_archivo(archivo)
        except Exception as e:
            print(f"Error leyendo {archivo}: {e}")
            continue

        pick = datos.get("pick")
        if isinstance(pick, dict) and pick.get("emitido") is True:
            principales.append(
                {
                    "ia": datos.get("ia", "Desconocida"),
                    "mercado": pick.get("mercado", ""),
                    "seleccion": pick.get("seleccion", ""),
                    "cuota": float(pick.get("cuota", 0.0) or 0.0),
                    "confianza": float(pick.get("confianza", 0.0) or 0.0),
                    "valor_esperado": float(pick.get("valor_esperado", 0.0) or 0.0),
                    "razonamiento": str(pick.get("razonamiento", "") or ""),
                }
            )

        for alt in datos.get("alternativas_consideradas", []):
            if not isinstance(alt, dict):
                continue
            alternativas.append(
                {
                    "ia": datos.get("ia", "Desconocida"),
                    "mercado": alt.get("mercado", ""),
                    "seleccion": alt.get("seleccion", ""),
                    "cuota": float(alt.get("cuota", 0.0) or 0.0),
                    "motivo": str(alt.get("descartado_por", "") or ""),
                }
            )

    return {"principales": principales, "alternativas": alternativas}


def recopilar_todos_los_picks():
    todos = {}
    for carpeta in obtener_carpetas_partidos():
        picks = leer_picks_de_partido(carpeta)
        if picks["principales"] or picks["alternativas"]:
            todos[carpeta] = picks
    return todos


def generar_pdf(data, incluir_alternativas=True):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    _safe_add_font(pdf)
    _set_font_segura(pdf, 16)
    pdf.cell(0, 10, "Jr AI 11 - Analisis de Apuestas", ln=True, align="C")

    _set_font_segura(pdf, 10)
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    pdf.cell(0, 6, f"Fecha: {fecha} | 8 IAs analistas", ln=True, align="C")

    total_principales = sum(len(partido["principales"]) for partido in data.values())
    total_alternativas = (
        sum(len(partido["alternativas"]) for partido in data.values())
        if incluir_alternativas
        else 0
    )
    pdf.cell(0, 6, f"Total picks principales: {total_principales}", ln=True)
    if incluir_alternativas:
        pdf.cell(0, 6, f"Total picks alternativos: {total_alternativas}", ln=True)
    pdf.ln(5)

    for nombre_partido, picks in data.items():
        if not picks["principales"] and (
            not incluir_alternativas or not picks["alternativas"]
        ):
            continue

        _set_font_segura(pdf, 14)
        pdf.cell(0, 8, f"Partido: {nombre_partido}", ln=True)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 190, pdf.get_y())
        pdf.ln(2)

        if picks["principales"]:
            _set_font_segura(pdf, 11)
            pdf.set_text_color(0, 100, 0)
            pdf.cell(0, 6, "Picks principales", ln=True)
            pdf.set_text_color(0, 0, 0)
            _set_font_segura(pdf, 10)
            for pick in picks["principales"]:
                pdf.ln(2)
                pdf.cell(0, 5, f"{pick['ia']} - {pick['mercado']}", ln=True)
                pdf.cell(
                    0,
                    5,
                    f"   Seleccion: {pick['seleccion']} @ {pick['cuota']:.2f}",
                    ln=True,
                )
                conf = int(float(pick.get("confianza") or 0) * 100)
                ev = float(pick.get("valor_esperado") or 0) * 100
                pdf.cell(0, 5, f"   Confianza: {conf}% | EV: {ev:+.1f}%", ln=True)
                razonamiento = str(pick.get("razonamiento") or "")
                resumen = razonamiento[:200] + ("..." if len(razonamiento) > 200 else "")
                pdf.multi_cell(0, 4, f"   Analisis: {resumen}")
            pdf.ln(2)

        if incluir_alternativas and picks["alternativas"]:
            _set_font_segura(pdf, 11)
            pdf.set_text_color(150, 75, 0)
            pdf.cell(0, 6, "Picks alternativos", ln=True)
            pdf.set_text_color(0, 0, 0)
            _set_font_segura(pdf, 10)
            for alt in picks["alternativas"]:
                pdf.ln(2)
                pdf.cell(0, 5, f"{alt['ia']} - {alt['mercado']} (descartado)", ln=True)
                seleccion = alt["seleccion"]
                if alt["cuota"] > 0:
                    seleccion += f" @ {alt['cuota']:.2f}"
                pdf.cell(0, 5, f"   Seleccion: {seleccion}", ln=True)
                pdf.multi_cell(0, 4, f"   Motivo: {alt['motivo']}")
            pdf.ln(2)

        pdf.ln(5)

    pdf.set_y(-15)
    _set_font_segura(pdf, 8)
    pdf.cell(
        0,
        10,
        "Analisis generado por 8 IAs. No es consejo financiero.",
        0,
        0,
        "C",
    )

    resultado = pdf.output()
    if isinstance(resultado, bytearray):
        resultado = bytes(resultado)
    return resultado


def generar_pdf_desde_dataframe(df, titulo="Jr AI 11 - Boletin de Picks", subtitulo=""):
    if df is None or df.empty:
        raise ValueError("No hay picks para exportar.")

    trabajo = df.copy()
    if "confianza" in trabajo.columns:
        trabajo["confianza"] = pd.to_numeric(trabajo["confianza"], errors="coerce").fillna(0.0)
    else:
        trabajo["confianza"] = 0.0

    if "cuota" in trabajo.columns:
        trabajo["cuota"] = pd.to_numeric(trabajo["cuota"], errors="coerce").fillna(0.0)
    else:
        trabajo["cuota"] = 0.0

    if "analisis_breve" not in trabajo.columns:
        trabajo["analisis_breve"] = ""
    if "tipo_pick" not in trabajo.columns:
        trabajo["tipo_pick"] = "principal"
    if "resultado" not in trabajo.columns:
        trabajo["resultado"] = "pendiente"

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    _safe_add_font(pdf)

    _set_font_segura(pdf, 18)
    pdf.cell(0, 10, titulo, ln=True, align="C")

    _set_font_segura(pdf, 10)
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    texto_sub = subtitulo.strip() if subtitulo else "Boletin generado desde la base interna"
    pdf.cell(0, 6, texto_sub, ln=True, align="C")
    pdf.cell(0, 6, f"Fecha de exportacion: {fecha}", ln=True, align="C")
    pdf.ln(4)

    total_principales = int((trabajo["tipo_pick"] == "principal").sum())
    total_alternativas = int((trabajo["tipo_pick"] == "alternativa").sum())
    total_pendientes = int((trabajo["resultado"] == "pendiente").sum())

    _set_font_segura(pdf, 10)
    pdf.cell(0, 6, f"Principales: {total_principales} | Alternativos: {total_alternativas} | Pendientes: {total_pendientes}", ln=True)
    pdf.ln(4)

    columnas_orden = ["fecha", "partido", "ia", "mercado", "seleccion", "cuota", "confianza", "tipo_pick", "analisis_breve"]
    for columna in columnas_orden:
        if columna not in trabajo.columns:
            trabajo[columna] = ""

    trabajo = trabajo.sort_values(by=["fecha", "partido", "tipo_pick", "ia"], ascending=[False, True, True, True])

    partido_actual = None
    for _, row in trabajo.iterrows():
        partido = str(row.get("partido", "") or "Partido")
        if partido != partido_actual:
            partido_actual = partido
            pdf.ln(2)
            _set_font_segura(pdf, 13)
            pdf.set_text_color(20, 20, 20)
            pdf.cell(0, 8, partido_actual, ln=True)
            pdf.set_draw_color(210, 210, 210)
            pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 190, pdf.get_y())
            pdf.ln(2)

        tipo_pick = str(row.get("tipo_pick", "principal") or "principal").strip().lower()
        _set_font_segura(pdf, 10)
        if tipo_pick == "principal":
            pdf.set_text_color(0, 90, 0)
            etiqueta = "PICK PRINCIPAL"
        else:
            pdf.set_text_color(150, 90, 0)
            etiqueta = "PICK ALTERNATIVO"

        pdf.cell(0, 5, f"{etiqueta} | {row.get('ia', 'IA')}", ln=True)
        pdf.set_text_color(0, 0, 0)

        mercado = str(row.get("mercado", "") or "-")
        seleccion = str(row.get("seleccion", "") or "-")
        cuota = float(row.get("cuota", 0) or 0)
        confianza = float(row.get("confianza", 0) or 0) * 100
        analisis = str(row.get("analisis_breve", "") or "").strip()
        analisis = analisis[:220] + ("..." if len(analisis) > 220 else "")

        pdf.cell(0, 5, f"Mercado: {mercado}", ln=True)
        if cuota > 0:
            pdf.cell(0, 5, f"Seleccion: {seleccion} @ {cuota:.2f}", ln=True)
        else:
            pdf.cell(0, 5, f"Seleccion: {seleccion}", ln=True)
        pdf.cell(0, 5, f"Confianza declarada: {confianza:.0f}%", ln=True)
        if analisis:
            pdf.multi_cell(0, 4, f"Lectura breve: {analisis}")
        pdf.ln(2)

    pdf.set_y(-15)
    _set_font_segura(pdf, 8)
    pdf.cell(0, 10, "Documento interno de apoyo para publicacion y seguimiento.", 0, 0, "C")

    resultado = pdf.output()
    if isinstance(resultado, bytearray):
        resultado = bytes(resultado)
    return resultado


def generar_pdf_pick_oficial(pick, titulo="Jr AI 11 - Pick Oficial", subtitulo="Contenido listo para compartir"):
    if not pick:
        raise ValueError("No hay informacion del pick oficial.")

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    _safe_add_font(pdf)

    partido = str(pick.get("partido", "Partido")).strip()
    mercado = str(pick.get("mercado", "-")).strip()
    seleccion = str(pick.get("seleccion", "-")).strip()
    ia = str(pick.get("ia", "Sistema")).strip()
    cuota = float(pick.get("cuota", 0) or 0)
    confianza = float(pick.get("confianza", 0) or 0) * 100
    analisis = str(pick.get("analisis_breve", "") or "").strip()
    analisis = analisis[:320] + ("..." if len(analisis) > 320 else "")

    _set_font_segura(pdf, 20)
    pdf.cell(0, 12, titulo, ln=True, align="C")

    _set_font_segura(pdf, 11)
    pdf.cell(0, 6, subtitulo, ln=True, align="C")
    pdf.cell(0, 6, datetime.now().strftime("%d/%m/%Y %H:%M"), ln=True, align="C")
    pdf.ln(8)

    _set_font_segura(pdf, 16)
    pdf.cell(0, 10, partido, ln=True, align="C")
    pdf.ln(2)

    _set_font_segura(pdf, 12)
    pdf.set_text_color(0, 90, 0)
    pdf.cell(0, 8, "PICK OFICIAL", ln=True, align="C")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    _set_font_segura(pdf, 12)
    pdf.cell(0, 7, f"Mercado: {mercado}", ln=True)
    if cuota > 0:
        pdf.cell(0, 7, f"Seleccion: {seleccion} @ {cuota:.2f}", ln=True)
    else:
        pdf.cell(0, 7, f"Seleccion: {seleccion}", ln=True)
    pdf.cell(0, 7, f"Fuente / IA: {ia}", ln=True)
    pdf.cell(0, 7, f"Confianza declarada: {confianza:.0f}%", ln=True)
    pdf.ln(3)

    if analisis:
        _set_font_segura(pdf, 11)
        pdf.multi_cell(0, 6, f"Lectura breve: {analisis}")

    pdf.ln(6)
    _set_font_segura(pdf, 9)
    pdf.multi_cell(0, 5, "Material informativo para seguimiento deportivo. Verifica cuotas finales antes de publicar o entrar.")

    resultado = pdf.output()
    if isinstance(resultado, bytearray):
        resultado = bytes(resultado)
    return resultado


def generar_pdf_resultado_pick(pick, titulo="Jr AI 11 - Resultado del Pick", subtitulo="Seguimiento del sistema"):
    if not pick:
        raise ValueError("No hay informacion del pick cerrado.")

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    _safe_add_font(pdf)

    partido = str(pick.get("partido", "Partido")).strip()
    mercado = str(pick.get("mercado", "-")).strip()
    seleccion = str(pick.get("seleccion", "-")).strip()
    ia = str(pick.get("ia", "Sistema")).strip()
    cuota = float(pick.get("cuota", 0) or 0)
    cuota_real = float(pick.get("cuota_real", 0) or 0)
    resultado_pick = str(pick.get("resultado", "pendiente")).strip().lower()
    ganancia = float(pick.get("ganancia", 0) or 0)
    analisis = str(pick.get("analisis_breve", "") or "").strip()
    analisis = analisis[:280] + ("..." if len(analisis) > 280 else "")

    etiqueta = resultado_pick.upper()
    color = (0, 120, 0)
    if resultado_pick == "perdida":
        color = (170, 30, 30)
    elif resultado_pick == "media":
        color = (170, 120, 0)

    _set_font_segura(pdf, 20)
    pdf.cell(0, 12, titulo, ln=True, align="C")

    _set_font_segura(pdf, 11)
    pdf.cell(0, 6, subtitulo, ln=True, align="C")
    pdf.cell(0, 6, datetime.now().strftime("%d/%m/%Y %H:%M"), ln=True, align="C")
    pdf.ln(8)

    _set_font_segura(pdf, 16)
    pdf.cell(0, 10, partido, ln=True, align="C")
    pdf.ln(2)

    _set_font_segura(pdf, 14)
    pdf.set_text_color(*color)
    pdf.cell(0, 8, etiqueta, ln=True, align="C")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    _set_font_segura(pdf, 12)
    pdf.cell(0, 7, f"Mercado: {mercado}", ln=True)
    pdf.cell(0, 7, f"Seleccion: {seleccion}", ln=True)
    if cuota > 0:
        pdf.cell(0, 7, f"Cuota publicada: {cuota:.2f}", ln=True)
    if cuota_real > 0:
        pdf.cell(0, 7, f"Cuota real registrada: {cuota_real:.2f}", ln=True)
    pdf.cell(0, 7, f"Fuente / IA: {ia}", ln=True)
    pdf.cell(0, 7, f"Ganancia registrada: {ganancia:.2f}", ln=True)
    pdf.ln(3)

    if analisis:
        _set_font_segura(pdf, 11)
        pdf.multi_cell(0, 6, f"Lectura breve original: {analisis}")

    pdf.ln(6)
    _set_font_segura(pdf, 9)
    pdf.multi_cell(0, 5, "Resumen de seguimiento para comunicacion y control interno del rendimiento.")

    resultado = pdf.output()
    if isinstance(resultado, bytearray):
        resultado = bytes(resultado)
    return resultado


def generar_pdf_pick_social(pick, marca="Jr AI 11", subtitulo="Pick oficial"):
    if not pick:
        raise ValueError("No hay informacion del pick.")
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    _safe_add_font(pdf)

    partido = str(pick.get("partido", "Partido")).strip()
    mercado = str(pick.get("mercado", "-")).strip()
    seleccion = str(pick.get("seleccion", "-")).strip()
    ia = str(pick.get("ia", "Sistema")).strip()
    cuota = float(pick.get("cuota", 0) or 0)
    confianza = float(pick.get("confianza", 0) or 0) * 100
    analisis = str(pick.get("analisis_breve", "") or "").strip()
    analisis = analisis[:160] + ("..." if len(analisis) > 160 else "")

    pdf.set_fill_color(22, 28, 36)
    pdf.rect(0, 0, 210, 297, "F")

    pdf.set_text_color(255, 255, 255)
    _set_font_segura(pdf, 18)
    pdf.cell(0, 12, marca, ln=True, align="C")
    _set_font_segura(pdf, 12)
    pdf.set_text_color(214, 170, 76)
    pdf.cell(0, 8, subtitulo.upper(), ln=True, align="C")
    pdf.ln(8)

    pdf.set_text_color(255, 255, 255)
    _set_font_segura(pdf, 20)
    pdf.multi_cell(0, 10, partido, align="C")
    pdf.ln(4)

    _set_font_segura(pdf, 14)
    pdf.set_text_color(214, 170, 76)
    pdf.cell(0, 8, f"{mercado}", ln=True, align="C")
    pdf.set_text_color(255, 255, 255)
    _set_font_segura(pdf, 16)
    if cuota > 0:
        pdf.cell(0, 10, f"{seleccion} @ {cuota:.2f}", ln=True, align="C")
    else:
        pdf.cell(0, 10, seleccion, ln=True, align="C")
    pdf.ln(6)

    _set_font_segura(pdf, 12)
    pdf.cell(0, 8, f"Confianza declarada: {confianza:.0f}%", ln=True, align="C")
    pdf.cell(0, 8, f"Fuente: {ia}", ln=True, align="C")
    pdf.ln(8)

    if analisis:
        _set_font_segura(pdf, 11)
        pdf.set_text_color(220, 220, 220)
        pdf.multi_cell(0, 7, analisis, align="C")

    resultado = pdf.output()
    if isinstance(resultado, bytearray):
        resultado = bytes(resultado)
    return resultado


def generar_pdf_resultado_social(pick, marca="Jr AI 11", subtitulo="Resultado del pick"):
    if not pick:
        raise ValueError("No hay informacion del pick cerrado.")
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    _safe_add_font(pdf)

    partido = str(pick.get("partido", "Partido")).strip()
    mercado = str(pick.get("mercado", "-")).strip()
    seleccion = str(pick.get("seleccion", "-")).strip()
    cuota = float(pick.get("cuota", 0) or 0)
    resultado_pick = str(pick.get("resultado", "pendiente")).strip().lower()
    ganancia = float(pick.get("ganancia", 0) or 0)

    etiqueta = "WIN"
    color = (0, 140, 70)
    if resultado_pick == "perdida":
        etiqueta = "LOSS"
        color = (180, 40, 40)
    elif resultado_pick == "media":
        etiqueta = "PUSH"
        color = (180, 130, 20)

    pdf.set_fill_color(22, 28, 36)
    pdf.rect(0, 0, 210, 297, "F")

    pdf.set_text_color(255, 255, 255)
    _set_font_segura(pdf, 18)
    pdf.cell(0, 12, marca, ln=True, align="C")
    _set_font_segura(pdf, 12)
    pdf.set_text_color(214, 170, 76)
    pdf.cell(0, 8, subtitulo.upper(), ln=True, align="C")
    pdf.ln(10)

    _set_font_segura(pdf, 26)
    pdf.set_text_color(*color)
    pdf.cell(0, 14, etiqueta, ln=True, align="C")
    pdf.ln(4)

    pdf.set_text_color(255, 255, 255)
    _set_font_segura(pdf, 18)
    pdf.multi_cell(0, 10, partido, align="C")
    pdf.ln(4)

    _set_font_segura(pdf, 13)
    pdf.cell(0, 8, f"{mercado}", ln=True, align="C")
    if cuota > 0:
        pdf.cell(0, 8, f"{seleccion} @ {cuota:.2f}", ln=True, align="C")
    else:
        pdf.cell(0, 8, seleccion, ln=True, align="C")
    pdf.ln(6)

    _set_font_segura(pdf, 12)
    pdf.cell(0, 8, f"Ganancia registrada: {ganancia:.2f}", ln=True, align="C")

    resultado = pdf.output()
    if isinstance(resultado, bytearray):
        resultado = bytes(resultado)
    return resultado
