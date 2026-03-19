import re
import pandas as pd
from datetime import datetime
from config import IAS_LIST

def parse_txt_file(file) -> pd.DataFrame:
    """
    Parsea un archivo de texto con formato plano de picks.
    Ejemplo:
    IA: Gemini
    FECHA: 2026-02-25
    ---
    PARTIDO: Real Madrid vs Benfica
    MERCADO: Hándicap Asiático
    SELECCION: Benfica +1.25
    CUOTA: 1.45
    CONFIANZA: 0.75
    ANALISIS: texto
    ---
    """
    try:
        contenido = file.read().decode('utf-8')
    except:
        try:
            contenido = file.read().decode('latin-1')
        except:
            raise ValueError("No se pudo leer el archivo. Codificación no soportada.")

    lineas = contenido.split('\n')
    
    # Variables para el parseo
    ia = "Desconocida"
    fecha = None
    picks = []
    pick_actual = {}
    dentro_pick = False
    
    for i, linea in enumerate(lineas):
        linea = linea.strip()
        
        if not linea:
            continue
            
        if linea.startswith('IA:'):
            ia = linea.replace('IA:', '', 1).strip()
            if not ia:
                ia = "Desconocida"
            continue
            
        if linea.startswith('FECHA:'):
            fecha_str = linea.replace('FECHA:', '', 1).strip()
            try:
                datetime.strptime(fecha_str, '%Y-%m-%d')
                fecha = fecha_str
            except:
                fecha = None
            continue
            
        if linea.startswith('---'):
            if pick_actual and 'partido' in pick_actual:
                pick_actual['ia'] = ia
                if fecha:
                    pick_actual['fecha'] = fecha
                picks.append(pick_actual)
            pick_actual = {}
            dentro_pick = True
            continue
            
        if not dentro_pick and not pick_actual:
            dentro_pick = True
            
        if dentro_pick:
            if linea.startswith('PARTIDO:'):
                pick_actual['partido'] = linea.replace('PARTIDO:', '', 1).strip()
            elif linea.startswith('MERCADO:'):
                pick_actual['mercado'] = linea.replace('MERCADO:', '', 1).strip()
            elif linea.startswith('SELECCION:'):
                pick_actual['seleccion'] = linea.replace('SELECCION:', '', 1).strip()
            elif linea.startswith('CUOTA:'):
                try:
                    cuota_str = linea.replace('CUOTA:', '', 1).strip().replace(',', '.')
                    pick_actual['cuota'] = float(cuota_str)
                except:
                    raise ValueError(f"Cuota inválida en línea {i+1}: {linea}")
            elif linea.startswith('CONFIANZA:'):
                try:
                    conf_str = linea.replace('CONFIANZA:', '', 1).strip().replace(',', '.')
                    pick_actual['confianza'] = float(conf_str)
                except:
                    pick_actual['confianza'] = None
            elif linea.startswith('ANALISIS:'):
                pick_actual['analisis_breve'] = linea.replace('ANALISIS:', '', 1).strip()
    
    if pick_actual and 'partido' in pick_actual:
        pick_actual['ia'] = ia
        if fecha:
            pick_actual['fecha'] = fecha
        picks.append(pick_actual)
    
    if not picks:
        raise ValueError("No se encontraron picks válidos en el archivo.")
    
    df = pd.DataFrame(picks)
    
    required = ['partido', 'mercado', 'seleccion', 'cuota', 'fecha', 'ia']
    for col in required:
        if col not in df.columns:
            if col == 'fecha' and fecha:
                df['fecha'] = fecha
            else:
                df[col] = None
    
    if 'confianza' not in df.columns:
        df['confianza'] = None
    if 'analisis_breve' not in df.columns:
        df['analisis_breve'] = ""
    
    return df[required + ['confianza', 'analisis_breve']]

def validate_and_load_file(file) -> pd.DataFrame:
    return parse_txt_file(file)