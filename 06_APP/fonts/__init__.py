"""
Módulo de gestión de fuentes para PDFs.
Multiplataforma: busca fuentes en el proyecto primero, luego sistema.
"""
import os
import sys

FUENTES_CARPETA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")

FUENTES_SISTEMA_COMUNES = [
    "DejaVuSans.ttf",
    "LiberationSans-Regular.ttf", 
    "NotoSans-Regular.ttf",
    "Roboto-Regular.ttf",
    "Arial.ttf",
    "Helvetica.ttf",
]

RUTAS_WINDOWS = [
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
]

RUTAS_LINUX = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/google-noto/NotoSans-Regular.ttf",
]

RUTAS_MAC = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial.ttf",
]


def _buscar_fuente_en_carpeta(nombre_fuente):
    """Busca una fuente en la carpeta del proyecto."""
    if not os.path.exists(FUENTES_CARPETA):
        return None
    
    for archivo in os.listdir(FUENTES_CARPETA):
        if archivo.lower().startswith(nombre_fuente.lower()) and archivo.endswith((".ttf", ".ttc", ".otf")):
            return os.path.join(FUENTES_CARPETA, archivo)
    return None


def _buscar_fuente_en_sistema():
    """Busca una fuente de emoji en el sistema."""
    rutas = []
    
    if sys.platform == "win32":
        rutas.extend(RUTAS_WINDOWS)
    elif sys.platform == "darwin":
        rutas.extend(RUTAS_MAC)
    else:
        rutas.extend(RUTAS_LINUX)
    
    for ruta in rutas:
        if os.path.exists(ruta):
            return ruta
    
    for fuente in FUENTES_SISTEMA_COMUNES:
        for raiz, dirs, archivos in os.walk("/usr/share/fonts"):
            if fuente in archivos:
                return os.path.join(raiz, fuente)
    
    return None


def obtener_ruta_fuente(fuente_preferida=None):
    """
    Obtiene la ruta a una fuente.
    
    Prioridad:
    1. Fuente en carpeta fonts/ del proyecto
    2. Fuente del sistema (detectada automáticamente)
    3. None (se usará fuente por defecto)
    
    Args:
        fuente_preferida: Nombre de fuente específica a buscar
        
    Returns:
        Ruta a la fuente o None
    """
    if fuente_preferida:
        ruta = _buscar_fuente_en_carpeta(fuente_preferida)
        if ruta:
            return ruta
    
    ruta = _buscar_fuente_en_carpeta("segoeui")
    if ruta:
        return ruta
    
    ruta = _buscar_fuente_en_carpeta("emoji")
    if ruta:
        return ruta
    
    return _buscar_fuente_en_sistema()


def get_fuente_emoji():
    """Obtiene la ruta a la fuente de emoji/símbolos."""
    return obtener_ruta_fuente()


def crear_pdf_con_fuente(pdf_class):
    """
    Decorador para crear PDFs con fuente de emoji.
    
    Uso:
        @crear_pdf_con_fuente
        class MiPDF(FPDF):
            pass
    """
    ruta_fuente = get_fuente_emoji()
    
    def wrapper(*args, **kwargs):
        pdf = pdf_class(*args, **kwargs)
        
        if ruta_fuente:
            try:
                pdf.add_font("Emoji", "", ruta_fuente, uni=True)
            except Exception:
                pass
        
        return pdf
    
    return wrapper
