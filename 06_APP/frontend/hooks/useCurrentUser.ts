'use client';

import { useQuery } from '@tanstack/react-query';
import api from '@/lib/api';

export type CurrentUser = {
  id?: number;
  username?: string;
  display_name?: string;
  email?: string | null;
  role?: string;
  active?: boolean;
  must_change_password?: boolean;
  subscription_plan?: string;
  subscription_start?: string | null;
  subscription_end?: string | null;
};

type MeResponse = {
  user?: CurrentUser;
};

export function useCurrentUser() {
  return useQuery({
    queryKey: ['auth-me'],
    queryFn: () => api.get('/auth/me').then((response) => (response.data as MeResponse).user ?? null),
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
}
