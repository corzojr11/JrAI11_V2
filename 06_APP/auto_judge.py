import json
import os
from datetime import datetime
from database import get_all_picks
from core.judge import consolidar_picks

# Carpeta donde se guardarán los veredictos
VEREDICTOS_DIR = "veredictos"
try:
    os.makedirs(VEREDICTOS_DIR, exist_ok=True)
    print(f"✅ Carpeta de veredictos: {os.path.abspath(VEREDICTOS_DIR)}")
except Exception as e:
    print(f"❌ Error al crear carpeta: {e}")
    exit(1)

def ejecutar_juez():
    print(f"🚀 Ejecutando juez automático - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Directorio actual: {os.getcwd()}")

    # Cargar pesos si existen
    pesos = {}
    if os.path.exists('pesos_ia.json'):
        with open('pesos_ia.json', 'r') as f:
            pesos = json.load(f)
        print("✅ Pesos cargados desde pesos_ia.json")
    else:
        print("⚠️ No se encontró pesos_ia.json. Usando pesos neutros.")

    # Obtener picks pendientes
    df = get_all_picks()
    if df.empty:
        print("📭 No hay picks en la base de datos.")
        return

    pendientes = df[df['resultado'] == 'pendiente']
    if pendientes.empty:
        print("📭 No hay picks pendientes.")
        return

    print(f"📊 {len(pendientes)} picks pendientes encontrados.")

    # Consolidar picks
    try:
        resultados = consolidar_picks(pendientes, pesos)
    except Exception as e:
        print(f"❌ Error al consolidar picks: {e}")
        return

    # Guardar veredicto en la subcarpeta
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archivo = os.path.join(VEREDICTOS_DIR, f"veredicto_{timestamp}.json")
    try:
        with open(archivo, 'w') as f:
            json.dump(resultados, f, indent=2)
        print(f"✅ Veredicto guardado en {archivo}")
    except Exception as e:
        print(f"❌ Error al guardar archivo: {e}")
        return

    # Mostrar resumen
    print("\n🏆 **TOP 3 PICKS**")
    for i, p in enumerate(resultados[:3]):
        print(f"{i+1}. {p['Partido']} | {p['Mercado']} | {p['Seleccion']} | Cuota: {p['Cuota Promedio']} | Confianza: {p['Confianza Ponderada']} | Consenso: {p['Consenso']}")

if __name__ == "__main__":
    ejecutar_juez()