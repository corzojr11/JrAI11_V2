import asyncio
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_lab_overview_produces_segmentations(monkeypatch):
    from backend import main as backend_main

    df = pd.DataFrame(
        [
            {
                "id": 1,
                "fecha": "2026-01-01",
                "partido": "A vs B",
                "ia": "Motor-Propio",
                "mercado": "Ganador",
                "competicion": "Liga 1",
                "tipo_pick": "principal",
                "resultado": "ganada",
                "stake": 10,
                "ganancia": 12,
            },
            {
                "id": 2,
                "fecha": "2026-01-02",
                "partido": "C vs D",
                "ia": "Gemini",
                "mercado": "Over 2.5",
                "competicion": "Liga 1",
                "tipo_pick": "alternativa",
                "resultado": "perdida",
                "stake": 10,
                "ganancia": -10,
            },
        ]
    )

    monkeypatch.setattr(backend_main, "get_all_picks", lambda incluir_alternativas=True: df)

    payload = asyncio.run(
        backend_main.get_lab_overview(
            current_user={"role": "admin", "active": True, "username": "admin"},
            incluir_alternativas=True,
        )
    )

    assert payload["summary"]["total_picks"] == 2
    assert payload["summary"]["closed_picks"] == 2
    assert payload["by_tipo_pick"][0]["tipo_pick"] in {"principal", "alternativa"}
    assert payload["by_ia"][0]["picks"] == 1


def test_backtest_lab_exposes_series(monkeypatch):
    from backend import main as backend_main

    monkeypatch.setattr(
        backend_main,
        "calcular_metricas",
        lambda incluir_alternativas=False, fecha_inicio=None, fecha_fin=None: {
            "bankroll_inicial": 100,
            "bankroll_actual": 112,
            "total_picks": 2,
            "ganadas": 1,
            "perdidas": 1,
            "medias": 0,
            "roi_global": 12.0,
            "yield_global": 12.0,
            "fecha_min": "2026-01-01",
            "fecha_max": "2026-01-02",
            "serie_diaria": [{"fecha": "2026-01-01", "bankroll": 100}],
            "df_ia": pd.DataFrame([{"ia": "Motor-Propio", "roi": 12.0}]),
            "evolucion": pd.DataFrame([{"fecha": "2026-01-01", "bankroll": 100}]),
            "metricas_riesgo": {"sharpe_ratio": 1.0},
        },
    )

    payload = asyncio.run(
        backend_main.get_backtest_lab(
            current_user={"role": "admin", "active": True, "username": "admin"},
            incluir_alternativas=False,
        )
    )

    assert payload["summary"]["roi_global"] == 12.0
    assert payload["serie_diaria"][0]["bankroll"] == 100
    assert payload["roi_por_ia"][0]["ia"] == "Motor-Propio"
