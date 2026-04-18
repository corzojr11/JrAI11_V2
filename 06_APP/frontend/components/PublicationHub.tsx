'use client';

import { useQuery } from '@tanstack/react-query';
import api from '@/lib/api';
import type { CurrentUser } from '@/hooks/useCurrentUser';
import { useCurrentUser } from '@/hooks/useCurrentUser';

type PublicationCopy = {
  copy_corto?: string;
  copy_social?: string;
  copy_largo?: string;
};

type PublicationItem = {
  id?: number;
  partido?: string;
  fecha?: string;
  mercado?: string;
  seleccion?: string;
  cuota?: number;
  confianza?: number;
  ganancia?: number;
  resultado?: string;
  ia?: string;
  analisis_breve?: string;
  copy?: PublicationCopy;
};

type PublicationOverview = {
  user?: CurrentUser;
  can_publish?: boolean;
  limits?: {
    pendientes?: number | null;
    cerrados?: number | null;
  };
  stats?: {
    total_picks?: number;
    pendientes_principales?: number;
    cerrados_principales?: number;
    roi_global?: number;
    yield_global?: number;
  };
  feed?: {
    pendientes?: PublicationItem[];
    cerrados?: PublicationItem[];
  };
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

async function downloadPdf(path: string, filename: string) {
  const response = await api.get(path, { responseType: 'blob' });
  const url = window.URL.createObjectURL(response.data);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

function PublicationCard({
  item,
  kind,
  canPublish,
}: {
  item: PublicationItem;
  kind: 'pick' | 'result';
  canPublish: boolean;
}) {
  const title = item.partido ?? 'Sin partido';
  const subtitle =
    kind === 'pick'
      ? `${item.mercado ?? '-'} | ${item.seleccion ?? '-'} | Cuota ${Number(item.cuota ?? 0).toFixed(2)}`
      : `${item.mercado ?? '-'} | ${item.seleccion ?? '-'} | Resultado ${item.resultado ?? '-'}`;

  const copy = item.copy ?? {};
  const downloadPath = kind === 'pick'
    ? `/api/publication/export/pick/${item.id ?? 0}`
    : `/api/publication/export/result/${item.id ?? 0}`;

  const telegramPath = kind === 'pick'
    ? `/api/publication/telegram/pick/${item.id ?? 0}`
    : `/api/publication/telegram/result/${item.id ?? 0}`;

  return (
    <article className="publication-card">
      <div className="panel-header">
        <div>
          <div className="panel-title">{title}</div>
          <p className="muted">{subtitle}</p>
        </div>
        <div className="panel-badge">
          {kind === 'pick'
            ? `${Number(item.confianza ?? 0).toFixed(0)}%`
            : `${formatMoney(item.ganancia)} COP`}
        </div>
      </div>

      <div className="publication-copy">
        <textarea readOnly rows={kind === 'pick' ? 5 : 4} value={copy.copy_social ?? ''} />
      </div>

      <div className="publication-meta">
        <span>{item.fecha?.slice(0, 10) ?? '-'}</span>
        <span>{item.ia ?? 'Jr AI 11'}</span>
      </div>

      {canPublish ? (
        <div className="publication-actions">
          <button
            type="button"
            className="ghost-button"
            onClick={() => void navigator.clipboard.writeText(copy.copy_social ?? '')}
          >
            Copiar texto
          </button>
          <button
            type="button"
            className="ghost-button"
            onClick={() => void downloadPdf(`${downloadPath}/pdf-social`, `${kind === 'pick' ? 'pick' : 'resultado'}_social_${item.id ?? 'export'}.pdf`)}
          >
            Descargar PDF
          </button>
          <button
            type="button"
            className="ghost-button primary"
            onClick={() => {
              void api.post(telegramPath);
            }}
          >
            Enviar a Telegram
          </button>
        </div>
      ) : (
        <div className="publication-actions">
          <span className="panel-badge">Solo lectura</span>
        </div>
      )}
    </article>
  );
}

export default function PublicationHub() {
  const currentUserQuery = useCurrentUser();
  const overviewQuery = useQuery<PublicationOverview>({
    queryKey: ['publication-overview'],
    queryFn: () => api.get('/api/publication/overview').then((response) => response.data),
  });

  const currentUser = currentUserQuery.data;
  const overview = overviewQuery.data;
  const canPublish = Boolean(overview?.can_publish);
  const role = String(currentUser?.role ?? overview?.user?.role ?? '').toLowerCase();
  const plan = String(currentUser?.subscription_plan ?? overview?.user?.subscription_plan ?? 'free').toLowerCase();
  const pending = overview?.feed?.pendientes ?? [];
  const closed = overview?.feed?.cerrados ?? [];

  if (currentUserQuery.isLoading || overviewQuery.isLoading) {
    return (
      <div className="dashboard-shell">
        <section className="panel">
          <div className="panel-title">Cargando publicación</div>
          <p className="muted">Recuperando feed, resumen y permisos...</p>
        </section>
      </div>
    );
  }

  if (currentUserQuery.isError || overviewQuery.isError) {
    return (
      <div className="dashboard-shell">
        <section className="panel">
          <div className="panel-title">No se pudo cargar la publicación</div>
          <p className="muted">El backend no devolvió la vista de publicación para este usuario.</p>
        </section>
      </div>
    );
  }

  return (
    <div className="dashboard-shell publication-shell">
      <section className="panel hero publication-hero">
        <div className="hero-copy">
          <div className="eyebrow">Publicación</div>
          <h1>Feed compartible y exportación</h1>
          <p>
            La misma capa de publicación de Streamlit, ahora separada por permisos: {role || 'usuario'} / {plan || 'free'}.
          </p>
          <div className="hero-actions">
            <button
              type="button"
              className="ghost-button primary"
              onClick={() => {
                void downloadPdf('/api/publication/export/boletin.pdf', 'boletin_picks.pdf');
              }}
              disabled={!canPublish}
            >
              Descargar boletín
            </button>
            <button
              type="button"
              className="ghost-button"
              onClick={() => {
                if (!canPublish) return;
                void api.post('/api/publication/telegram/boletin');
              }}
              disabled={!canPublish}
            >
              Enviar boletín a Telegram
            </button>
          </div>
        </div>
        <div className="hero-filters">
          <div className="summary-card">
            <span>Total picks</span>
            <strong>{Number(overview?.stats?.total_picks ?? 0)}</strong>
          </div>
          <div className="summary-card">
            <span>Pendientes</span>
            <strong>{Number(overview?.stats?.pendientes_principales ?? 0)}</strong>
          </div>
          <div className="summary-card">
            <span>Cerrados</span>
            <strong>{Number(overview?.stats?.cerrados_principales ?? 0)}</strong>
          </div>
          <div className="summary-card">
            <span>ROI global</span>
            <strong>{formatPercent(overview?.stats?.roi_global)}</strong>
          </div>
        </div>
      </section>

      <section className="publication-grid">
        <div className="panel publication-column">
          <div className="panel-header">
            <div>
              <div className="panel-title">Picks pendientes</div>
              <p className="muted">Vista pública de picks activos con el mismo recorte de Streamlit.</p>
            </div>
            <div className="panel-badge">{pending.length} visibles</div>
          </div>
          <div className="publication-list">
            {pending.map((item) => (
              <PublicationCard key={item.id ?? `${item.partido}-${item.fecha}`} item={item} kind="pick" canPublish={canPublish} />
            ))}
          </div>
        </div>

        <div className="panel publication-column">
          <div className="panel-header">
            <div>
              <div className="panel-title">Resultados recientes</div>
              <p className="muted">Cierres publicados con el resumen que antes vivía dentro de la app original.</p>
            </div>
            <div className="panel-badge">{closed.length} visibles</div>
          </div>
          <div className="publication-list">
            {closed.map((item) => (
              <PublicationCard key={item.id ?? `${item.partido}-${item.fecha}`} item={item} kind="result" canPublish={canPublish} />
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
