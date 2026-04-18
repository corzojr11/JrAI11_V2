import AuthGate from '@/components/AuthGate';
import LabHub from '@/components/LabHub';

export default function LabPage() {
  return (
    <AuthGate allowedRoles={['admin']}>
      <LabHub />
    </AuthGate>
  );
}
