import { readStorage, writeStorage } from './brand';

/**
 * Client half of the Phase 1 password gate.
 *
 * The token is a signed expiry stamp from the backend, not a user identity —
 * everyone who signs in shares one workspace. It rides in the Authorization
 * header rather than a cookie because the frontend and backend are served from
 * different origins in production (see render.yaml), where a cross-site cookie
 * would need SameSite=None and lose to third-party cookie blocking.
 *
 * Sign-out is purely local: the backend keeps no session state, so dropping the
 * token is the whole operation.
 */

const TOKEN_KEY = 'auth-token';

let unauthorizedHandler = null;

export const getAuthToken = () => readStorage(TOKEN_KEY, '') || '';

export const setAuthToken = token => writeStorage(TOKEN_KEY, token || '');

export const clearAuthToken = () => writeStorage(TOKEN_KEY, '');

export const authHeaders = () => {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
};

/** Lets App.jsx swap back to the login screen when any request 401s. */
export const onUnauthorized = handler => { unauthorizedHandler = handler; };

/**
 * Called by the API layer on a 401. Drops the stale token first so the retry a
 * component might attempt cannot loop against the same dead credential.
 */
export const handleUnauthorized = () => {
  clearAuthToken();
  unauthorizedHandler?.();
};
