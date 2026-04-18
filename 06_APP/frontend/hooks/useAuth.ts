'use client';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { AxiosError } from 'axios';
import { useRouter } from 'next/navigation';
import api from '@/lib/api';

type LoginResponse = {
  message: string;
};

type LoginError = AxiosError<{ detail?: string }>;

export function useAuth() {
  const router = useRouter();
  const queryClient = useQueryClient();

  const login = useMutation<LoginResponse, LoginError, { username: string; password: string }>({
    mutationFn: (creds: { username: string; password: string }) =>
      api.post('/auth/login', creds).then((response) => response.data as LoginResponse),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['auth-me'] });
      router.push('/dashboard');
    },
    onError: (error) => {
      console.error('Login error:', error);
    },
  });

  return { login };
}
