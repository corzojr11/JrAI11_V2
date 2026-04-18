import AuthGate from '@/components/AuthGate';
import OperationFlow from '@/components/OperationFlow';

export default function OperationPage() {
  return (
    <AuthGate allowedRoles={['admin']}>
      <OperationFlow />
    </AuthGate>
  );
}
