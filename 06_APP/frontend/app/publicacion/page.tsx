import AuthGate from '@/components/AuthGate';
import PublicationHub from '@/components/PublicationHub';

export default function PublicationPage() {
  return (
    <AuthGate allowedRoles={['admin', 'user']}>
      <PublicationHub />
    </AuthGate>
  );
}
