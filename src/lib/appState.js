import React from 'react';
import { readStorage, storageKey } from '../brand';

export const DEFAULT_UPLOAD_LIMIT_MB = 25;

export const PROVIDER_LABELS = { ollama: 'Ollama', groq: 'Groq', openai: 'OpenAI', gemini: 'Gemini' };
export const DEFAULT_PROVIDER_MODELS = { ollama: 'llama3.2:latest', groq: 'openai/gpt-oss-20b', openai: 'gpt-5.4-mini', gemini: 'gemini-2.5-flash' };
export const AI_PREFERENCE_STORAGE_KEY = storageKey('explore-ai');
export const ACTIVE_CHAT_STORAGE_KEY = storageKey('explore-active-chat');
export const APP_DATA_CACHE_KEY = storageKey('last-data');
export const APP_PAGES = ['home', 'library', 'ask', 'ticket-analysis', 'secret-chat', 'settings'];
export const normalizePageId = pageId => {
  if (pageId === 'ticketinsight' || pageId === 'ticket-analysis-lab') return 'ticket-analysis';
  // Legacy route/page ids kept working for old bookmarks and shared links.
  if (pageId === 'hub') return 'library';
  if (pageId === 'explore') return 'ask';
  return pageId;
};

export function readSavedAiPreference() {
  try {
    return JSON.parse(readStorage('explore-ai', '{}'));
  } catch {
    return {};
  }
}

export function readCachedAppData() {
  try {
    return JSON.parse(readStorage('last-data', '{}'));
  } catch {
    return {};
  }
}
