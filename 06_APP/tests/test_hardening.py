import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_dedupe_picks_frame_removes_duplicate_rows():
    from backend.main import _dedupe_picks_frame

    df = pd.DataFrame(
        [
            {
                "fecha": "2026-01-01",
                "partido": "A vs B",
                "ia": "Motor",
                "mercado": "Ganador",
                "seleccion": "A",
                "tipo_pick": "principal",
            },
            {
                "fecha": "2026-01-01",
                "partido": "A vs B",
                "ia": "Motor",
                "mercado": "Ganador",
                "seleccion": "A",
                "tipo_pick": "principal",
            },
        ]
    )

    deduped = _dedupe_picks_frame(df)

    assert len(deduped) == 1
