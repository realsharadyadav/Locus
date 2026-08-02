import React, { useEffect, useState } from 'react';
import {
  AlertTriangle,
  BookOpen,
  Check,
  CircleCheck,
  Database,
  Info,
  KeyRound,
  LogOut,
  Radio,
  Sparkles,
  Zap,
} from 'lucide-react';
import { api } from '../api';
import { BRAND, writeStorage } from '../brand';
import { ModelTable } from '../components/ModelTable';
import { DEFAULT_PROVIDER_MODELS, PROVIDER_LABELS, PROVIDER_META, PROVIDER_ORDER, readSavedAiPreference } from '../lib/appState';

export const REASONING_MODE_META = [
  { id: 'light', label: 'Light', icon: Radio, desc: 'Fast direct chat — default mode' },
  { id: 'unrestricted', label: 'Unrestricted', icon: Zap, desc: 'Expert mode — direct, low-fluff answers' },
  { id: 'thinking', label: 'Thinking', icon: Sparkles, desc: 'Deep analysis — inspects all selected content' },
  { id: 'deep_summary', label: 'Deep Summary', icon: BookOpen, desc: 'Complete section-by-section doc coverage' },
  { id: 'ticket_analysis', label: 'Ticket Analysis', icon: Database, desc: 'Group incidents by problem pattern' },
];

export function SettingsPage({ toast, authRequired = false, onSignOut }) {
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState(null);
  const [customModel, setCustomModel] = useState('');
  const [limits, setLimits] = useState(null);
  const [limitInput, setLimitInput] = useState('');
  const [savingLimit, setSavingLimit] = useState(false);
  const [enabledProviders, setEnabledProviders] = useState(null);
  const [savingProviders, setSavingProviders] = useState(false);
  const [enabledModels, setEnabledModels] = useState(null);
  const [savingModels, setSavingModels] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.llmConfig(),
      api.preference('explore_ai').catch(() => ({ value: {} })),
      api.systemLimits().catch(() => null),
      api.preference('enabled_providers').catch(() => ({ value: {} })),
      api.preference('enabled_models').catch(() => ({ value: {} })),
    ])
      .then(([llmConfig, preference, systemLimits, enabledProvidersPref, enabledModelsPref]) => {
        if (cancelled) return;
        setConfig(llmConfig);
        const saved = { ...readSavedAiPreference(), ...(preference.value || {}) };
        setDraft({
          provider: saved.provider || llmConfig.provider || 'ollama',
          model: saved.model || llmConfig.model || '',
          reasoning_mode: saved.reasoning_mode === 'web_research' ? 'light' : (saved.reasoning_mode || 'light'),
          web_source_limit: saved.web_source_limit || 200,
        });
        if (systemLimits) {
          setLimits(systemLimits);
          setLimitInput(String(systemLimits.upload_max_mb));
        }
        const knownProviders = Object.keys(llmConfig.providers || {});
        const savedEnabled = enabledProvidersPref.value?.providers;
        // No preference saved yet means nothing has ever been hidden — default to everything on.
        setEnabledProviders(new Set(
          Array.isArray(savedEnabled) && savedEnabled.length
            ? savedEnabled.filter(id => knownProviders.includes(id))
            : knownProviders
        ));
        // Only providers the user has actually customized get an entry here — a provider with
        // no entry means "every one of its models is enabled" (same default-on semantics as
        // enabledProviders above), so most providers never need a stored list at all.
        const initialEnabledModels = {};
        for (const [provider, ids] of Object.entries(enabledModelsPref.value || {})) {
          if (Array.isArray(ids)) initialEnabledModels[provider] = new Set(ids);
        }
        setEnabledModels(initialEnabledModels);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const toggleProviderEnabled = (provider) => {
    setEnabledProviders(current => {
      const next = new Set(current);
      if (next.has(provider)) next.delete(provider);
      else next.add(provider);
      return next;
    });
  };

  const saveEnabledProviders = async () => {
    setSavingProviders(true);
    try {
      await api.updatePreference('enabled_providers', { providers: Array.from(enabledProviders) });
      toast('Enabled providers saved', 'success');
    } catch (error) {
      toast(error.message || 'Could not save enabled providers', 'error');
    } finally {
      setSavingProviders(false);
    }
  };

  const toggleModelEnabled = (provider, modelId) => {
    setEnabledModels(current => {
      // First customization for this provider: materialize the full "all enabled" list so
      // unchecking one model doesn't implicitly disable every model that isn't yet known.
      const baseSet = current[provider] ? new Set(current[provider]) : new Set(config?.providers?.[provider] || []);
      if (baseSet.has(modelId)) baseSet.delete(modelId);
      else baseSet.add(modelId);
      return { ...current, [provider]: baseSet };
    });
  };

  // Bulk version of the same logic, used by ModelTable's Select all / Deselect all — those act
  // on whatever the search/free-only filters currently leave visible, not the whole provider.
  const setModelsEnabled = (provider, modelIds, enabled) => {
    setEnabledModels(current => {
      const baseSet = current[provider] ? new Set(current[provider]) : new Set(config?.providers?.[provider] || []);
      for (const modelId of modelIds) {
        if (enabled) baseSet.add(modelId);
        else baseSet.delete(modelId);
      }
      return { ...current, [provider]: baseSet };
    });
  };

  const saveEnabledModels = async () => {
    setSavingModels(true);
    try {
      const payload = {};
      for (const [provider, set] of Object.entries(enabledModels)) {
        payload[provider] = Array.from(set);
      }
      await api.updatePreference('enabled_models', payload);
      toast('Enabled models saved', 'success');
    } catch (error) {
      toast(error.message || 'Could not save enabled models', 'error');
    } finally {
      setSavingModels(false);
    }
  };

  const saveUploadLimit = async () => {
    if (!limits) return;
    const requested = Math.max(1, Math.min(Math.round(Number(limitInput) || 0), limits.upload_ceiling_mb));
    setSavingLimit(true);
    try {
      await api.updatePreference('upload_limits', { max_mb: requested });
      const refreshed = await api.systemLimits();
      setLimits(refreshed);
      setLimitInput(String(refreshed.upload_max_mb));
      toast(`Upload limit set to ${refreshed.upload_max_mb} MB`, 'success');
    } catch (error) {
      toast(error.message || 'Could not save the upload limit', 'error');
    } finally {
      setSavingLimit(false);
    }
  };

  if (loading || !draft || !enabledProviders || !enabledModels) {
    return (
      <div className="page settings-page">
        <div className="loading-grid">
          {[1, 2].map(item => <div key={item} className="skeleton-card" />)}
        </div>
      </div>
    );
  }

  const knownProviders = Object.keys(config?.providers || {});
  const providerOrder = config?.provider_order?.length ? config.provider_order : PROVIDER_ORDER;
  const providers = providerOrder.filter(id => knownProviders.includes(id));
  const providerModels = provider => config?.providers?.[provider] || [];
  const providerReady = provider => provider === 'ollama' ? providerModels('ollama').length > 0 : providerModels(provider).length > 0;
  const modelMeta = config?.model_meta || {};

  const selectProvider = (provider) => {
    const options = providerModels(provider);
    setDraft(current => ({ ...current, provider, model: options[0] || DEFAULT_PROVIDER_MODELS[provider] || '' }));
    setCustomModel('');
  };

  const selectModel = (model) => {
    setDraft(current => ({ ...current, model }));
    setCustomModel('');
  };

  const applyCustomModel = () => {
    const value = customModel.trim();
    if (!value) return;
    setDraft(current => ({ ...current, model: value }));
  };

  const selectReasoningMode = (mode) => {
    setDraft(current => ({ ...current, reasoning_mode: mode }));
  };

  const save = async () => {
    setSaving(true);
    try {
      await api.updatePreference('explore_ai', draft);
      writeStorage('explore-ai', JSON.stringify(draft));
      toast('Default provider, model, and mode saved', 'success');
    } catch (error) {
      toast(error.message || 'Could not save settings', 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page settings-page">
      <div className="inner-title">
        <div>
          <span className="kicker">SETTINGS</span>
          <h1>Providers & models</h1>
          <p>Choose what {BRAND.name} uses by default for new conversations.</p>
        </div>
      </div>

      <section className="settings-section">
        <h3>Default provider</h3>
        <div className="settings-provider-grid">
          {providers.map(provider => {
            const meta = PROVIDER_META[provider];
            const ready = providerReady(provider);
            const active = draft.provider === provider;
            const enabled = enabledProviders.has(provider);
            return (
              <div key={provider} className={`settings-provider-card ${active ? 'active' : ''} ${enabled ? '' : 'disabled'}`}>
                <button
                  type="button"
                  className="settings-provider-card-select"
                  onClick={() => selectProvider(provider)}
                >
                  <span className="settings-provider-icon">{meta.icon}</span>
                  <span className="settings-provider-info">
                    <strong>{PROVIDER_LABELS[provider]}</strong>
                    <small>{meta.blurb}</small>
                  </span>
                  <span className={`settings-provider-status ${ready ? 'ready' : 'idle'}`}>
                    {ready ? <CircleCheck size={13} /> : <AlertTriangle size={13} />}
                    {ready ? `${providerModels(provider).length} model${providerModels(provider).length === 1 ? '' : 's'}` : 'Not connected'}
                  </span>
                </button>
                <label className="settings-provider-toggle">
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={() => toggleProviderEnabled(provider)}
                  />
                  <span>Show in {BRAND.name}</span>
                </label>
              </div>
            );
          })}
        </div>
        <div className="settings-save-bar settings-save-bar-inline">
          <button type="button" className="btn-primary" onClick={saveEnabledProviders} disabled={savingProviders}>
            {savingProviders ? 'Saving...' : 'Save enabled providers'}
          </button>
        </div>

        {!providerReady(draft.provider) && (
          <div className="settings-hint">
            <Info size={14} />
            <span>{PROVIDER_META[draft.provider].envHint}</span>
          </div>
        )}

        <div className="settings-model-header">
          <h3>Default model</h3>
        </div>
        {providerModels(draft.provider).length === 0 ? (
          <p className="settings-empty-note">No models detected yet for {PROVIDER_LABELS[draft.provider]}. You can still set a model ID manually below.</p>
        ) : (
          <>
            <ModelTable
              models={providerModels(draft.provider)}
              modelMeta={modelMeta}
              selectedModel={draft.model}
              onSelect={selectModel}
              enabledModelIds={enabledModels[draft.provider] || null}
              onToggleEnabled={id => toggleModelEnabled(draft.provider, id)}
              onSetEnabled={(ids, enabled) => setModelsEnabled(draft.provider, ids, enabled)}
            />
            <div className="settings-save-bar settings-save-bar-inline">
              <button type="button" className="btn-primary" onClick={saveEnabledModels} disabled={savingModels}>
                {savingModels ? 'Saving...' : 'Save enabled models'}
              </button>
            </div>
          </>
        )}
        <div className="settings-custom-model">
          <input
            type="text"
            placeholder="Or type a custom model ID..."
            value={customModel}
            onChange={e => setCustomModel(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); applyCustomModel(); } }}
          />
          <button type="button" onClick={applyCustomModel} disabled={!customModel.trim()}>Use</button>
        </div>
        <div className="settings-current-model">
          <KeyRound size={13} />
          <span>Current default: <strong>{PROVIDER_LABELS[draft.provider]} / {draft.model || 'none selected'}</strong></span>
        </div>
      </section>

      {limits && (
        <section className="settings-section">
          <h3>File upload limit</h3>
          <p className="settings-hint-text">{limits.reason}</p>
          <div className="settings-limit-row">
            <input
              type="number"
              min={1}
              max={limits.upload_ceiling_mb}
              value={limitInput}
              onChange={e => setLimitInput(e.target.value)}
            />
            <span>MB (max {limits.upload_ceiling_mb} MB on this deployment)</span>
            <button type="button" className="btn-primary" onClick={saveUploadLimit} disabled={savingLimit}>
              {savingLimit ? 'Saving...' : 'Save limit'}
            </button>
          </div>
        </section>
      )}

      <section className="settings-section">
        <h3>Default reasoning mode</h3>
        <div className="settings-mode-grid">
          {REASONING_MODE_META.map(mode => {
            const Icon = mode.icon;
            const active = draft.reasoning_mode === mode.id;
            return (
              <button
                key={mode.id}
                type="button"
                className={`settings-mode-card ${active ? 'active' : ''}`}
                onClick={() => selectReasoningMode(mode.id)}
              >
                <Icon size={16} />
                <span>
                  <strong>{mode.label}</strong>
                  <small>{mode.desc}</small>
                </span>
                {active && <Check size={14} className="settings-mode-check" />}
              </button>
            );
          })}
        </div>
      </section>

      {authRequired && (
        <section className="settings-section">
          <h3>Session</h3>
          {/* One shared password guards this workspace, so there is no account
              to show — just the way out. */}
          <p className="settings-hint-text">Signed in with the workspace password. Signing out only clears this browser.</p>
          <button type="button" className="settings-signout" onClick={onSignOut}>
            <LogOut size={15} />
            Sign out
          </button>
        </section>
      )}

      <div className="settings-save-bar">
        <button type="button" className="btn-primary" onClick={save} disabled={saving}>
          {saving ? 'Saving...' : 'Save defaults'}
        </button>
      </div>
    </div>
  );
}
