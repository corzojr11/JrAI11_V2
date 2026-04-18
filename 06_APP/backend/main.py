from datetime import date, datetime
from typing import Any
import os
import sys
import time

import pandas as pd
from pydantic import BaseModel, Field

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from database import get_all_picks, get_prepared_matches, save_prepared_match
from backtest_engine import calcular_metricas
from services.match_prepare_service import (
    construir_ficha_preparada,
    obtener_partidos_por_fecha_local,
    obtener_partidos_proximos_locales,
    preparar_partido_desde_api,
)
from config import API_FOOTBALL_KEY, FRONTEND_ORIGINS, logger
from backend.routers import auth
from backend.core.dependencies import get_current_user, require_roles

app = FastAPI(
    title="Jr AI 11 Backend",
    version="1.0.0",
    description="Backend inicial para desacoplar lectura de datos desde Streamlit.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["auth"])


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "HTTP %s %s -> %s (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.exception("HTTP %s %s failed after %.1fms: %s", request.method, request.url.path, elapsed_ms, exc)
        raise


class PrepareMatchRequest(BaseModel):
    partido_texto: str
    fecha_iso: str = ""
    liga_key: str | None = None


class GenerateFichaRequest(BaseModel):
    data: dict[str, Any]
    manual: dict[str, Any] = Field(default_factory=dict)


def _to_jsonable(value: Any) -> Any:
    try:
        import math
        import numpy as np
        import pandas as pd
    except Exception:
        np = None
        pd = None
        math = None

    if value is None:
        return None
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if math and (math.isnan(value) or math.isinf(value)):
            return None
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if np is not None:
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            if np.isnan(value) or np.isinf(value):
                return None
            return float(value)
        if isinstance(value, np.bool_):
            return bool(value)
        if isinstance(value, np.ndarray):
            return [_to_jsonable(v) for v in value.tolist()]

    if pd is not None:
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        if value is pd.NaT:
            return None
        if isinstance(value, pd.DataFrame):
            return [_to_jsonable(r) for r in value.to_dict(orient="records")]
        if isinstance(value, pd.Series):
            return {str(k): _to_jsonable(v) for k, v in value.to_dict().items()}
        try:
            if pd.isna(value):
                return None
        except Exception:
            pass

    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]

    return str(value)

def _build_api_status_snapshot() -> dict[str, Any]:
    return {
        "captured_at": datetime.now().isoformat(),
        "config": {
            "api_football_key_configured": bool(API_FOOTBALL_KEY),
        },
        "odds": None,
        "odds_error": "Endpoint temporalmente simplificado: estado detallado de The Odds API no conectado todavía.",
        "football": None,
        "football_error": "Endpoint temporalmente simplificado: estado detallado de API-Football no conectado todavía.",
    }

def _apply_date_filter(df: pd.DataFrame, fecha_inicio: str | None, fecha_fin: str | None) -> pd.DataFrame:
    if df is None or df.empty or "fecha" not in df.columns:
        return df

    fechas = pd.to_datetime(df["fecha"], errors="coerce")
    mask = fechas.notna()

    if fecha_inicio:
        inicio = pd.to_datetime(fecha_inicio, errors="coerce")
        if pd.notna(inicio):
            mask &= fechas >= inicio

    if fecha_fin:
        fin = pd.to_datetime(fecha_fin, errors="coerce")
        if pd.notna(fin):
            mask &= fechas <= fin

    return df.loc[mask].copy()


def _dedupe_picks_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    dedupe_cols = [col for col in ["fecha", "partido", "ia", "mercado", "seleccion", "tipo_pick"] if col in df.columns]
    if not dedupe_cols:
        return df

    duplicates = int(df.duplicated(subset=dedupe_cols, keep="first").sum())
    if duplicates:
        logger.warning("Se detectaron %s filas duplicadas en picks con claves %s. Se eliminaran en la respuesta.", duplicates, dedupe_cols)
        return df.drop_duplicates(subset=dedupe_cols, keep="first").copy()
    return df


def _manual_coverage(manual: dict[str, Any]) -> float:
    required_fields = [
        "xg_local",
        "xg_visitante",
        "elo_local",
        "elo_visitante",
        "arbitro_manual",
        "forma_local_manual",
        "forma_visitante_manual",
        "h2h_manual",
        "lesiones_local_manual",
        "lesiones_visitante_manual",
        "alineacion_local_manual",
        "alineacion_visitante_manual",
        "cuotas_manual_resumen",
        "motivacion_local",
        "motivacion_visitante",
        "contexto_extra",
    ]
    completos = sum(1 for campo in required_fields if str(manual.get(campo, "") or "").strip())
    return round((completos / len(required_fields)) * 100, 2)


def _publication_limits_for_user(current_user: dict[str, Any]) -> dict[str, int | None]:
    role = str(current_user.get("role", "")).strip().lower()
    if role == "admin":
        return {"pendientes": None, "cerrados": None}

    plan = str(current_user.get("subscription_plan", "free") or "free").strip().lower()
    mapping = {
        "free": {"pendientes": 3, "cerrados": 3},
        "premium": {"pendientes": 10, "cerrados": 8},
        "vip": {"pendientes": 20, "cerrados": 15},
    }
    return mapping.get(plan, mapping["free"])


def _publication_sort_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    trabajo = df.copy()
    if "id" in trabajo.columns:
        trabajo = trabajo.sort_values(by="id", ascending=False)
    elif "timestamp" in trabajo.columns:
        trabajo = trabajo.sort_values(by="timestamp", ascending=False)
    return trabajo.reset_index(drop=True)


def _publication_pick_copy(row: dict[str, Any]) -> dict[str, str]:
    partido = str(row.get("partido", "")).strip()
    mercado = str(row.get("mercado", "")).strip()
    seleccion = str(row.get("seleccion", "")).strip()
    confianza = int(float(row.get("confianza", 0) or 0) * 100)
    cuota = float(row.get("cuota", 0) or 0)
    resumen = str(row.get("analisis_breve", "") or "").strip()
    resumen_corto = resumen[:220] + ("..." if len(resumen) > 220 else "")

    return {
        "copy_corto": f"{partido}\n{mercado}: {seleccion}\nCuota: {cuota:.2f} | Confianza: {confianza}%",
        "copy_social": (
            "Jr AI 11 | PICK OFICIAL\n\n"
            f"{partido}\n"
            f"{mercado}: {seleccion}\n"
            f"Cuota publicada: {cuota:.2f}\n"
            f"Confianza declarada: {confianza}%\n\n"
            f"Lectura clave: {resumen_corto}\n\n"
            "Verifica cuota final antes de entrar.\n"
            "#JrAI11 #PickOficial #ApuestasDeportivas"
        ),
        "copy_largo": (
            f"Jr AI 11 | PICK OFICIAL\n\n"
            f"{partido}\n"
            f"{mercado}: {seleccion}\n"
            f"Cuota: {cuota:.2f}\n"
            f"Confianza: {confianza}%\n"
            f"IA / Fuente: {str(row.get('ia', '') or '')}\n"
            f"Lectura breve: {resumen_corto}"
        ),
    }


def _publication_result_copy(row: dict[str, Any]) -> dict[str, str]:
    partido = str(row.get("partido", "")).strip()
    mercado = str(row.get("mercado", "")).strip()
    seleccion = str(row.get("seleccion", "")).strip()
    estado = str(row.get("resultado", "")).strip().lower()
    etiqueta = "WIN"
    if estado == "perdida":
        etiqueta = "LOSS"
    elif estado == "media":
        etiqueta = "PUSH"

    cuota = float(row.get("cuota", 0) or 0)
    ganancia = float(row.get("ganancia", 0) or 0)

    return {
        "copy_corto": f"{partido}\n{mercado}: {seleccion}\nResultado: {etiqueta}",
        "copy_social": (
            f"Jr AI 11 | {etiqueta}\n\n"
            f"{partido}\n"
            f"{mercado}: {seleccion}\n"
            f"Cuota publicada: {cuota:.2f}\n"
            f"Ganancia registrada: {ganancia:.2f}\n\n"
            "Seguimiento real del sistema.\n"
            "#JrAI11 #ResultadoPick #ApuestasDeportivas"
        ),
        "copy_largo": (
            f"Jr AI 11 | {etiqueta}\n\n"
            f"{partido}\n"
            f"{mercado}: {seleccion}\n"
            f"Cuota: {cuota:.2f}\n"
            f"Ganancia: {ganancia:.2f}\n"
            f"IA / Fuente: {str(row.get('ia', '') or '')}"
        ),
    }


def _publication_pdf_headers(filename: str) -> dict[str, str]:
    return {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
    }


def _analysis_base_df(
    incluir_alternativas: bool = False,
    fecha_inicio: str | None = None,
    fecha_fin: str | None = None,
) -> pd.DataFrame:
    df = get_all_picks(incluir_alternativas=incluir_alternativas)
    if df is None or df.empty:
        return pd.DataFrame()

    trabajo = df.copy()
    if "fecha" in trabajo.columns:
        fechas = pd.to_datetime(trabajo["fecha"], errors="coerce")
        mask = fechas.notna()
        if fecha_inicio:
            inicio = pd.to_datetime(fecha_inicio, errors="coerce")
            if pd.notna(inicio):
                mask &= fechas >= inicio
        if fecha_fin:
            fin = pd.to_datetime(fecha_fin, errors="coerce")
            if pd.notna(fin):
                mask &= fechas <= fin
        trabajo = trabajo.loc[mask].copy()

    for columna, valor in {
        "resultado": "pendiente",
        "tipo_pick": "principal",
        "ia": "Sin IA",
        "mercado": "Sin mercado",
        "competicion": "Sin competencia",
        "stake": 0.0,
        "ganancia": 0.0,
    }.items():
        if columna not in trabajo.columns:
            trabajo[columna] = valor

    if "id" in trabajo.columns:
        trabajo["id"] = pd.to_numeric(trabajo["id"], errors="coerce").fillna(0).astype(int)
    if "stake" in trabajo.columns:
        trabajo["stake"] = pd.to_numeric(trabajo["stake"], errors="coerce").fillna(0.0)
    if "ganancia" in trabajo.columns:
        trabajo["ganancia"] = pd.to_numeric(trabajo["ganancia"], errors="coerce").fillna(0.0)
    if "cuota" in trabajo.columns:
        trabajo["cuota"] = pd.to_numeric(trabajo["cuota"], errors="coerce").fillna(0.0)
    if "confianza" in trabajo.columns:
        trabajo["confianza"] = pd.to_numeric(trabajo["confianza"], errors="coerce").fillna(0.0)

    return _dedupe_picks_frame(trabajo)


def _analysis_group_breakdown(df: pd.DataFrame, field: str, limit: int = 10) -> list[dict[str, Any]]:
    if df is None or df.empty or field not in df.columns:
        return []

    trabajo = df.copy()
    trabajo[field] = trabajo[field].fillna("Sin dato").astype(str)
    trabajo["__closed__"] = trabajo["resultado"].astype(str).isin(["ganada", "perdida", "media"])
    trabajo["__win__"] = trabajo["resultado"].astype(str) == "ganada"
    trabajo["__loss__"] = trabajo["resultado"].astype(str) == "perdida"
    trabajo["__media__"] = trabajo["resultado"].astype(str) == "media"

    resumen = (
        trabajo.groupby(field, dropna=False)
        .agg(
            picks=("id", "count"),
            ganadas=("__win__", "sum"),
            perdidas=("__loss__", "sum"),
            medias=("__media__", "sum"),
            stake_total=("stake", "sum"),
            ganancia_total=("ganancia", "sum"),
        )
        .reset_index()
    )

    resumen["roi"] = resumen.apply(
        lambda row: (float(row["ganancia_total"]) / float(row["stake_total"]) * 100)
        if float(row["stake_total"] or 0) > 0
        else 0.0,
        axis=1,
    ).round(2)
    resumen["win_rate"] = resumen.apply(
        lambda row: (float(row["ganadas"]) / max(1.0, float(row["ganadas"] + row["perdidas"])) * 100),
        axis=1,
    ).round(2)
    resumen = resumen.sort_values(by=["roi", "picks"], ascending=[False, False]).head(limit)
    return _to_jsonable(resumen)


def _analysis_type_breakdown(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty or "tipo_pick" not in df.columns:
        return []
    return _analysis_group_breakdown(df, "tipo_pick", limit=10)


def _analysis_summary(df: pd.DataFrame) -> dict[str, Any]:
    if df is None or df.empty:
        return {
            "total_picks": 0,
            "closed_picks": 0,
            "pending_picks": 0,
            "stake_total": 0.0,
            "ganancia_total": 0.0,
            "roi_global": 0.0,
            "yield_global": 0.0,
            "win_rate": 0.0,
        }

    cerrados = df[df["resultado"].astype(str) != "pendiente"].copy()
    ganadas = int((cerrados["resultado"].astype(str) == "ganada").sum())
    perdidas = int((cerrados["resultado"].astype(str) == "perdida").sum())
    medias = int((cerrados["resultado"].astype(str) == "media").sum())
    stake_total = float(cerrados["stake"].sum()) if "stake" in cerrados.columns else 0.0
    ganancia_total = float(cerrados["ganancia"].sum()) if "ganancia" in cerrados.columns else 0.0
    roi_global = (ganancia_total / stake_total * 100) if stake_total > 0 else 0.0
    total = ganadas + perdidas
    win_rate = (ganadas / total * 100) if total > 0 else 0.0
    return {
        "total_picks": int(len(df)),
        "closed_picks": int(len(cerrados)),
        "pending_picks": int((df["resultado"].astype(str) == "pendiente").sum()),
        "stake_total": round(stake_total, 2),
        "ganancia_total": round(ganancia_total, 2),
        "roi_global": round(roi_global, 2),
        "yield_global": round((ganancia_total / max(1.0, len(cerrados))) if len(cerrados) else 0.0, 2),
        "win_rate": round(win_rate, 2),
        "ganadas": ganadas,
        "perdidas": perdidas,
        "medias": medias,
    }

@app.get("/")
async def root():
    return {"ok": True, "service": "Jr AI 11 Backend", "docs": "/docs"}

@app.get("/picks")
@app.get("/api/picks")
async def get_picks(
    current_user: dict[str, Any] = Depends(get_current_user),
    incluir_alternativas: bool = Query(False),
    fecha_inicio: str | None = Query(None),
    fecha_fin: str | None = Query(None),
):
    try:
        df = get_all_picks(incluir_alternativas=incluir_alternativas)
        df = _dedupe_picks_frame(df)
        df = _apply_date_filter(df, fecha_inicio, fecha_fin)
        if df is None:
            return {"picks": [], "count": 0}
        picks = _to_jsonable(df)
        return {"picks": picks, "count": len(picks) if isinstance(picks, list) else 0}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching picks: {e}")

@app.get("/metrics")
@app.get("/api/metrics")
async def get_metrics(
    current_user: dict[str, Any] = Depends(get_current_user),
    incluir_alternativas: bool = Query(False),
    fecha_inicio: str | None = Query(None),
    fecha_fin: str | None = Query(None),
):
    try:
        return {
            "metrics": _to_jsonable(
                calcular_metricas(
                    incluir_alternativas=incluir_alternativas,
                    fecha_inicio=fecha_inicio,
                    fecha_fin=fecha_fin,
                )
            )
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculating metrics: {e}")

@app.get("/api/partidos_por_fecha")
async def get_partidos_por_fecha(
    current_user: dict[str, Any] = Depends(require_roles("admin")),
    fecha: str = Query(...),
):
    try:
        partidos, error = obtener_partidos_por_fecha_local(fecha, solo_futuros=True)
        if error:
            raise HTTPException(status_code=400, detail=error)
        return {"fecha": fecha, "partidos": _to_jsonable(partidos), "count": len(partidos) if partidos else 0}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching partidos: {e}")

@app.get("/api/preparation/proximos")
async def get_preparation_proximos(
    current_user: dict[str, Any] = Depends(require_roles("admin")),
    dias: int = Query(3, ge=1, le=7),
):
    try:
        partidos, error = obtener_partidos_proximos_locales(dias_adelante=dias)
        if error:
            raise HTTPException(status_code=400, detail=error)
        return {"dias": dias, "partidos": _to_jsonable(partidos), "count": len(partidos) if partidos else 0}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching proximos: {e}")

@app.post("/api/preparation/prepare")
async def prepare_match(
    payload: PrepareMatchRequest,
    current_user: dict[str, Any] = Depends(require_roles("admin")),
):
    try:
        data, error = preparar_partido_desde_api(
            payload.partido_texto,
            fecha_iso=payload.fecha_iso or "",
            liga_key=payload.liga_key,
        )
        if error:
            raise HTTPException(status_code=400, detail=error)
        return {"data": _to_jsonable(data)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error preparing match: {e}")

@app.post("/api/preparation/generate")
async def generate_ficha(
    payload: GenerateFichaRequest,
    current_user: dict[str, Any] = Depends(require_roles("admin")),
):
    try:
        data = payload.data or {}
        manual = payload.manual or {}
        ficha_texto = construir_ficha_preparada(data, manual)
        cobertura_pct = _manual_coverage(manual)
        saved_result = save_prepared_match(
            data.get("partido", ""),
            data.get("fecha", ""),
            data.get("liga_nombre", ""),
            cobertura_pct,
            ficha_texto,
        )
        return {
            "ficha_texto": ficha_texto,
            "cobertura_pct": cobertura_pct,
            "saved_result": _to_jsonable(saved_result),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating ficha: {e}")

@app.get("/api/preparation/history")
async def get_preparation_history(
    current_user: dict[str, Any] = Depends(require_roles("admin")),
    limit: int = Query(12, ge=1, le=50),
):
    try:
        historial = get_prepared_matches(limit=limit)
        return {"items": _to_jsonable(historial), "count": len(historial) if historial is not None else 0}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching history: {e}")

@app.get("/api/api-status")
async def get_api_status():
    try:
        return _build_api_status_snapshot()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching API status: {e}")


@app.get("/api/lab")
async def get_lab_overview(
    current_user: dict[str, Any] = Depends(require_roles("admin")),
    incluir_alternativas: bool = Query(True),
    fecha_inicio: str | None = Query(None),
    fecha_fin: str | None = Query(None),
):
    try:
        df = _analysis_base_df(incluir_alternativas=incluir_alternativas, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)
        summary = _analysis_summary(df)
        return {
            "user": _to_jsonable(current_user),
            "range": {
                "fecha_min": str(df["fecha"].min()) if not df.empty and "fecha" in df.columns else None,
                "fecha_max": str(df["fecha"].max()) if not df.empty and "fecha" in df.columns else None,
            },
            "summary": summary,
            "by_tipo_pick": _analysis_type_breakdown(df),
            "by_ia": _analysis_group_breakdown(df, "ia", limit=12),
            "by_mercado": _analysis_group_breakdown(df, "mercado", limit=12),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching lab overview: {e}")


@app.get("/api/analysis/segments")
async def get_analysis_segments(
    current_user: dict[str, Any] = Depends(require_roles("admin")),
    incluir_alternativas: bool = Query(True),
    fecha_inicio: str | None = Query(None),
    fecha_fin: str | None = Query(None),
):
    try:
        df = _analysis_base_df(incluir_alternativas=incluir_alternativas, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)
        return {
            "user": _to_jsonable(current_user),
            "segments": {
                "ia": _analysis_group_breakdown(df, "ia", limit=12),
                "mercado": _analysis_group_breakdown(df, "mercado", limit=12),
                "competicion": _analysis_group_breakdown(df, "competicion", limit=12),
            },
            "by_tipo_pick": _analysis_type_breakdown(df),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching analysis segments: {e}")


@app.get("/api/backtest")
async def get_backtest_lab(
    current_user: dict[str, Any] = Depends(require_roles("admin")),
    incluir_alternativas: bool = Query(False),
    fecha_inicio: str | None = Query(None),
    fecha_fin: str | None = Query(None),
):
    try:
        metrics = calcular_metricas(
            incluir_alternativas=incluir_alternativas,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
        )
        metrics_json = _to_jsonable(metrics)
        serie_diaria = metrics_json.get("serie_diaria", []) if isinstance(metrics_json, dict) else []
        df_ia = metrics_json.get("df_ia", []) if isinstance(metrics_json, dict) else []
        return {
            "user": _to_jsonable(current_user),
            "summary": metrics_json,
            "serie_diaria": serie_diaria,
            "roi_por_ia": df_ia,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching backtest lab: {e}")


@app.get("/api/publication/overview")
async def get_publication_overview(current_user: dict[str, Any] = Depends(get_current_user)):
    try:
        df = _dedupe_picks_frame(get_all_picks(incluir_alternativas=True))
        if df is None:
            df = pd.DataFrame()

        if not df.empty and "tipo_pick" in df.columns:
            df = df[df["tipo_pick"].astype(str) == "principal"].copy()

        if not df.empty and "resultado" not in df.columns:
            df["resultado"] = "pendiente"

        df = _publication_sort_frame(df)
        limits = _publication_limits_for_user(current_user)

        pendientes = df[df["resultado"].astype(str) == "pendiente"].copy() if not df.empty else pd.DataFrame()
        cerrados = df[df["resultado"].astype(str).isin(["ganada", "perdida", "media"])].copy() if not df.empty else pd.DataFrame()

        if limits["pendientes"] is not None:
            pendientes = pendientes.head(int(limits["pendientes"]))
        if limits["cerrados"] is not None:
            cerrados = cerrados.head(int(limits["cerrados"]))

        pending_rows = [
            {
                "id": int(row.get("id", 0) or 0),
                "partido": str(row.get("partido", "") or ""),
                "fecha": str(row.get("fecha", "") or ""),
                "mercado": str(row.get("mercado", "") or ""),
                "seleccion": str(row.get("seleccion", "") or ""),
                "cuota": float(row.get("cuota", 0) or 0),
                "confianza": float(row.get("confianza", 0) or 0),
                "ia": str(row.get("ia", "") or ""),
                "analisis_breve": str(row.get("analisis_breve", "") or ""),
                "copy": _publication_pick_copy(row),
            }
            for _, row in pendientes.iterrows()
        ]

        closed_rows = [
            {
                "id": int(row.get("id", 0) or 0),
                "partido": str(row.get("partido", "") or ""),
                "fecha": str(row.get("fecha", "") or ""),
                "mercado": str(row.get("mercado", "") or ""),
                "seleccion": str(row.get("seleccion", "") or ""),
                "cuota": float(row.get("cuota", 0) or 0),
                "ganancia": float(row.get("ganancia", 0) or 0),
                "resultado": str(row.get("resultado", "") or ""),
                "ia": str(row.get("ia", "") or ""),
                "copy": _publication_result_copy(row),
            }
            for _, row in cerrados.iterrows()
        ]

        try:
            metrics = calcular_metricas(incluir_alternativas=False)
        except Exception:
            metrics = {}

        return {
            "user": _to_jsonable(current_user),
            "can_publish": str(current_user.get("role", "")).strip().lower() == "admin",
            "limits": _to_jsonable(limits),
            "stats": {
                "total_picks": len(df),
                "pendientes_principales": len(pendientes),
                "cerrados_principales": len(cerrados),
                "roi_global": metrics.get("roi_global", 0) if isinstance(metrics, dict) else 0,
                "yield_global": metrics.get("yield_global", 0) if isinstance(metrics, dict) else 0,
            },
            "feed": {
                "pendientes": _to_jsonable(pending_rows),
                "cerrados": _to_jsonable(closed_rows),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching publication overview: {e}")


@app.get("/api/publication/export/pick/{pick_id}")
async def export_publication_pick(
    pick_id: int,
    current_user: dict[str, Any] = Depends(require_roles("admin")),
):
    try:
        df = _dedupe_picks_frame(get_all_picks(incluir_alternativas=True))
        if df is None or df.empty or "id" not in df.columns:
            raise HTTPException(status_code=404, detail="Pick not found")
        match = df[df["id"] == pick_id]
        if match.empty:
            raise HTTPException(status_code=404, detail="Pick not found")
        row = match.iloc[0].to_dict()
        payload = _publication_pick_copy(row)
        return {
            "id": pick_id,
            "kind": "pick",
            "title": str(row.get("partido", "") or ""),
            "payload": _to_jsonable(payload),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting pick: {e}")


@app.get("/api/publication/export/result/{pick_id}")
async def export_publication_result(
    pick_id: int,
    current_user: dict[str, Any] = Depends(require_roles("admin")),
):
    try:
        df = _dedupe_picks_frame(get_all_picks(incluir_alternativas=True))
        if df is None or df.empty or "id" not in df.columns:
            raise HTTPException(status_code=404, detail="Result not found")
        match = df[df["id"] == pick_id]
        if match.empty:
            raise HTTPException(status_code=404, detail="Result not found")
        row = match.iloc[0].to_dict()
        payload = _publication_result_copy(row)
        return {
            "id": pick_id,
            "kind": "result",
            "title": str(row.get("partido", "") or ""),
            "payload": _to_jsonable(payload),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting result: {e}")


@app.get("/api/publication/export/pick/{pick_id}/pdf-social")
async def export_publication_pick_pdf_social(
    pick_id: int,
    current_user: dict[str, Any] = Depends(require_roles("admin")),
):
    try:
        from pdf_generator import generar_pdf_pick_social

        df = _dedupe_picks_frame(get_all_picks(incluir_alternativas=True))
        if df is None or df.empty or "id" not in df.columns:
            raise HTTPException(status_code=404, detail="Pick not found")
        match = df[df["id"] == pick_id]
        if match.empty:
            raise HTTPException(status_code=404, detail="Pick not found")
        row = match.iloc[0].to_dict()
        pdf_bytes = generar_pdf_pick_social(row)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers=_publication_pdf_headers(f"pick_social_{pick_id}.pdf"),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting pick pdf: {e}")


@app.get("/api/publication/export/result/{pick_id}/pdf-social")
async def export_publication_result_pdf_social(
    pick_id: int,
    current_user: dict[str, Any] = Depends(require_roles("admin")),
):
    try:
        from pdf_generator import generar_pdf_resultado_social

        df = _dedupe_picks_frame(get_all_picks(incluir_alternativas=True))
        if df is None or df.empty or "id" not in df.columns:
            raise HTTPException(status_code=404, detail="Result not found")
        match = df[df["id"] == pick_id]
        if match.empty:
            raise HTTPException(status_code=404, detail="Result not found")
        row = match.iloc[0].to_dict()
        pdf_bytes = generar_pdf_resultado_social(row)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers=_publication_pdf_headers(f"resultado_social_{pick_id}.pdf"),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting result pdf: {e}")


@app.get("/api/publication/export/boletin.pdf")
async def export_publication_boletin_pdf(
    current_user: dict[str, Any] = Depends(require_roles("admin")),
):
    try:
        from pdf_generator import generar_pdf_desde_dataframe

        df = _dedupe_picks_frame(get_all_picks(incluir_alternativas=True))
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail="No hay picks para exportar")
        pdf_bytes = generar_pdf_desde_dataframe(
            df,
            titulo="Jr AI 11 - Boletin de Picks",
            subtitulo="Boletin compartible desde la base interna",
        )
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers=_publication_pdf_headers("boletin_picks.pdf"),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting boletin: {e}")


@app.post("/api/publication/telegram/pick/{pick_id}")
async def send_publication_pick_to_telegram(
    pick_id: int,
    current_user: dict[str, Any] = Depends(require_roles("admin")),
):
    try:
        from pdf_generator import generar_pdf_pick_social
        from services.telegram_service import telegram_config_ok, enviar_paquete_telegram

        if not telegram_config_ok():
            raise HTTPException(status_code=400, detail="Telegram no configurado")

        df = _dedupe_picks_frame(get_all_picks(incluir_alternativas=True))
        if df is None or df.empty or "id" not in df.columns:
            raise HTTPException(status_code=404, detail="Pick not found")
        match = df[df["id"] == pick_id]
        if match.empty:
            raise HTTPException(status_code=404, detail="Pick not found")
        row = match.iloc[0].to_dict()
        payload = _publication_pick_copy(row)
        pdf_social = generar_pdf_pick_social(row)
        ok, detalle = enviar_paquete_telegram(
            payload["copy_social"],
            pdf_social,
            f"pick_social_{pick_id}.pdf",
            caption=f"Pick oficial | {row.get('partido', '')}",
        )
        if not ok:
            raise HTTPException(status_code=400, detail=detalle)
        return {"ok": True, "message": detalle}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error sending pick to Telegram: {e}")


@app.post("/api/publication/telegram/result/{pick_id}")
async def send_publication_result_to_telegram(
    pick_id: int,
    current_user: dict[str, Any] = Depends(require_roles("admin")),
):
    try:
        from pdf_generator import generar_pdf_resultado_social
        from services.telegram_service import telegram_config_ok, enviar_paquete_telegram

        if not telegram_config_ok():
            raise HTTPException(status_code=400, detail="Telegram no configurado")

        df = _dedupe_picks_frame(get_all_picks(incluir_alternativas=True))
        if df is None or df.empty or "id" not in df.columns:
            raise HTTPException(status_code=404, detail="Result not found")
        match = df[df["id"] == pick_id]
        if match.empty:
            raise HTTPException(status_code=404, detail="Result not found")
        row = match.iloc[0].to_dict()
        payload = _publication_result_copy(row)
        pdf_social = generar_pdf_resultado_social(row)
        ok, detalle = enviar_paquete_telegram(
            payload["copy_social"],
            pdf_social,
            f"resultado_social_{pick_id}.pdf",
            caption=f"Resultado | {row.get('partido', '')}",
        )
        if not ok:
            raise HTTPException(status_code=400, detail=detalle)
        return {"ok": True, "message": detalle}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error sending result to Telegram: {e}")


@app.post("/api/publication/telegram/boletin")
async def send_publication_boletin_to_telegram(
    current_user: dict[str, Any] = Depends(require_roles("admin")),
):
    try:
        from pdf_generator import generar_pdf_desde_dataframe
        from services.telegram_service import telegram_config_ok, enviar_documento_telegram

        if not telegram_config_ok():
            raise HTTPException(status_code=400, detail="Telegram no configurado")

        df = _dedupe_picks_frame(get_all_picks(incluir_alternativas=True))
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail="No hay picks para exportar")
        pdf_bytes = generar_pdf_desde_dataframe(
            df,
            titulo="Jr AI 11 - Boletin de Picks",
            subtitulo="Boletin compartible desde la base interna",
        )
        ok, detalle = enviar_documento_telegram(
            pdf_bytes,
            "boletin_picks.pdf",
            caption="Jr AI 11 - Boletin compartible desde la base interna",
        )
        if not ok:
            raise HTTPException(status_code=400, detail=detalle)
        return {"ok": True, "message": detalle}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error sending boletin to Telegram: {e}")
