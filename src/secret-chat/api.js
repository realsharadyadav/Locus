import { API_BASE } from '../apiBase';

const request = async (path, options = {}) => {
  const response = await fetch(`${API_BASE}/api/secret-chat${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
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
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return response.status === 204 ? null : response.json();
};

const query = params => {
  const search = new URLSearchParams(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== ''),
  ).toString();
  return search ? `?${search}` : '';
};

export const secretChatApi = {
  create: (options = {}) => request('', { method: 'POST', body: JSON.stringify(options) }),
  rooms: (hostKey, clientId) => request(query({ host_key: hostKey, client_id: clientId })),
  get: (token, { clientId = '', hostKey = '' } = {}) => request(`/${token}${query({ client_id: clientId, host_key: hostKey })}`),
  updateOptions: (token, payload) => request(`/${token}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteRoom: (token, hostKey) => request(`/${token}${query({ host_key: hostKey })}`, { method: 'DELETE' }),
  deleteAllRooms: hostKey => request(query({ host_key: hostKey }), { method: 'DELETE' }),
  clearMessages: (token, hostKey) => request(`/${token}/messages${query({ host_key: hostKey })}`, { method: 'DELETE' }),
  getMessages: (token, after = 0) => request(`/${token}/messages?after=${after}`),
  sendMessage: (token, sender, content, viaAi = false) =>
    request(`/${token}/messages`, { method: 'POST', body: JSON.stringify({ sender, content, via_ai: viaAi }) }),
  presence: (token, payload) => request(`/${token}/presence`, { method: 'POST', body: JSON.stringify(payload) }),
  participants: (token, hostKey) => request(`/${token}/participants${query({ host_key: hostKey })}`),
  assist: (token, payload) => request(`/${token}/assist`, { method: 'POST', body: JSON.stringify(payload) }),
  stream: (token, after = 0) => `${API_BASE}/api/secret-chat/${token}/stream?after=${after}`,
};
