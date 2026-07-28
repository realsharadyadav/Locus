import React, { useState } from 'react';
import { BRAND } from '../brand';
import { setAuthToken } from '../auth';
import { api } from '../api';
import { Logo } from './Logo';

/**
 * The Phase 1 password gate.
 *
 * One shared password, not an account — so there is no email field, no sign-up
 * and no reset flow. It mirrors the boot splash on purpose: signing in should
 * feel like the workspace still loading, not like a different product.
 */
export function LoginPage({ onSignedIn }) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const submit = async event => {
    event.preventDefault();
    if (!password || submitting) return;
    setSubmitting(true);
    setError('');
    try {
      const { token } = await api.login(password);
      setAuthToken(token);
      setPassword('');
      onSignedIn();
    } catch (loginError) {
      setError(loginError.message || 'Sign in failed');
      setSubmitting(false);
    }
  };

  return (
    <div className="login">
      <form className="login-card" onSubmit={submit}>
        <Logo />
        <p className="login-tagline">{BRAND.tagline}</p>
        <label className="login-field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            autoFocus
            autoComplete="current-password"
            placeholder="Enter the workspace password"
            aria-invalid={Boolean(error)}
            onChange={event => { setPassword(event.target.value); setError(''); }}
          />
        </label>
        {/* aria-live so a screen reader announces a wrong password without the
            field losing focus. */}
        <p className="login-error" role="alert" aria-live="polite">{error}</p>
        <button className="login-submit" type="submit" disabled={!password || submitting}>
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
