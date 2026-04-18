'use client';

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '@/lib/api';

type FixtureRow = {
  fixture_id?: number;
  fecha?: string;
  fecha_corta?: string;
  hora?: string;
  liga?: string;
  liga_id?: number;
  local?: string;
  visitante?: string;
};

type PreparedData = {
  fixture_id?: number;
  partido?: string;
  fecha?: string;
  hora?: string;
  liga_nombre?: string;
  pais?: string;
  estadio?: string;
  ciudad?: string;
  arbitro?: string;
  home?: Record<string, unknown>;
  away?: Record<string, unknown>;
  h2h?: unknown[];
  lineups?: unknown[];
  odds?: Record<string, unknown>;
  debug_api?: Record<string, unknown>;
};

type ManualForm = {
  arbitro_manual: string;
  forma_local_manual: string;
  forma_visitante_manual: string;
  h2h_manual: string;
  lesiones_local_manual: string;
  lesiones_visitante_manual: string;
  alineacion_local_manual: string;
  alineacion_visitante_manual: string;
  cuotas_manual_resumen: string;
  xg_local: string;
  xg_visitante: string;
  elo_local: string;
  elo_visitante: string;
  motivacion_local: string;
  motivacion_visitante: string;
  contexto_extra: string;
};

type HistoryRow = {
  id?: number;
  partido?: string;
  fecha?: string;
  liga?: string;
  cobertura?: number;
  ficha_texto?: string;
  created_at?: string;
};

const emptyManual: ManualForm = {
  arbitro_manual: '',
  forma_local_manual: '',
  forma_visitante_manual: '',
  h2h_manual: '',
  lesiones_local_manual: '',
  lesiones_visitante_manual: '',
  alineacion_local_manual: '',
  alineacion_visitante_manual: '',
  cuotas_manual_resumen: '',
  xg_local: '',
  xg_visitante: '',
  elo_local: '',
  elo_visitante: '',
  motivacion_local: '',
  motivacion_visitante: '',
  contexto_extra: '',
};

function formatFixtureTitle(item: FixtureRow) {
  return `${item.local ?? 'Local'} vs ${item.visitante ?? 'Visitante'}`;
}

function getReadyScore(manual: ManualForm) {
  const fields: (keyof ManualForm)[] = [
    'xg_local',
    'xg_visitante',
    'elo_local',
    'elo_visitante',
    'arbitro_manual',
    'forma_local_manual',
    'forma_visitante_manual',
    'h2h_manual',
    'lesiones_local_manual',
    'lesiones_visitante_manual',
    'alineacion_local_manual',
    'alineacion_visitante_manual',
    'cuotas_manual_resumen',
    'motivacion_local',
    'motivacion_visitante',
    'contexto_extra',
  ];
  return fields.filter((field) => manual[field].trim()).length;
}

export default function OperationFlow() {
  const queryClient = useQueryClient();
  const [selectedDate, setSelectedDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [fixtures, setFixtures] = useState<FixtureRow[]>([]);
  const [selectedFixture, setSelectedFixture] = useState<FixtureRow | null>(null);
  const [manual, setManual] = useState<ManualForm>(emptyManual);
  const [preparedData, setPreparedData] = useState<PreparedData | null>(null);
  const [fichaTexto, setFichaTexto] = useState('');
  const [manualSearch, setManualSearch] = useState('');
  const [searchDate, setSearchDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [statusMessage, setStatusMessage] = useState('Listo para cargar un fixture.');

  const apiStatusQuery = useQuery({
    queryKey: ['api-status'],
    queryFn: () => api.get('/api/api-status').then((res) => res.data),
  });

  const historyQuery = useQuery({
    queryKey: ['prepared-history'],
    queryFn: () => api.get('/api/preparation/history', { params: { limit: 12 } }).then((res) => res.data.items ?? []),
  });

  const loadFixtures = useMutation({
    mutationFn: (mode: 'day' | 'proximos') => {
      if (mode === 'proximos') {
        return api.get('/api/preparation/proximos', { params: { dias: 3 } }).then((res) => res.data.partidos ?? []);
      }
      return api.get('/api/partidos_por_fecha', { params: { fecha: selectedDate } }).then((res) => res.data.partidos ?? []);
    },
    onSuccess: (rows) => {
      setFixtures(rows as FixtureRow[]);
      setSelectedFixture(null);
      setPreparedData(null);
      setFichaTexto('');
      setStatusMessage('Fixtures cargados. Selecciona uno para preparar.');
    },
    onError: () => {
      setStatusMessage('No se pudieron cargar los fixtures.');
    },
  });

  const prepareMatch = useMutation({
    mutationFn: (payload: { partido_texto: string; fecha_iso: string; liga_key?: string | null }) =>
      api.post('/api/preparation/prepare', payload).then((res) => res.data.data as PreparedData),
    onSuccess: (data) => {
      setPreparedData(data);
      setFichaTexto('');
      setStatusMessage('Partido preparado. Completa los campos manuales y genera la ficha.');
    },
    onError: () => {
      setStatusMessage('No se pudo preparar el partido.');
    },
  });

  const generateFicha = useMutation({
    mutationFn: (payload: { data: PreparedData; manual: ManualForm }) =>
      api.post('/api/preparation/generate', payload).then((res) => res.data as { ficha_texto: string; cobertura_pct: number }),
    onSuccess: (data) => {
      setFichaTexto(data.ficha_texto);
      setStatusMessage(`Ficha generada. Cobertura manual: ${data.cobertura_pct}%`);
      queryClient.invalidateQueries({ queryKey: ['prepared-history'] });
    },
    onError: () => {
      setStatusMessage('No se pudo generar la ficha.');
    },
  });

  const manualReady = useMemo(() => getReadyScore(manual), [manual]);
  const coverage = useMemo(() => {
    const total = 16;
    return Math.round((manualReady / total) * 100);
  }, [manualReady]);

  const currentStep = preparedData ? 2 : 1;
  const finalStep = fichaTexto ? 3 : currentStep;

  const history = (historyQuery.data ?? []) as HistoryRow[];

  return (
    <div className="dashboard-shell operation-shell">
      <section className="panel operation-hero">
        <div>
          <div className="eyebrow">Operación</div>
          <h1>Preparación de partido</h1>
          <p className="muted">
            Flujo recuperado de Streamlit: buscar fixture, completar datos manuales y generar la ficha operativa.
          </p>
        </div>
        <div className="operation-status">
          <div className="status-card">
            <span>API</span>
            <strong>{apiStatusQuery.data?.config?.api_football_key_configured ? 'Activa' : 'Sin key'}</strong>
          </div>
          <div className="status-card">
            <span>Estado</span>
            <strong>{statusMessage}</strong>
          </div>
        </div>
      </section>

      <section className="stepper">
        <div className={`step-pill ${currentStep === 1 ? 'active' : ''}`}>1. Buscar fixture</div>
        <div className={`step-pill ${currentStep === 2 ? 'active' : ''}`}>2. Completar manual</div>
        <div className={`step-pill ${finalStep === 3 ? 'active' : ''}`}>3. Generar ficha</div>
      </section>

      <section className="panel operation-panel">
        <div className="panel-header">
          <div>
            <div className="panel-title">Paso 1. Buscar fixture</div>
            <p className="muted">Carga por fecha local o usa la búsqueda manual alternativa del flujo original.</p>
          </div>
          <button type="button" className="ghost-button" onClick={() => void loadFixtures.mutateAsync('day')}>
            Cargar partidos
          </button>
        </div>

        <div className="operation-filters">
          <label>
            <span>Fecha local</span>
            <input type="date" value={selectedDate} onChange={(event) => setSelectedDate(event.target.value)} />
          </label>
          <button type="button" className="ghost-button" onClick={() => void loadFixtures.mutateAsync('proximos')}>
            Próximos 3 días
          </button>
        </div>

        <div className="fixture-grid">
          {fixtures.map((fixture) => (
            <button
              key={`${fixture.fixture_id ?? fixture.fecha ?? ''}-${fixture.local ?? ''}`}
              type="button"
              className={`fixture-card ${selectedFixture?.fixture_id === fixture.fixture_id ? 'selected' : ''}`}
              onClick={() => {
                setSelectedFixture(fixture);
                setSearchDate(fixture.fecha_corta ?? selectedDate);
                void prepareMatch.mutateAsync({
                  partido_texto: formatFixtureTitle(fixture),
                  fecha_iso: fixture.fecha_corta ?? selectedDate,
                });
              }}
            >
              <span>{fixture.liga ?? 'Sin liga'}</span>
              <strong>{formatFixtureTitle(fixture)}</strong>
              <small>{fixture.hora ?? '--:--'}</small>
            </button>
          ))}
        </div>

        <div className="manual-search">
          <div className="panel-title">Buscar manualmente</div>
          <div className="operation-form">
            <label>
              <span>Partido</span>
              <input
                type="text"
                value={manualSearch}
                onChange={(event) => setManualSearch(event.target.value)}
                placeholder="Ej: Atletico Nacional vs Llaneros"
              />
            </label>
            <label>
              <span>Fecha</span>
              <input type="date" value={searchDate} onChange={(event) => setSearchDate(event.target.value)} />
            </label>
            <button
              type="button"
              className="ghost-button"
              onClick={() =>
                void prepareMatch.mutateAsync({
                  partido_texto: manualSearch,
                  fecha_iso: searchDate,
                })
              }
            >
              Preparar
            </button>
          </div>
        </div>
      </section>

      {preparedData ? (
        <section className="panel operation-panel">
          <div className="panel-header">
            <div>
              <div className="panel-title">Paso 2. Completar manual</div>
              <p className="muted">Los datos de API ya están cargados. Completa los campos que Streamlit dejaba a mano.</p>
            </div>
            <div className="panel-badge">Cobertura estimada: {coverage}%</div>
          </div>

          <div className="summary-grid">
            <div className="summary-card">
              <span>Partido</span>
              <strong>{preparedData.partido ?? '-'}</strong>
            </div>
            <div className="summary-card">
              <span>Liga</span>
              <strong>{preparedData.liga_nombre ?? '-'}</strong>
            </div>
            <div className="summary-card">
              <span>Fecha</span>
              <strong>{preparedData.fecha ?? '-'}</strong>
            </div>
            <div className="summary-card">
              <span>Arbitro</span>
              <strong>{preparedData.arbitro ?? 'Sin dato'}</strong>
            </div>
          </div>

          <div className="operation-form operation-form-grid">
            {(
              [
                ['xg_local', 'xG local'],
                ['xg_visitante', 'xG visitante'],
                ['elo_local', 'ELO local'],
                ['elo_visitante', 'ELO visitante'],
              ] as const
            ).map(([key, label]) => (
              <label key={key}>
                <span>{label}</span>
                <input
                  type="text"
                  value={manual[key]}
                  onChange={(event) => setManual((current) => ({ ...current, [key]: event.target.value }))}
                  placeholder={label}
                />
              </label>
            ))}
            <label>
              <span>Arbitro</span>
              <input
                type="text"
                value={manual.arbitro_manual}
                onChange={(event) => setManual((current) => ({ ...current, arbitro_manual: event.target.value }))}
                placeholder="Ej: Andres Rojas"
              />
            </label>
            <label>
              <span>Cuotas / mercado</span>
              <input
                type="text"
                value={manual.cuotas_manual_resumen}
                onChange={(event) => setManual((current) => ({ ...current, cuotas_manual_resumen: event.target.value }))}
                placeholder="Resumen de cuotas"
              />
            </label>
          </div>

          <div className="operation-form operation-form-stack">
            {(
              [
                ['forma_local_manual', 'Forma reciente local'],
                ['forma_visitante_manual', 'Forma reciente visitante'],
                ['h2h_manual', 'H2H ultimos enfrentamientos'],
                ['lesiones_local_manual', 'Lesiones / suspensiones local'],
                ['lesiones_visitante_manual', 'Lesiones / suspensiones visitante'],
                ['alineacion_local_manual', 'Alineacion probable local'],
                ['alineacion_visitante_manual', 'Alineacion probable visitante'],
                ['motivacion_local', 'Motivacion / contexto local'],
                ['motivacion_visitante', 'Motivacion / contexto visitante'],
                ['contexto_extra', 'Contexto adicional'],
              ] as const
            ).map(([key, label]) => (
              <label key={key}>
                <span>{label}</span>
                <textarea
                  value={manual[key]}
                  onChange={(event) => setManual((current) => ({ ...current, [key]: event.target.value }))}
                  rows={4}
                  placeholder={label}
                />
              </label>
            ))}
          </div>

          <div className="operation-actions">
            <button
              type="button"
              className="ghost-button"
              onClick={() => setManual(emptyManual)}
            >
              Limpiar manual
            </button>
            <button
              type="button"
              className="ghost-button primary"
              onClick={() => {
                if (!preparedData) return;
                void generateFicha.mutateAsync({ data: preparedData, manual });
              }}
            >
              Generar ficha estructurada
            </button>
          </div>

          <div className="progress-block">
            <div className="progress-head">
              <span>Campos manuales completos</span>
              <strong>{manualReady}/16</strong>
            </div>
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: `${coverage}%` }} />
            </div>
          </div>
        </section>
      ) : null}

      {fichaTexto ? (
        <section className="panel operation-panel">
          <div className="panel-header">
            <div>
              <div className="panel-title">Paso 3. Ficha generada</div>
              <p className="muted">La ficha ya quedó persistida en backend y lista para el flujo de análisis interno.</p>
            </div>
            <div className="panel-badge">Guardada en base</div>
          </div>
          <textarea className="ficha-preview" readOnly value={fichaTexto} rows={20} />
        </section>
      ) : null}

      <section className="panel operation-panel">
        <div className="panel-header">
          <div>
            <div className="panel-title">Historial de fichas</div>
            <p className="muted">Últimas fichas preparadas, igual que en el flujo original.</p>
          </div>
          <div className="panel-badge">{history.length} registros</div>
        </div>
        <div className="history-list">
          {history.map((item) => (
            <details key={item.id ?? `${item.partido}-${item.fecha}`}>
              <summary>
                <span>{item.partido ?? 'Sin partido'}</span>
                <small>{item.liga ?? 'Sin liga'} | {Number(item.cobertura ?? 0).toFixed(0)}%</small>
              </summary>
              <textarea readOnly rows={10} value={item.ficha_texto ?? ''} />
            </details>
          ))}
        </div>
      </section>
    </div>
  );
}
