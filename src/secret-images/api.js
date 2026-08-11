import { API_BASE } from '../apiBase';
import { authHeaders, getAuthToken, handleUnauthorized } from '../auth';

/**
 * `fetch` rejects with a bare TypeError("Failed to fetch") when the request never
 * reached the server at all — API asleep, offline, DNS, CORS. That string went
 * straight into a toast, where it told the reader nothing about what to do.
 * Anything that did reach the server arrives as a response and keeps its own
 * message, so only the transport failure is reworded here.
 */
const send = async (url, init) => {
  try {
    return await fetch(url, init);
  } catch {
    throw new Error("Can't reach the server — check your connection and try again.");
  }
};

const request = async (path, options = {}) => {
  const response = await send(`${API_BASE}/api/secret-images${path}`, {
    // `headers` after the spread: options carrying its own headers must not drop
    // the auth token on the floor.
    ...options,
    headers: { ...authHeaders(), ...options.headers },
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

/**
 * Fetch the image bytes and hand back an object URL.
 *
 * The obvious `<img src={image.url}>` cannot work here for two independent
 * reasons, and both bit at once:
 *
 * 1. `/api/secret-images/view/{id}` sits behind the Sign-in Gate, and a browser
 *    image request carries no `Authorization` header — every thumbnail came back
 *    401 and rendered as a broken image.
 * 2. The backend returns that path relative, so on a split deployment (static
 *    frontend, separate API service) it resolved against the *frontend* origin,
 *    where the SPA rewrite answers with index.html instead of a photo.
 *
 * Fetching through the same authenticated helper as everything else fixes both:
 * the token travels in a header where it belongs — not in a query string, which
 * for this feature in particular would leak it into history and access logs —
 * and API_BASE points at the real API.
 */
const objectUrl = async path => {
  const response = await send(`${API_BASE}/api/secret-images${path}`, { headers: authHeaders() });
  if (response.status === 401 && getAuthToken()) {
    handleUnauthorized();
  }
  if (!response.ok) throw new Error('Could not load image');
  return URL.createObjectURL(await response.blob());
};

export const secretImagesApi = {
  status: () => request('/status'),
  list: () => request(''),
  view: id => objectUrl(`/view/${id}`),
  upload: file => {
    const body = new FormData();
    body.append('file', file);
    return request('', { method: 'POST', body });
  },
  remove: id => request(`/${id}`, { method: 'DELETE' }),
};
