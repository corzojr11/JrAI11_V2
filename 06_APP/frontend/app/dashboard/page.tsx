import AuthGate from '@/components/AuthGate';
import Dashboard from '@/components/Dashboard';

export default function DashboardPage() {
  return (
    <AuthGate allowedRoles={['admin', 'user']} allowedPlans={['premium', 'vip']}>
      <Dashboard />
    </AuthGate>
  );
}
