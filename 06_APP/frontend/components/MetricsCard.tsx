'use client';

type MetricsCardProps = {
  label: string;
  value: string | number;
  helper?: string;
  tone?: 'emerald' | 'amber' | 'slate' | 'rose';
};

const toneClass: Record<NonNullable<MetricsCardProps['tone']>, string> = {
  emerald: 'metric-card metric-card-emerald',
  amber: 'metric-card metric-card-amber',
  slate: 'metric-card metric-card-slate',
  rose: 'metric-card metric-card-rose',
};

export default function MetricsCard({ label, value, helper, tone = 'slate' }: MetricsCardProps) {
  return (
    <div className={toneClass[tone]}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {helper ? <div className="metric-helper">{helper}</div> : null}
    </div>
  );
}
