import { API_BASE } from '../apiBase';
import { authHeaders, getAuthToken, handleUnauthorized } from '../auth';

const request = async (path, options = {}) => {
  const response = await fetch(`${API_BASE}/api/secret-images${path}`, {
    headers: { ...authHeaders(), ...options.headers },
    ...options,
  });
  if (response.status === 401 && getAuthToken()) {
    handleUnauthorized();
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    const message = typeof detail === 'string' ? detail : 'Something went wrong';
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return response.status === 204 ? null : response.json();
};

export const secretImagesApi = {
  status: () => request('/status'),
  list: () => request(''),
  upload: file => {
    const body = new FormData();
    body.append('file', file);
    return request('', { method: 'POST', body });
  },
  remove: id => request(`/${id}`, { method: 'DELETE' }),
};
