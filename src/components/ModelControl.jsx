import React, { useEffect, useRef, useState } from 'react';
import {
  Search,
} from 'lucide-react';
import { DEFAULT_PROVIDER_MODELS, PROVIDER_LABELS } from '../lib/appState';
import { formatContextLength } from '../lib/format';
import { useClickOutside } from '../hooks/useClickOutside';

export function ModelControl({ config, provider, setProvider, model, setModel }) {
  const providerIcons = { ollama: '🦙', groq: '⚡', openai: '🤖', gemini: '✨' };
  const [openMenu, setOpenMenu] = useState(null);
  const [modelQuery, setModelQuery] = useState('');
  const [freeOnly, setFreeOnly] = useState(false);
  const controlRef = useClickOutside(openMenu !== null, () => setOpenMenu(null));
  const modelSearchRef = useRef(null);
  const fallbackModels = {
    ollama: [],
    groq: [],
    openai: [],
    gemini: [],
  };
  useEffect(() => {
    if (openMenu === 'model') modelSearchRef.current?.focus();
    else { setModelQuery(''); setFreeOnly(false); }
  }, [openMenu]);
  const backendModels = config?.providers?.[provider] || [];
  const presetModels = provider === config?.provider ? (config?.presets || []) : [];
  const modelOptions = [...new Set([model, ...backendModels, ...presetModels, ...(fallbackModels[provider] || [])].filter(Boolean))];
  const modelMeta = config?.model_meta || {};
  const isFreeModel = item => !!modelMeta[item]?.free;
  const contextOf = item => modelMeta[item]?.context_length || 0;
  const visibleModelOptions = modelOptions
    .filter(item => (freeOnly ? isFreeModel(item) : true))
    .filter(item => (modelQuery.trim() ? item.toLowerCase().includes(modelQuery.trim().toLowerCase()) : true))
    .sort((a, b) => contextOf(b) - contextOf(a));
  const listedModel = modelOptions.includes(model) ? model : modelOptions[0] || DEFAULT_PROVIDER_MODELS[provider];
  const changeProvider = nextProvider => {
    const nextOptions = config?.providers?.[nextProvider] || [];
    setProvider(nextProvider);
    setModel(nextOptions[0] || (nextProvider === config?.provider ? config.model : DEFAULT_PROVIDER_MODELS[nextProvider]));
  };
  return (
    <div className="model-control" ref={controlRef} aria-label="Choose the AI provider and model used for answers">
      <div className={`model-control-field mc-provider ${openMenu === 'provider' ? 'open' : ''}`}>
        <button
          type="button"
          className="mc-trigger"
          onClick={() => setOpenMenu(openMenu === 'provider' ? null : 'provider')}
          aria-expanded={openMenu === 'provider'}
          aria-label="LLM provider"
        >
          <span className="mc-icon" aria-hidden="true">{providerIcons[provider]}</span>
          <span className="mc-copy">
            <span className="mc-label">Provider</span>
            <span className="mc-value">{PROVIDER_LABELS[provider]}</span>
          </span>
          <svg className="mc-chevron" width="10" height="6" viewBox="0 0 10 6" fill="none"><path d="M1 1l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
        </button>
        {openMenu === 'provider' && (
          <div className="mc-menu" role="listbox" aria-label="LLM provider menu">
            {Object.keys(config?.providers || DEFAULT_PROVIDER_MODELS).map(item => {
              const active = item === provider;
              return (
                <button
                  key={item}
                  type="button"
                  className={`mc-option ${active ? 'active' : ''}`}
                  onClick={() => {
                    changeProvider(item);
                    setOpenMenu(null);
                  }}
                  role="option"
                  aria-selected={active}
                >
                  <span className="mc-option-icon" aria-hidden="true">{providerIcons[item]}</span>
                  <span className="mc-option-text">
                    <strong>{PROVIDER_LABELS[item]}</strong>
                    <small>{item === 'ollama' ? 'Local models' : item === 'groq' ? 'Fast cloud' : item === 'openai' ? 'OpenAI' : 'Google Gemini'}</small>
                  </span>
                  {active && <span className="mc-option-check">✓</span>}
                </button>
              );
            })}
          </div>
        )}
      </div>
      <div className="mc-divider" />
      <div className={`model-control-field mc-model ${openMenu === 'model' ? 'open' : ''}`}>
        <button
          type="button"
          className="mc-trigger"
          onClick={() => setOpenMenu(openMenu === 'model' ? null : 'model')}
          aria-expanded={openMenu === 'model'}
          aria-label={`${PROVIDER_LABELS[provider]} model presets`}
        >
          <span className="mc-copy">
            <span className="mc-label">Model</span>
            <span className="mc-value mc-value-model">{listedModel}</span>
          </span>
          <svg className="mc-chevron" width="10" height="6" viewBox="0 0 10 6" fill="none"><path d="M1 1l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
        </button>
        {openMenu === 'model' && (
          <div className="mc-menu mc-menu-model" role="listbox" aria-label="Model presets menu">
            <div className="mc-model-search">
              <Search size={12} className="mc-model-search-icon" />
              <input
                ref={modelSearchRef}
                type="text"
                placeholder="Search models..."
                value={modelQuery}
                onChange={e => setModelQuery(e.target.value)}
                onKeyDown={e => e.stopPropagation()}
              />
              <button
                type="button"
                className={`mc-free-toggle ${freeOnly ? 'active' : ''}`}
                onClick={() => setFreeOnly(current => !current)}
                aria-pressed={freeOnly}
                title="Show only free models"
              >
                Free only
              </button>
            </div>
            {visibleModelOptions.length === 0 && (
              <div className="mc-model-empty">No models match your search.</div>
            )}
            {visibleModelOptions.map(item => {
              const active = item === listedModel;
              const contextLabel = formatContextLength(contextOf(item));
              return (
                <button
                  key={item}
                  type="button"
                  className={`mc-option mc-option-model ${active ? 'active' : ''}`}
                  onClick={() => {
                    setModel(item);
                    setOpenMenu(null);
                  }}
                  role="option"
                  aria-selected={active}
                  title={item}
                >
                  <span className="mc-option-text">
                    <strong>{item}</strong>
                    <small>
                      {active ? 'Selected model' : 'Available preset'}
                      {contextLabel ? ` · ${contextLabel}` : ''}
                    </small>
                  </span>
                  {isFreeModel(item) && <span className="mc-free-tag">Free</span>}
                  {active && <span className="mc-option-check">✓</span>}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
