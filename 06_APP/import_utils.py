import json
from datetime import datetime

import pandas as pd


def leer_archivo_subido(file) -> str:
    file.seek(0)
    contenido_bytes = file.read()
    file.seek(0)

    for encoding in ("utf-8", "latin-1"):
        try:
            return contenido_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue

    raise ValueError("No se pudo leer el archivo. Codificacion no soportada.")


def extraer_cuota_de_seleccion(seleccion):
    """
    Extrae la cuota de un string como "Over 3.5 @ 1.95".
    Devuelve (seleccion_limpia, cuota).
    """
    if isinstance(seleccion, str) and "@" in seleccion:
        partes = seleccion.split("@")
        seleccion_limpia = partes[0].strip()
        try:
            cuota_str = partes[1].strip().split()[0].replace(",", ".")
            cuota = float(cuota_str)
            return seleccion_limpia, cuota
        except Exception:
            return seleccion, 0.0
    return seleccion, 0.0


def normalizar_dataframe_picks(df: pd.DataFrame) -> pd.DataFrame:
    required = ["partido", "mercado", "seleccion", "cuota", "fecha", "ia"]
    for col in required:
        if col not in df.columns:
            df[col] = None

    if "confianza" not in df.columns:
        df["confianza"] = None
    if "analisis_breve" not in df.columns:
        df["analisis_breve"] = ""
    if "tipo_pick" not in df.columns:
        df["tipo_pick"] = "principal"

    df["cuota"] = pd.to_numeric(df["cuota"], errors="coerce")
    df["confianza"] = pd.to_numeric(df["confianza"], errors="coerce")
    df["fecha"] = df["fecha"].fillna(datetime.now().strftime("%Y-%m-%d"))

    df["ia"] = df["ia"].fillna("Desconocida").astype(str).str.strip()
    df["partido"] = df["partido"].fillna("").astype(str).str.strip()
    df["mercado"] = df["mercado"].fillna("").astype(str).str.strip()
    df["seleccion"] = df["seleccion"].fillna("").astype(str).str.strip()
    df["analisis_breve"] = df["analisis_breve"].fillna("").astype(str).str.strip()
    df["tipo_pick"] = (
        df["tipo_pick"].fillna("principal").astype(str).str.strip().str.lower()
    )

    df = df[df["partido"] != ""]
    df = df[df["mercado"] != ""]
    df = df[df["seleccion"] != ""]
    df = df[df["cuota"].notna() & (df["cuota"] >= 1.01)]

    if df.empty:
        raise ValueError(
            "No se encontraron picks validos con partido, mercado, seleccion y cuota >= 1.01."
        )

    return df[required + ["confianza", "analisis_breve", "tipo_pick"]]


def parse_txt_file(file) -> pd.DataFrame:
    contenido = leer_archivo_subido(file)
    lineas = contenido.splitlines()
    ia = "Desconocida"
    fecha = None
    picks = []
    pick_actual = {}
    dentro_pick = False

    for linea in lineas:
        linea = linea.strip()
        if not linea:
            continue

        if linea.startswith("IA:"):
            ia = linea.replace("IA:", "", 1).strip() or "Desconocida"
            continue

        if linea.startswith("FECHA:"):
            fecha_str = linea.replace("FECHA:", "", 1).strip()
            try:
                datetime.strptime(fecha_str, "%Y-%m-%d")
                fecha = fecha_str
            except Exception:
                fecha = None
            continue

        if linea.startswith("---"):
            if pick_actual and "partido" in pick_actual:
                pick_actual["ia"] = ia
                if fecha:
                    pick_actual["fecha"] = fecha
                picks.append(pick_actual)
            pick_actual = {}
            dentro_pick = True
            continue

        if not dentro_pick and not pick_actual:
            dentro_pick = True

        if not dentro_pick:
            continue

        if linea.startswith("PARTIDO:"):
            pick_actual["partido"] = linea.replace("PARTIDO:", "", 1).strip()
        elif linea.startswith("MERCADO:"):
            pick_actual["mercado"] = linea.replace("MERCADO:", "", 1).strip()
        elif linea.startswith("SELECCION:"):
            seleccion_raw = linea.replace("SELECCION:", "", 1).strip()
            seleccion_limpia, cuota_extraida = extraer_cuota_de_seleccion(seleccion_raw)
            pick_actual["seleccion"] = seleccion_limpia
            if cuota_extraida > 0:
                pick_actual["cuota"] = cuota_extraida
        elif linea.startswith("CUOTA:"):
            try:
                cuota_str = linea.replace("CUOTA:", "", 1).strip().replace(",", ".")
                pick_actual["cuota"] = float(cuota_str)
            except Exception:
                pass
        elif linea.startswith("CONFIANZA:"):
            try:
                conf_str = linea.replace("CONFIANZA:", "", 1).strip().replace(",", ".")
                pick_actual["confianza"] = float(conf_str)
            except Exception:
                pick_actual["confianza"] = None
        elif linea.startswith("ANALISIS:"):
            pick_actual["analisis_breve"] = linea.replace("ANALISIS:", "", 1).strip()

    if pick_actual and "partido" in pick_actual:
        pick_actual["ia"] = ia
        if fecha:
            pick_actual["fecha"] = fecha
        picks.append(pick_actual)

    if not picks:
        raise ValueError("No se encontraron picks validos en el archivo de texto.")

    df = pd.DataFrame(picks)
    if "fecha" not in df.columns and fecha:
        df["fecha"] = fecha
    df["tipo_pick"] = "principal"
    return normalizar_dataframe_picks(df)


def parse_json_file(file) -> pd.DataFrame:
    contenido = leer_archivo_subido(file)

    try:
        data = json.loads(contenido)
    except json.JSONDecodeError as e:
        raise ValueError(f"Error decodificando JSON: {e}")

    if isinstance(data, dict):
        data = [data]

    picks = []
    for item in data:
        ia = item.get("ia", "Desconocida")
        fecha = item.get("fecha", datetime.now().strftime("%Y-%m-%d"))
        partido = item.get("partido", "")

        pick_principal = item.get("pick")
        if isinstance(pick_principal, dict) and pick_principal.get("emitido") is True:
            seleccion_raw = pick_principal.get("seleccion", "")
            seleccion_limpia, cuota_extraida = extraer_cuota_de_seleccion(seleccion_raw)
            picks.append(
                {
                    "ia": ia,
                    "fecha": fecha,
                    "partido": partido,
                    "mercado": pick_principal.get("mercado", ""),
                    "seleccion": seleccion_limpia,
                    "cuota": cuota_extraida
                    if cuota_extraida > 0
                    else pick_principal.get("cuota", 0.0),
                    "confianza": pick_principal.get("confianza", 0.5),
                    "analisis_breve": str(pick_principal.get("razonamiento", ""))[:100],
                    "tipo_pick": "principal",
                }
            )

        alternativas = item.get("alternativas_consideradas", [])
        if isinstance(alternativas, list):
            for alt in alternativas:
                if not isinstance(alt, dict):
                    continue
                if "mercado" not in alt or "seleccion" not in alt:
                    continue

                seleccion_raw = alt.get("seleccion", "")
                seleccion_limpia, cuota_extraida = extraer_cuota_de_seleccion(seleccion_raw)
                picks.append(
                    {
                        "ia": ia,
                        "fecha": fecha,
                        "partido": partido,
                        "mercado": alt.get("mercado", ""),
                        "seleccion": seleccion_limpia,
                        "cuota": cuota_extraida
                        if cuota_extraida > 0
                        else alt.get("cuota", 0.0),
                        "confianza": alt.get("confianza", 0.5),
                        "analisis_breve": str(alt.get("descartado_por", ""))[:100],
                        "tipo_pick": "alternativa",
                    }
                )

    if not picks:
        raise ValueError("No se encontraron picks validos en el archivo JSON.")

    df = pd.DataFrame(picks)
    return normalizar_dataframe_picks(df)


def validate_and_load_file(file) -> pd.DataFrame:
    try:
        contenido_muestra = leer_archivo_subido(file)[:1024]
    except Exception:
        contenido_muestra = ""

    stripped = contenido_muestra.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return parse_json_file(file)
    return parse_txt_file(file)
