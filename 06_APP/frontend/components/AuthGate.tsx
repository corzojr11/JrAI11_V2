'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import type { AxiosError } from 'axios';
import api from '@/lib/api';
import { useCurrentUser } from '@/hooks/useCurrentUser';

type AuthGateProps = {
  children: React.ReactNode;
  allowedRoles?: string[];
  allowedPlans?: string[];
};

function normalize(values?: string[]) {
  return (values ?? []).map((value) => value.trim().toLowerCase()).filter(Boolean);
}

export default function AuthGate({ children, allowedRoles, allowedPlans }: AuthGateProps) {
  const router = useRouter();
  const currentUserQuery = useCurrentUser();

  const role = String(currentUserQuery.data?.role ?? '').toLowerCase();
  const subscriptionPlan = String(currentUserQuery.data?.subscription_plan ?? '').toLowerCase();
  const roleAllowed = !allowedRoles?.length || normalize(allowedRoles).includes(role);
  const planAllowed = !allowedPlans?.length || role === 'admin' || normalize(allowedPlans).includes(subscriptionPlan);

  useEffect(() => {
    if (currentUserQuery.isError) {
      router.replace('/login');
    }
  }, [currentUserQuery.isError, router]);

  const status = (currentUserQuery.error as AxiosError | undefined)?.response?.status;

  if (currentUserQuery.isLoading) {
    return (
      <div className="dashboard-shell">
        <section className="panel">
          <div className="panel-title">Cargando acceso</div>
          <p className="muted">Verificando sesión activa...</p>
        </section>
      </div>
    );
  }

  if (status === 401) {
    return null;
  }

  if (!roleAllowed || !planAllowed) {
    return (
      <div className="dashboard-shell">
        <section className="panel">
          <div className="panel-title">Acceso restringido</div>
          <p className="muted">
            Tu cuenta no tiene permisos para esta vista.
          </p>
          <button
            type="button"
            className="ghost-button"
            onClick={() => {
              void api.post('/auth/logout').finally(() => router.replace('/login'));
            }}
          >
            Ir al login
          </button>
        </section>
      </div>
    );
  }

  return <>{children}</>;
}
