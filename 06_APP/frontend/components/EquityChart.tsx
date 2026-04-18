'use client';

type Point = {
  fecha: string;
  bankroll: number;
};

type EquityChartProps = {
  points: Point[];
  title?: string;
};

export default function EquityChart({ points, title = 'Evolucion del bankroll' }: EquityChartProps) {
  if (!points.length) {
    return (
      <div className="panel chart-panel">
        <div className="panel-title">{title}</div>
        <p className="muted">No hay cierres suficientes para dibujar la curva.</p>
      </div>
    );
  }

  const width = 1000;
  const height = 320;
  const padding = 36;
  const values = points.map((point) => point.bankroll);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = points.length === 1 ? 0 : (width - padding * 2) / (points.length - 1);

  const coords = points.map((point, index) => {
    const x = padding + step * index;
    const y = padding + ((max - point.bankroll) / range) * (height - padding * 2);
    return { ...point, x, y };
  });

  const path = coords
    .map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`)
    .join(' ');

  return (
    <div className="panel chart-panel">
      <div className="panel-header">
        <div>
          <div className="panel-title">{title}</div>
          <p className="muted">Curva de capital filtrada por el periodo seleccionado.</p>
        </div>
        <div className="chart-range">
          <span>{points[0].fecha}</span>
          <span>{points[points.length - 1].fecha}</span>
        </div>
      </div>
      <div className="chart-wrap">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
          <defs>
            <linearGradient id="equityFill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="rgb(104, 219, 145)" stopOpacity="0.42" />
              <stop offset="100%" stopColor="rgb(104, 219, 145)" stopOpacity="0.02" />
            </linearGradient>
          </defs>
          <path
            d={`${path} L ${coords[coords.length - 1]?.x ?? 0} ${height - padding} L ${coords[0].x} ${height - padding} Z`}
            fill="url(#equityFill)"
          />
          <path d={path} fill="none" stroke="#68db91" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
          {coords.map((point) => (
            <circle key={`${point.fecha}-${point.x}`} cx={point.x} cy={point.y} r="4.5" fill="#e8fff0" stroke="#68db91" strokeWidth="3" />
          ))}
        </svg>
      </div>
      <div className="chart-foot">
        <span>Mín {Math.round(min).toLocaleString('es-CO')}</span>
        <span>Máx {Math.round(max).toLocaleString('es-CO')}</span>
      </div>
    </div>
  );
}
