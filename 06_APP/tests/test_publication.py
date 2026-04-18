import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_publication_copies_have_expected_shape():
    from backend.main import _publication_pick_copy, _publication_result_copy

    pick_copy = _publication_pick_copy(
        {
            "partido": "A vs B",
            "mercado": "Ganador",
            "seleccion": "A",
            "cuota": 2.1,
            "confianza": 0.83,
            "analisis_breve": "Texto de analisis para publicar",
            "ia": "Motor-Propio",
        }
    )
    result_copy = _publication_result_copy(
        {
            "partido": "A vs B",
            "mercado": "Ganador",
            "seleccion": "A",
            "cuota": 2.1,
            "ganancia": 11.5,
            "resultado": "ganada",
            "ia": "Motor-Propio",
        }
    )

    assert "PICK OFICIAL" in pick_copy["copy_social"]
    assert "WIN" in result_copy["copy_social"]


def test_publication_overview_respects_member_limits(monkeypatch):
    from backend import main as backend_main

    data = pd.DataFrame(
        [
            {
                "id": 1,
                "tipo_pick": "principal",
                "resultado": "pendiente",
                "partido": "P1",
                "fecha": "2026-01-01",
                "mercado": "M1",
                "seleccion": "S1",
                "cuota": 2.0,
                "confianza": 0.8,
                "ia": "Motor-Propio",
                "analisis_breve": "A",
            },
            {
                "id": 2,
                "tipo_pick": "principal",
                "resultado": "ganada",
                "partido": "P2",
                "fecha": "2026-01-02",
                "mercado": "M2",
                "seleccion": "S2",
                "cuota": 1.9,
                "ganancia": 2.0,
                "ia": "Motor-Propio",
            },
        ]
    )

    monkeypatch.setattr(backend_main, "get_all_picks", lambda incluir_alternativas=True: data)
    monkeypatch.setattr(
        backend_main,
        "calcular_metricas",
        lambda incluir_alternativas=False, fecha_inicio=None, fecha_fin=None: {"roi_global": 12.5, "yield_global": 9.1},
    )

    payload = backend_main._publication_limits_for_user({"role": "user", "subscription_plan": "premium"})
    assert payload == {"pendientes": 10, "cerrados": 8}

    import asyncio

    result = asyncio.run(
        backend_main.get_publication_overview(
            current_user={"role": "user", "subscription_plan": "premium", "active": True, "username": "demo"}
        )
    )

    assert result["can_publish"] is False
    assert result["stats"]["roi_global"] == 12.5
    assert len(result["feed"]["pendientes"]) == 1
    assert len(result["feed"]["cerrados"]) == 1
