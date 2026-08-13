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
import { PROVIDER_LABELS, PROVIDER_META, PROVIDER_ORDER, readSavedAiPreference } from '../lib/appState';

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
  // Which provider's catalogue is on screen in the visibility section. Deliberately separate
  // from draft.provider: browsing what a provider offers is not the same act as changing the
  // default, and conflating the two is what made this page confusing.
  const [catalogProvider, setCatalogProvider] = useState(null);
  // Which models actually answered a probe, keyed provider -> model. Saved server-side by the
  // test endpoint, so the tags are still there on the next visit.
  const [health, setHealth] = useState({});
  const [respondingOnly, setRespondingOnly] = useState(false);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.llmConfig(),
      api.preference('explore_ai').catch(() => ({ value: {} })),
      api.systemLimits().catch(() => null),
      api.preference('enabled_providers').catch(() => ({ value: {} })),
      api.preference('enabled_models').catch(() => ({ value: {} })),
      api.preference('model_health').catch(() => ({ value: {} })),
    ])
      .then(([llmConfig, preference, systemLimits, enabledProvidersPref, enabledModelsPref, modelHealthPref]) => {
        if (cancelled) return;
        setConfig(llmConfig);
        const saved = { ...readSavedAiPreference(), ...(preference.value || {}) };
        // Open the catalogue on a provider that actually has models to show — landing on the
        // default's provider is useless when that provider isn't connected, which is exactly
        // when you want to go looking at what else is available.
        const stocked = Object.entries(llmConfig.providers || {}).find(([, models]) => models.length);
        const preferredCatalog = saved.provider || llmConfig.provider || 'ollama';
        setCatalogProvider(
          (llmConfig.providers?.[preferredCatalog] || []).length ? preferredCatalog : (stocked?.[0] || preferredCatalog)
        );
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
        setHealth(modelHealthPref.value || {});
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

  const testModels = async (models) => {
    if (!models.length) return;
    setTesting(true);
    try {
      const result = await api.testModels(catalogProvider, models);
      setHealth(current => ({
        ...current,
        [catalogProvider]: { ...(current[catalogProvider] || {}), ...result.results },
      }));
      const responding = Object.values(result.results).filter(item => item.ok).length;
      toast(`${responding} of ${models.length} model${models.length === 1 ? '' : 's'} responded`, responding ? 'success' : 'error');
    } catch (error) {
      toast(error.message || 'Could not test these models', 'error');
    } finally {
      setTesting(false);
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

  if (loading || !draft || !enabledProviders || !enabledModels || !catalogProvider) {
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

  // Every model that could be the default, grouped by the provider that offers it. The
  // provider is never chosen by hand any more — it is read off the model you pick, and shown
  // only as a label (it still travels in the saved preference because the backend routes on it).
  const modelGroups = providers
    .map(provider => ({
      provider,
      models: providerModels(provider).filter(model => (respondingOnly ? health[provider]?.[model]?.ok : true)),
    }))
    .filter(group => group.models.length);
  const knownModel = modelGroups.some(group => group.models.includes(draft.model));

  const selectModel = (provider, model) => {
    setDraft(current => ({ ...current, provider, model }));
    setCustomModel('');
  };

  const applyCustomModel = () => {
    const value = customModel.trim();
    if (!value) return;
    // A hand-typed id belongs to whichever provider's catalogue is open — nothing else can
    // say where it should be routed.
    setDraft(current => ({ ...current, provider: catalogProvider, model: value }));
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
          <p>{BRAND.name} answers with one model everywhere — Ask, Ticket Analysis and Private Chats. Choose it here.</p>
        </div>
      </div>

      {/* Two separate jobs, two separate sections. Picking the one model the app answers with
          used to share a panel with the checkboxes that hide providers and models from the
          catalogue, and selecting a row meant two different things depending on where you
          clicked it. The default lives on its own below; the catalogue follows it. */}
      <section className="settings-section settings-default-section">
        <div className="settings-section-head">
          <h3>Default model</h3>
          <p className="settings-hint-text">Used by every module. Nothing else in {BRAND.name} asks you to pick a model.</p>
        </div>

        <div className="settings-default-picker">
          <label className="settings-provider-filter settings-default-model-field">
            <span>Model</span>
            <select
              value={knownModel ? `${draft.provider}::${draft.model}` : ''}
              onChange={e => {
                const [provider, ...rest] = e.target.value.split('::');
                if (rest.length) selectModel(provider, rest.join('::'));
              }}
            >
              {!knownModel && <option value="">{draft.model || 'none selected'}</option>}
              {modelGroups.map(group => (
                <optgroup key={group.provider} label={`${PROVIDER_LABELS[group.provider]} (${group.models.length})`}>
                  {group.models.map(model => (
                    <option key={`${group.provider}::${model}`} value={`${group.provider}::${model}`}>
                      {model}{health[group.provider]?.[model] ? (health[group.provider][model].ok ? ' \u00B7 responding' : ' \u00B7 no answer') : ''}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
          <label className="settings-responding-filter">
            <input type="checkbox" checked={respondingOnly} onChange={() => setRespondingOnly(value => !value)} />
            <span>Only models that responded to a test</span>
          </label>
        </div>
        <div className="settings-default-provider">
          <span className="settings-provider-icon">{PROVIDER_META[draft.provider]?.icon}</span>
          <span>Runs on <strong>{PROVIDER_LABELS[draft.provider] || draft.provider}</strong> — taken from the model you picked.</span>
        </div>

        {!providerReady(draft.provider) && (
          <div className="settings-hint">
            <Info size={14} />
            <span>{PROVIDER_META[draft.provider].envHint}</span>
          </div>
        )}
        {providerModels(draft.provider).length === 0 && (
          <p className="settings-empty-note">No models detected yet for {PROVIDER_LABELS[draft.provider]}. You can still set a model ID manually below.</p>
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
        <div className="settings-save-bar settings-save-bar-inline">
          <button type="button" className="btn-primary" onClick={save} disabled={saving}>
            {saving ? 'Saving...' : 'Save default model'}
          </button>
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-head">
          <h3>Available providers & models</h3>
          <p className="settings-hint-text">Housekeeping only: what stays in this catalogue. Unticking something never changes the default above.</p>
        </div>
        <div className="settings-provider-grid">
          {providers.map(provider => {
            const meta = PROVIDER_META[provider];
            const ready = providerReady(provider);
            const browsing = catalogProvider === provider;
            const enabled = enabledProviders.has(provider);
            return (
              <div key={provider} className={`settings-provider-card ${browsing ? 'active' : ''} ${enabled ? '' : 'disabled'}`}>
                <button
                  type="button"
                  className="settings-provider-card-select"
                  onClick={() => setCatalogProvider(provider)}
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

        <div className="settings-model-header">
          <h4>{PROVIDER_LABELS[catalogProvider]} models</h4>
          <label className="settings-provider-filter">
            <span>Provider</span>
            <select value={catalogProvider} onChange={e => setCatalogProvider(e.target.value)}>
              {providers.map(provider => (
                <option key={provider} value={provider}>
                  {PROVIDER_LABELS[provider]} ({providerModels(provider).length})
                </option>
              ))}
            </select>
          </label>
        </div>
        {providerModels(catalogProvider).length === 0 ? (
          <p className="settings-empty-note">No models detected yet for {PROVIDER_LABELS[catalogProvider]}.</p>
        ) : (
          <>
            <ModelTable
              models={providerModels(catalogProvider)}
              modelMeta={modelMeta}
              selectedModel={catalogProvider === draft.provider ? draft.model : ''}
              onSelect={model => { setDraft(current => ({ ...current, provider: catalogProvider, model })); setCustomModel(''); }}
              health={health[catalogProvider] || {}}
              onTest={testModels}
              testing={testing}
              enabledModelIds={enabledModels[catalogProvider] || null}
              onToggleEnabled={id => toggleModelEnabled(catalogProvider, id)}
              onSetEnabled={(ids, enabled) => setModelsEnabled(catalogProvider, ids, enabled)}
            />
            <div className="settings-save-bar settings-save-bar-inline">
              <button type="button" className="btn-primary" onClick={saveEnabledModels} disabled={savingModels}>
                {savingModels ? 'Saving...' : 'Save enabled models'}
              </button>
            </div>
          </>
        )}
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
        <div className="settings-save-bar settings-save-bar-inline">
          <button type="button" className="btn-primary" onClick={save} disabled={saving}>
            {saving ? 'Saving...' : 'Save default mode'}
          </button>
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

    </div>
  );
}
