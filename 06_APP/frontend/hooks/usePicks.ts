import { useQuery } from '@tanstack/react-query';
import api from '@/lib/api';

export type PickFilters = {
  incluir_alternativas?: boolean;
  fecha_inicio?: string;
  fecha_fin?: string;
};

export function usePicks(filters: PickFilters = {}) {
  return useQuery({
    queryKey: ['picks', filters],
    queryFn: () =>
      api
        .get('/picks', { params: filters })
        .then((res) => res.data.picks),
  });
}
