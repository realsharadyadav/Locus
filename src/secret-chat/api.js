const request = async (path, options = {}) => {
  const response = await fetch(`/api/secret-chat${path}`, {
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
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
};

export const secretChatApi = {
  create: () => request('', { method: 'POST' }),
  get: (token) => request(`/${token}`),
  getMessages: (token, after = 0) => request(`/${token}/messages?after=${after}`),
  sendMessage: (token, sender, content) => request(`/${token}/messages`, { method: 'POST', body: JSON.stringify({ sender, content }) }),
  stream: (token, after = 0) => `/api/secret-chat/${token}/stream?after=${after}`,
};
