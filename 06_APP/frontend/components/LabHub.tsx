'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '@/lib/api';
import EquityChart from './EquityChart';
import MetricsCard from './MetricsCard';

type SegmentRow = {
  tipo_pick?: string;
  ia?: string;
  mercado?: string;
  competicion?: string;
  picks?: number;
  ganadas?: number;
  perdidas?: number;
  medias?: number;
  stake_total?: number;
  ganancia_total?: number;
  roi?: number;
  win_rate?: number;
};

type LabSummary = {
  total_picks?: number;
  closed_picks?: number;
  pending_picks?: number;
  stake_total?: number;
  ganancia_total?: number;
  roi_global?: number;
  yield_global?: number;
  win_rate?: number;
  ganadas?: number;
  perdidas?: number;
  medias?: number;
};

type LabResponse = {
  summary?: LabSummary;
  by_tipo_pick?: SegmentRow[];
  by_ia?: SegmentRow[];
  by_mercado?: SegmentRow[];
  range?: {
    fecha_min?: string | null;
    fecha_max?: string | null;
  };
};

type BacktestResponse = {
  summary?: Record<string, unknown>;
  serie_diaria?: Array<{
    fecha: string;
    bankroll: number;
    ganancia_neta?: number;
    stake_total?: number;
    picks?: number;
    roi_dia?: number;
  }>;
};

function formatPercent(value: number | undefined) {
  return `${Number(value ?? 0).toFixed(1)}%`;
}

function formatMoney(value: number | undefined) {
  return Number(value ?? 0).toLocaleString('es-CO', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
}

function SegmentList({
  title,
  rows,
  fieldLabel,
}: {
  title: string;
  rows: SegmentRow[];
  fieldLabel: 'tipo_pick' | 'ia' | 'mercado' | 'competicion';
}) {
  return (
    <section className="panel lab-panel">
      <div className="panel-header">
        <div>
          <div className="panel-title">{title}</div>
          <p className="muted">Ranking con lectura histórica del laboratorio.</p>
        </div>
        <div className="panel-badge">{rows.length} filas</div>
      </div>
      <div className="analysis-list">
        {rows.length ? rows.map((row) => (
          <article
            className="analysis-card"
            key={`${fieldLabel}-${String(row[fieldLabel] ?? row.ia ?? row.mercado ?? 'segmento')}`}
          >
            {(() => {
              const label = String(row[fieldLabel] ?? 'Sin dato');
              return (
                <>
                  <div className="analysis-head">
                    <strong>{label}</strong>
                    <span>{formatPercent(row.roi)}</span>
                  </div>
                  <div className="analysis-meta">
                    <span>Picks {Number(row.picks ?? 0)}</span>
                    <span>Win {formatPercent(row.win_rate)}</span>
                    <span>Ganancia {formatMoney(row.ganancia_total)}</span>
                  </div>
                </>
              );
            })()}
          </article>
        )) : (
          <p className="muted">Sin datos suficientes para este corte.</p>
        )}
      </div>
    </section>
  );
}

export default function LabHub() {
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');

  const params = useMemo(
    () => ({
      fecha_inicio: fromDate || undefined,
      fecha_fin: toDate || undefined,
    }),
    [fromDate, toDate],
  );

  const labQuery = useQuery<LabResponse>({
    queryKey: ['lab', params],
    queryFn: () => api.get('/api/lab', { params }).then((response) => response.data),
  });
  const analysisQuery = useQuery<{ segments?: { ia?: SegmentRow[]; mercado?: SegmentRow[]; competicion?: SegmentRow[] }; by_tipo_pick?: SegmentRow[] }>({
    queryKey: ['analysis-segments', params],
    queryFn: () => api.get('/api/analysis/segments', { params }).then((response) => response.data),
  });
  const backtestQuery = useQuery<BacktestResponse>({
    queryKey: ['backtest-lab', params],
    queryFn: () => api.get('/api/backtest', { params }).then((response) => response.data),
  });

  const summary = labQuery.data?.summary ?? {};
  const serie = backtestQuery.data?.serie_diaria ?? [];
  const typeRows = analysisQuery.data?.by_tipo_pick ?? labQuery.data?.by_tipo_pick ?? [];
  const segmentRows = analysisQuery.data?.segments?.ia ?? labQuery.data?.by_ia ?? [];
  const marketRows = analysisQuery.data?.segments?.mercado ?? labQuery.data?.by_mercado ?? [];

  if (labQuery.isLoading || analysisQuery.isLoading || backtestQuery.isLoading) {
    return (
      <div className="dashboard-shell">
        <section className="panel">
          <div className="panel-title">Cargando laboratorio</div>
          <p className="muted">Calculando cortes históricos y evolución temporal...</p>
        </section>
      </div>
    );
  }

  if (labQuery.isError || analysisQuery.isError || backtestQuery.isError) {
    return (
      <div className="dashboard-shell">
        <section className="panel">
          <div className="panel-title">No se pudo cargar el laboratorio</div>
          <p className="muted">El backend no devolvió los datos de análisis para este periodo.</p>
        </section>
      </div>
    );
  }

  return (
    <div className="dashboard-shell lab-shell">
      <section className="panel hero lab-hero">
        <div className="hero-copy">
          <div className="eyebrow">Laboratorio</div>
          <h1>Análisis y aprendizaje del motor</h1>
          <p>
            Espacio aislado para estudiar rendimiento histórico, por tipo de pick y por segmento, sin tocar
            la operación diaria.
          </p>
          <div className="hero-actions">
            <Link className="ghost-button primary" href="/dashboard">
              Volver al dashboard
            </Link>
            <button
              type="button"
              className="ghost-button"
              onClick={() => {
                setFromDate('');
                setToDate('');
              }}
            >
              Limpiar filtros
            </button>
          </div>
        </div>
        <div className="hero-filters lab-filters">
          <label>
            <span>Desde</span>
            <input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} />
          </label>
          <label>
            <span>Hasta</span>
            <input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} />
          </label>
          <div className="summary-card">
            <span>Rango</span>
            <strong>
              {labQuery.data?.range?.fecha_min ?? 'Sin dato'} - {labQuery.data?.range?.fecha_max ?? 'Sin dato'}
            </strong>
          </div>
        </div>
      </section>

      <section className="metrics-grid">
        <MetricsCard label="Total picks" value={String(Number(summary.total_picks ?? 0))} tone="emerald" />
        <MetricsCard label="Cerrados" value={String(Number(summary.closed_picks ?? 0))} tone="amber" />
        <MetricsCard label="Pendientes" value={String(Number(summary.pending_picks ?? 0))} tone="slate" />
        <MetricsCard label="ROI global" value={formatPercent(summary.roi_global)} tone="rose" />
      </section>

      <section className="metrics-grid">
        <MetricsCard label="Acierto" value={formatPercent(summary.win_rate)} tone="emerald" />
        <MetricsCard label="Stake total" value={formatMoney(summary.stake_total)} tone="amber" />
        <MetricsCard label="Ganancia neta" value={formatMoney(summary.ganancia_total)} tone="slate" />
        <MetricsCard label="Yield" value={formatPercent(summary.yield_global)} tone="rose" />
      </section>

      <section className="lab-grid">
        <div className="panel lab-panel">
          <div className="panel-header">
            <div>
              <div className="panel-title">Evolución temporal</div>
              <p className="muted">Curva de capital sobre datos históricos cerrados.</p>
            </div>
            <div className="panel-badge">{serie.length} puntos</div>
          </div>
          <EquityChart points={serie} />
        </div>
        <SegmentList title="Rendimiento por tipo de pick" rows={typeRows} fieldLabel="tipo_pick" />
      </section>

      <section className="lab-grid">
        <SegmentList title="ROI por IA" rows={segmentRows} fieldLabel="ia" />
        <SegmentList title="ROI por mercado" rows={marketRows} fieldLabel="mercado" />
      </section>
    </div>
  );
}
