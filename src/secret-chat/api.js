import { API_BASE } from '../apiBase';
import { authHeaders, handleUnauthorized } from '../auth';

/**
 * Guest calls (read a room, read/post messages, stream) carry no token and the
 * backend leaves them public. The host-only calls — list, create, rename,
 * delete — need the header, so it goes on every request and is simply empty in
 * a guest's browser.
 */
const request = async (path, options = {}) => {
  const response = await fetch(`${API_BASE}/api/secret-chat${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...options.headers },
  });
  if (response.status === 401) handleUnauthorized();
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    const message = typeof detail === 'string'
      ? detail
      : Array.isArray(detail)
        ? detail.map(item => item.msg || JSON.stringify(item)).join(', ')
        : detail && typeof detail === 'object'
          ? JSON.stringify(detail)
          : 'Something went wrong';
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
};

export const secretChatApi = {
  create: () => request('', { method: 'POST' }),
  list: () => request(''),
  rename: (token, title) => request(`/${token}`, { method: 'PATCH', body: JSON.stringify({ title }) }),
  remove: (token) => request(`/${token}`, { method: 'DELETE' }),
  get: (token) => request(`/${token}`),
  getMessages: (token, after = 0) => request(`/${token}/messages?after=${after}`),
  sendMessage: (token, sender, content) => request(`/${token}/messages`, { method: 'POST', body: JSON.stringify({ sender, content }) }),
  stream: (token, after = 0) => `${API_BASE}/api/secret-chat/${token}/stream?after=${after}`,
};
