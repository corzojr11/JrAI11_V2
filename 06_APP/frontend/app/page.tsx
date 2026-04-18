import AuthGate from '@/components/AuthGate';
import Dashboard from '@/components/Dashboard';

export default function Home() {
  return (
    <AuthGate allowedRoles={['admin', 'user']} allowedPlans={['premium', 'vip']}>
      <Dashboard />
    </AuthGate>
  );
}
