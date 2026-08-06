import { API_BASE } from './apiBase';
import { authHeaders, handleUnauthorized } from './auth';

/**
 * A 401 means the shared password gate turned us away — an expired token, or a
 * password rotated under us. Hand off to the auth layer so the app returns to
 * the login screen instead of surfacing a generic error inside the workspace.
 */
const checkAuthorized = response => {
  if (response.status === 401) handleUnauthorized();
  return response;
};

const request = async (path, options = {}) => {
  const response = checkAuthorized(await fetch(`${API_BASE}/api${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...options.headers },
  }));
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

export const api = {
  // Public endpoint: it tells the app whether a login screen is needed at all.
  authStatus: () => request('/auth/status'),
  authMe: () => request('/auth/me'),
  // Deliberately bypasses checkAuthorized — a 401 here is a wrong password, not
  // a dead session, and must not bounce the login screen it came from.
  login: async (password) => {
    const response = await fetch(`${API_BASE}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Sign in failed');
    return body;
  },
  llmConfig: () => request('/llm/config'),
  systemLimits: () => request('/system/limits'),
  preference: (key) => request(`/preferences/${key}`),
  updatePreference: (key, value) => request(`/preferences/${key}`, { method: 'PATCH', body: JSON.stringify({ value }) }),
  collections: () => request('/collections'),
  files: () => request('/files'),
  createCollection: (data) => request('/collections', { method: 'POST', body: JSON.stringify(data) }),
  deleteCollection: (id) => request(`/collections/${id}`, { method: 'DELETE' }),
  uploadFile: async (storeId, file) => {
    const body = new FormData();
    body.append('store_id', storeId);
    body.append('file', file);
    // No Content-Type here on purpose: the browser sets the multipart boundary.
    const response = checkAuthorized(await fetch(`${API_BASE}/api/files`, { method: 'POST', body, headers: authHeaders() }));
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || 'Upload failed');
    return response.json();
  },
  deleteFile: (id) => request(`/files/${id}`, { method: 'DELETE' }),
  ticketAnalysis: (fileId, maxGroups, minGroupSize, useLlmFallback = false, model, options = {}) => request('/ticket-analysis', {
    method: 'POST',
    body: JSON.stringify({ fileId, maxGroups, minGroupSize, useLlmFallback, model, ...options }),
  }),
  ticketAnalysisStream: async (fileId, maxGroups, minGroupSize, useLlmFallback = false, model, options = {}, onEvent = () => {}) => {
    const response = checkAuthorized(await fetch(`${API_BASE}/api/ticket-analysis/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ fileId, maxGroups, minGroupSize, useLlmFallback, model, ...options }),
    }));
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || 'Unable to start the analysis pipeline');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = ''; let result = null;
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split('\n'); buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        onEvent(event);
        if (event.type === 'result') result = event.data;
        if (event.type === 'error') throw new Error(event.detail);
      }
      if (done) break;
    }
    if (!result) throw new Error('The analysis pipeline ended without a result');
    return result;
  },
  ticketAnalysisOkfTaxonomy: () => request('/ticket-analysis/okf-taxonomy'),
  ticketAnalysisHistory: () => request('/ticket-analysis/history'),
  ticketAnalysisHistoryDetail: (id) => request(`/ticket-analysis/history/${id}`),
  saveTicketAnalysis: (data) => request('/ticket-analysis/history', { method: 'POST', body: JSON.stringify(data) }),
  deleteTicketAnalysisHistory: (id) => request(`/ticket-analysis/history/${id}`, { method: 'DELETE' }),
  createChatJob: (question, conversationId, provider, model, allowGeneralKnowledge, reasoningMode, fileIds, webSourceLimit, webSearch = false) => request('/chat/jobs', {
    method: 'POST',
    body: JSON.stringify({ question, conversation_id: conversationId, provider, model, allow_general_knowledge: allowGeneralKnowledge, reasoning_mode: reasoningMode, file_ids: fileIds, web_source_limit: webSourceLimit, web_search: webSearch }),
  }),
  chatJobs: () => request('/chat/jobs'),
  markChatJobSeen: (id) => request(`/chat/jobs/${id}/seen`, { method: 'PATCH' }),
  cancelChatJob: (id) => request(`/chat/jobs/${id}/cancel`, { method: 'POST' }),
  chatStream: async (question, conversationId, provider, model, allowGeneralKnowledge, reasoningMode, webSourceLimit, webSearch, onEvent, options = {}) => {
    const response = checkAuthorized(await fetch(`${API_BASE}/api/chat/stream`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify({ question, conversation_id: conversationId, provider, model, allow_general_knowledge: allowGeneralKnowledge, reasoning_mode: reasoningMode, web_source_limit: webSourceLimit, web_search: webSearch }), signal: options.signal }));
    if (!response.ok) throw new Error('Unable to start the answer pipeline');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = ''; let result = null;
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split('\n'); buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        onEvent(event);
        if (event.type === 'result') result = event.data;
        if (event.type === 'error') throw new Error(event.detail);
      }
      if (done) break;
    }
    if (!result) throw new Error('The answer pipeline ended without a result');
    return result;
  },
  directChatStream: async (question, conversationId, provider, model, allowGeneralKnowledge, reasoningMode, onEvent, options = {}) => {
    const response = checkAuthorized(await fetch(`${API_BASE}/api/chat/direct-stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ question, conversation_id: conversationId, provider, model, allow_general_knowledge: allowGeneralKnowledge, reasoning_mode: reasoningMode, file_ids: [], web_search: false }),
      signal: options.signal,
    }));
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Unable to start direct chat stream');
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = ''; let result = null;
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split('\n'); buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        onEvent(event);
        if (event.type === 'result') result = event.data;
        if (event.type === 'error') throw new Error(event.detail);
      }
      if (done) break;
    }
    if (!result) throw new Error('The direct chat stream ended without a result');
    return result;
  },
  chatSuggestions: (question, answer, provider, model) => request('/chat/suggestions', {
    method: 'POST',
    body: JSON.stringify({ question, answer, provider, model }),
  }),
  chats: () => request('/chats'),
  chatMessages: (id) => request(`/chats/${id}/messages`),
  stopChat: (id) => request(`/chats/${id}/stop`, { method: 'POST' }),
  truncateChatFromMessage: (chatId, messageId) => request(`/chats/${chatId}/messages/${messageId}/from`, { method: 'DELETE' }),
  deleteAllChats: () => request('/chats', { method: 'DELETE' }),
  deleteChat: (id) => request(`/chats/${id}`, { method: 'DELETE' }),
};
