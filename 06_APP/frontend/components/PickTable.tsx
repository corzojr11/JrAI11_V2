'use client';

export type PickRow = {
  id?: number;
  fecha?: string;
  partido?: string;
  mercado?: string;
  seleccion?: string;
  cuota?: number;
  confianza?: number;
  resultado?: string;
  ganancia?: number;
  stake?: number;
  ia?: string;
  tipo_pick?: string;
};

type PickTableProps = {
  picks: PickRow[];
};

const statusLabel: Record<string, string> = {
  ganada: 'Ganada',
  perdida: 'Perdida',
  media: 'Media',
  pendiente: 'Pendiente',
};

export default function PickTable({ picks }: PickTableProps) {
  if (!picks.length) {
    return (
      <div className="panel">
        <div className="panel-title">Picks filtrados</div>
        <p className="muted">No hay picks en el rango seleccionado.</p>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div>
          <div className="panel-title">Picks filtrados</div>
          <p className="muted">Vista operativa del periodo activo.</p>
        </div>
        <div className="panel-badge">{picks.length} filas</div>
      </div>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Partido</th>
              <th>Mercado</th>
              <th>Selección</th>
              <th>Cuota</th>
              <th>Estado</th>
              <th>Ganancia</th>
            </tr>
          </thead>
          <tbody>
            {picks.map((pick) => {
              const status = (pick.resultado ?? 'pendiente').toLowerCase();
              return (
                <tr key={`${pick.id ?? pick.fecha ?? 'pick'}-${pick.partido ?? ''}`}>
                  <td>{pick.fecha?.slice(0, 10) ?? '-'}</td>
                  <td>{pick.partido ?? '-'}</td>
                  <td>{pick.mercado ?? '-'}</td>
                  <td>{pick.seleccion ?? '-'}</td>
                  <td>{typeof pick.cuota === 'number' ? pick.cuota.toFixed(2) : '-'}</td>
                  <td>
                    <span className={`status-pill status-${status}`}>
                      {statusLabel[status] ?? pick.resultado ?? '-'}
                    </span>
                  </td>
                  <td>{typeof pick.ganancia === 'number' ? pick.ganancia.toFixed(2) : '-'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
