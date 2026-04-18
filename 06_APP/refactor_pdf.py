import os
import re

file_path = "pdf_generator.py"

with open(file_path, "r", encoding="utf-8") as f:
    text = f.read()

# 1. Replace _fuente and _set_font_segura
target_1 = """def _fuente(tamano):
    \"\"\"Retorna la fuente a usar (Emoji si está disponible, sino Helvetica).\"\"\"
    if _FUENTE_EMOJI_RUTA:
        return "Emoji"
    return "Helvetica"


def _set_font_segura(pdf, tamano):
    \"\"\"Establece la fuente de forma segura con fallback.\"\"\"
    fuente = _fuente(tamano)
    try:
        pdf.set_font(fuente, "", tamano)
    except Exception:
        pdf.set_font("Helvetica", "", tamano)"""

new_1 = """import logging

def _safe_add_font(pdf):
    \"\"\"Centraliza la carga segura de la fuente, silenciando logs ruidosos y evitando caidas.\"\"\"
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
    \"\"\"Establece la fuente de forma segura, con fallback directo a Helvetica.\"\"\"
    try:
        pdf.set_font("Emoji", "", tamano)
    except Exception:
        pdf.set_font("Helvetica", "", tamano)"""

text = text.replace(target_1, new_1)

# 2. Match the inline add_font calls
# Pattern 1 (in generar_pdf)
pattern_1 = re.compile(r"    fuente_ok = False\n    if _FUENTE_EMOJI_RUTA:\n        try:\n            pdf\.add_font\(\"Emoji\", \"\", _FUENTE_EMOJI_RUTA, uni=True\)\n            fuente_ok = True\n        except Exception:\n            pass")
text = pattern_1.sub(r"    _safe_add_font(pdf)", text)

# Pattern 2 (in the other 4 methods)
pattern_2 = re.compile(r"    fuente_emoji = get_fuente_emoji\(\)\n    if fuente_emoji:\n        try:\n            pdf\.add_font\(\"Emoji\", \"\", fuente_emoji, uni=True\)\n        except Exception:\n            pass")
text = pattern_2.sub(r"    _safe_add_font(pdf)", text)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(text)

print("pdf_generator.py refactored.")
