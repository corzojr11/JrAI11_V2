'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { useMetrics } from '@/hooks/useMetrics';
import { usePicks, type PickFilters } from '@/hooks/usePicks';
import EquityChart from './EquityChart';
import MetricsCard from './MetricsCard';
import PickTable, { type PickRow } from './PickTable';

type RiskMetrics = {
  sharpe_ratio?: number;
  max_drawdown?: number;
  profit_factor?: number;
  ev_promedio?: number;
  yield_porcentaje?: number;
  tasa_acierto?: number;
  racha_max_ganadora?: number;
  racha_max_perdedora?: number;
  p_value?: number;
  significativo_95?: boolean;
};

type MetricsResponse = {
  bankroll_inicial?: number;
  bankroll_actual?: number;
  total_picks?: number;
  ganadas?: number;
  perdidas?: number;
  medias?: number;
  roi_global?: number;
  yield_global?: number;
  fecha_min?: string | null;
  fecha_max?: string | null;
  serie_diaria?: Array<{
    fecha: string;
    bankroll: number;
    ganancia_neta?: number;
    stake_total?: number;
    picks?: number;
    roi_dia?: number;
  }>;
  metricas_riesgo?: RiskMetrics;
};

function formatPercent(value: number) {
  return `${value.toFixed(1)}%`;
}

function formatMoney(value: number) {
  return value.toLocaleString('es-CO', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
}

function getRange(picks: PickRow[], metrics: MetricsResponse) {
  const pickDates = picks
    .map((pick) => pick.fecha?.slice(0, 10) ?? '')
    .filter(Boolean)
    .sort();
  const min = metrics.fecha_min ?? pickDates[0] ?? '';
  const max = metrics.fecha_max ?? pickDates[pickDates.length - 1] ?? '';
  return { min, max };
}

function isInRange(date: string | undefined, fromDate: string, toDate: string) {
  if (!date) return false;
  const value = date.slice(0, 10);
  if (fromDate && value < fromDate) return false;
  if (toDate && value > toDate) return false;
  return true;
}

export default function Dashboard() {
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');

  const filters: PickFilters = useMemo(
    () => ({
      fecha_inicio: fromDate || undefined,
      fecha_fin: toDate || undefined,
    }),
    [fromDate, toDate],
  );

  const picksQuery = usePicks(filters);
  const metricsQuery = useMetrics(filters);

  const picks = useMemo(
    () => (Array.isArray(picksQuery.data) ? (picksQuery.data as PickRow[]) : []),
    [picksQuery.data],
  );
  const metrics = useMemo(
    () => (metricsQuery.data && typeof metricsQuery.data === 'object' ? (metricsQuery.data as MetricsResponse) : {}),
    [metricsQuery.data],
  );

  const range = useMemo(() => getRange(picks, metrics), [picks, metrics]);
  const selectedFrom = fromDate || range.min || '';
  const selectedTo = toDate || range.max || '';

  const filteredPicks = useMemo(
    () => picks.filter((pick) => isInRange(pick.fecha, selectedFrom, selectedTo)),
    [picks, selectedFrom, selectedTo],
  );

  const closedPicks = useMemo(
    () => filteredPicks.filter((pick) => pick.resultado && pick.resultado !== 'pendiente'),
    [filteredPicks],
  );

  const pendingPicks = useMemo(
    () => filteredPicks.filter((pick) => !pick.resultado || pick.resultado === 'pendiente'),
    [filteredPicks],
  );

  const closedStake = useMemo(
    () => closedPicks.reduce((sum, pick) => sum + Number(pick.stake ?? 0), 0),
    [closedPicks],
  );

  const closedGain = useMemo(
    () => closedPicks.reduce((sum, pick) => sum + Number(pick.ganancia ?? 0), 0),
    [closedPicks],
  );

  const winRate = useMemo(() => {
    const wins = closedPicks.filter((pick) => pick.resultado === 'ganada').length;
    const losses = closedPicks.filter((pick) => pick.resultado === 'perdida').length;
    const total = wins + losses;
    return total > 0 ? (wins / total) * 100 : 0;
  }, [closedPicks]);

  const roi = closedStake > 0 ? (closedGain / closedStake) * 100 : 0;
  const bankrollActual = metrics.bankroll_actual ?? metrics.bankroll_inicial ?? 0;

  const chartPoints = useMemo(() => {
    const bankrollInicial = metrics.bankroll_inicial ?? 0;
    const sortedClosed = [...closedPicks].sort((left, right) => {
      const leftDate = left.fecha ? new Date(left.fecha).getTime() : 0;
      const rightDate = right.fecha ? new Date(right.fecha).getTime() : 0;
      return leftDate - rightDate;
    });

    return sortedClosed.reduce<Array<{ fecha: string; bankroll: number }>>((series, pick) => {
      const previous = series[series.length - 1]?.bankroll ?? bankrollInicial;
      series.push({
        fecha: pick.fecha?.slice(0, 10) ?? '',
        bankroll: previous + Number(pick.ganancia ?? 0),
      });
      return series;
    }, []);
  }, [closedPicks, metrics.bankroll_inicial]);

  const riesgo = metrics.metricas_riesgo ?? {};

  if (picksQuery.isLoading || metricsQuery.isLoading) {
    return (
      <div className="dashboard-shell">
        <div className="dashboard-loading">Cargando dashboard...</div>
      </div>
    );
  }

  if (picksQuery.error || metricsQuery.error) {
    return (
      <div className="dashboard-shell">
        <div className="panel">
          <div className="panel-title">No se pudo cargar el dashboard</div>
          <p className="muted">El backend no devolvio los datos necesarios para este periodo.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard-shell">
      <section className="hero panel">
        <div className="hero-copy">
          <div className="eyebrow">Streamlit rescue</div>
          <h1>Dashboard operativo de picks</h1>
          <p>
            Vista filtrable del sistema con la misma lectura ejecutiva que ya existia:
            rendimiento, curva de capital, riesgo y tabla operativa.
          </p>
          <div className="hero-actions">
            <Link className="ghost-button primary" href="/publicacion">
              Publicación
            </Link>
            <Link className="ghost-button" href="/operacion">
              Operación
            </Link>
            <Link className="ghost-button" href="/lab">
              Laboratorio
            </Link>
          </div>
        </div>
        <div className="hero-filters">
          <label>
            <span>Desde</span>
            <input
              type="date"
              value={selectedFrom}
              min={range.min || undefined}
              max={range.max || undefined}
              onChange={(event) => setFromDate(event.target.value)}
            />
          </label>
          <label>
            <span>Hasta</span>
            <input
              type="date"
              value={selectedTo}
              min={range.min || undefined}
              max={range.max || undefined}
              onChange={(event) => setToDate(event.target.value)}
            />
          </label>
          <button
            type="button"
            className="ghost-button"
            onClick={() => {
              setFromDate(range.min);
              setToDate(range.max);
            }}
          >
            Restablecer
          </button>
        </div>
      </section>

      <section className="metrics-grid">
        <MetricsCard
          label="Bankroll actual"
          value={formatMoney(Number(bankrollActual))}
          helper={`${filteredPicks.length} picks en el periodo`}
          tone="emerald"
        />
        <MetricsCard
          label="ROI"
          value={formatPercent(roi)}
          helper={`${closedPicks.length} cerrados`}
          tone="amber"
        />
        <MetricsCard
          label="Acierto"
          value={formatPercent(winRate)}
          helper={`${pendingPicks.length} pendientes`}
          tone="slate"
        />
        <MetricsCard
          label="Yield global"
          value={formatPercent(Number(metrics.yield_global ?? 0))}
          helper={`Total picks: ${Number(metrics.total_picks ?? 0)}`}
          tone="rose"
        />
      </section>

      <section className="risk-grid">
        <MetricsCard label="Sharpe" value={(Number(riesgo.sharpe_ratio ?? 0)).toFixed(2)} tone="slate" />
        <MetricsCard label="Drawdown" value={formatPercent(Number(riesgo.max_drawdown ?? 0))} tone="rose" />
        <MetricsCard label="Profit factor" value={(Number(riesgo.profit_factor ?? 0)).toFixed(2)} tone="emerald" />
        <MetricsCard label="p-valor" value={(Number(riesgo.p_value ?? 0)).toFixed(4)} tone="amber" />
      </section>

      <EquityChart points={chartPoints} />

      <PickTable picks={filteredPicks} />
    </div>
  );
}
