'use client';
import { useState } from 'react';
import { useAuth } from '@/hooks/useAuth';

export default function LoginForm() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const { login } = useAuth();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    login.mutate({ username, password });
  };

  return (
    <form onSubmit={handleSubmit} style={{ padding: 40, display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 320 }}>
      <input
        type="text"
        value={username}
        onChange={(e) => setUsername(e.target.value)}
        placeholder="Username"
        required
        disabled={login.isPending}
      />
      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Password"
        required
        disabled={login.isPending}
      />
      <button type="submit" disabled={login.isPending}>
        {login.isPending ? 'Entrando...' : 'Login'}
      </button>
      {login.isError && (
        <p style={{ color: 'red' }}>
          Error: {login.error?.response?.data?.detail || 'Credenciales inválidas'}
        </p>
      )}
    </form>
  );
}
