import { useQuery } from '@tanstack/react-query';
import api from '@/lib/api';
import type { PickFilters } from './usePicks';

export function useMetrics(filters: PickFilters = {}) {
  return useQuery({
    queryKey: ['metrics', filters],
    queryFn: () =>
      api
        .get('/metrics', { params: filters })
        .then((res) => res.data.metrics),
  });
}
