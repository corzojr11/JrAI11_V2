# juez_con_pesos.py
import json
import glob
import os
import pandas as pd

def leer_pesos():
    """Lee el archivo de pesos y devuelve un diccionario. Si no existe, todos los pesos son 1.0."""
    if os.path.exists('pesos_ia.json'):
        with open('pesos_ia.json', 'r') as f:
            return json.load(f)
    else:
        print("⚠️ No se encontró pesos_ia.json. Usando pesos neutros (1.0).")
        return {}

def parsear_archivo_txt(ruta):
    """Lee un archivo de texto con formato IA, ---, etc. y devuelve lista de picks."""
    picks = []
    with open(ruta, 'r', encoding='utf-8') as f:
        lineas = f.readlines()
    
    pick_actual = {}
    for linea in lineas:
        linea = linea.strip()
        if linea.startswith('IA:'):
            pick_actual['ia'] = linea.replace('IA:', '').strip()
        elif linea.startswith('FECHA:'):
            pick_actual['fecha'] = linea.replace('FECHA:', '').strip()
        elif linea.startswith('---'):
            if pick_actual and 'partido' in pick_actual:
                picks.append(pick_actual)
            pick_actual = {}
        elif linea.startswith('PARTIDO:'):
            pick_actual['partido'] = linea.replace('PARTIDO:', '').strip()
        elif linea.startswith('MERCADO:'):
            pick_actual['mercado'] = linea.replace('MERCADO:', '').strip()
        elif linea.startswith('SELECCION:'):
            pick_actual['seleccion'] = linea.replace('SELECCION:', '').strip()
        elif linea.startswith('CUOTA:'):
            try:
                pick_actual['cuota'] = float(linea.replace('CUOTA:', '').strip())
            except:
                pick_actual['cuota'] = 0.0
        elif linea.startswith('CONFIANZA:'):
            try:
                pick_actual['confianza'] = float(linea.replace('CONFIANZA:', '').strip())
            except:
                pick_actual['confianza'] = 0.5
    
    if pick_actual and 'partido' in pick_actual:
        picks.append(pick_actual)
    return picks

def consolidar_picks(picks_todos, pesos):
    """
    Agrupa picks por (partido, mercado, seleccion) y calcula consenso ponderado por los pesos.
    """
    grupos = {}
    for pick in picks_todos:
        clave = (pick['partido'], pick['mercado'], pick['seleccion'])
        if clave not in grupos:
            grupos[clave] = []
        grupos[clave].append(pick)
    
    resultados = []
    for (partido, mercado, seleccion), lista in grupos.items():
        suma_pesos = 0
        suma_confianza_ponderada = 0
        cuotas = []
        for p in lista:
            peso = pesos.get(p['ia'], 1.0)
            suma_pesos += peso
            suma_confianza_ponderada += p['confianza'] * peso
            cuotas.append(p['cuota'])
        
        consenso_analistas = len(lista)
        cuota_promedio = sum(cuotas) / len(cuotas) if cuotas else 0
        confianza_promedio_ponderada = suma_confianza_ponderada / suma_pesos if suma_pesos > 0 else 0
        
        # Determinar recomendación
        if consenso_analistas >= 5:
            recomendacion = "Fuerte"
        elif consenso_analistas >= 3:
            recomendacion = "Moderada"
        else:
            recomendacion = "Baja"
        
        resultados.append({
            'partido': partido,
            'mercado': mercado,
            'seleccion': seleccion,
            'cuota_promedio': round(cuota_promedio, 2),
            'confianza_ponderada': round(confianza_promedio_ponderada, 2),
            'consenso_analistas': consenso_analistas,
            'recomendacion': recomendacion
        })
    
    resultados.sort(key=lambda x: (x['consenso_analistas'], x['confianza_ponderada']), reverse=True)
    return resultados

def main():
    print("📊 JUEZ PONDERADO (con pesos mejorados)")
    print("=" * 50)
    
    pesos = leer_pesos()
    if pesos:
        print("✅ Pesos cargados:")
        for ia, p in pesos.items():
            print(f"   {ia}: {p}")
    else:
        print("ℹ️ Usando pesos neutros (1.0)")
    
    archivos = glob.glob("picks_*.txt")
    if not archivos:
        print("❌ No se encontraron archivos de picks (picks_*.txt).")
        return
    
    todos_picks = []
    for archivo in archivos:
        picks = parsear_archivo_txt(archivo)
        todos_picks.extend(picks)
        print(f"✅ {len(picks)} picks cargados desde {archivo}")
    
    if not todos_picks:
        print("❌ No se encontraron picks en los archivos.")
        return
    
    print(f"\n📊 Total picks cargados: {len(todos_picks)}")
    consolidados = consolidar_picks(todos_picks, pesos)
    
    print("\n🏆 PICKS CONSOLIDADOS (ordenados por consenso y confianza ponderada):")
    for p in consolidados:
        print(f"{p['recomendacion']}: {p['partido']} | {p['mercado']} | {p['seleccion']} | Cuota: {p['cuota_promedio']} | Confianza pond: {p['confianza_ponderada']} | Consenso: {p['consenso_analistas']}")
    
    with open('veredicto_final.json', 'w') as f:
        json.dump(consolidados, f, indent=2)
    print("\n✅ Veredicto guardado en veredicto_final.json")

if __name__ == "__main__":
    main()