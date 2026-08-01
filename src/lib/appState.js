import React from 'react';
import { readStorage, storageKey } from '../brand';

export const DEFAULT_UPLOAD_LIMIT_MB = 25;

export const PROVIDER_LABELS = { ollama: 'Ollama', groq: 'Groq', openai: 'OpenAI', gemini: 'Gemini', openrouter: 'OpenRouter', tokenrouter: 'TokenRouter' };
export const DEFAULT_PROVIDER_MODELS = { ollama: 'llama3.2:latest', groq: 'openai/gpt-oss-20b', openai: 'gpt-5.4-mini', gemini: 'gemini-2.5-flash', openrouter: 'openrouter/auto', tokenrouter: '' };
// Fallback ordering before /api/llm/config responds (which also sends provider_order, the
// backend's own PROVIDERS registry order — the two are kept in sync by hand).
export const PROVIDER_ORDER = ['ollama', 'groq', 'openai', 'gemini', 'openrouter', 'tokenrouter'];
// Single source of truth for provider icon/blurb/env-hint copy, shared by ModelControl and
// SettingsPage so the two don't drift out of sync with each other.
export const PROVIDER_META = {
  ollama: { icon: '🦙', blurb: 'Local models, no API key needed', envHint: 'Runs against OLLAMA_URL — start Ollama and pull a model.' },
  groq: { icon: '⚡', blurb: 'Fast cloud inference', envHint: 'Set GROQ_API_KEY in your .env file.' },
  openai: { icon: '🤖', blurb: 'OpenAI models', envHint: 'Set OPENAI_API_KEY in your .env file.' },
  gemini: { icon: '✨', blurb: 'Google Gemini models', envHint: 'Set GEMINI_API_KEY in your .env file.' },
  openrouter: { icon: '🌐', blurb: 'One API for many model providers', envHint: 'Set OPENROUTER_API_KEY in your .env file.' },
  tokenrouter: { icon: '🔀', blurb: 'Unified gateway across many models', envHint: 'Set TOKENROUTER_API_KEY in your .env file.' },
};
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
