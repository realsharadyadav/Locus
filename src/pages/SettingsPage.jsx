import React, { useEffect, useState } from 'react';
import {
  BookOpen,
  Check,
  Info,
  KeyRound,
  Loader2,
  LogOut,
  Radio,
  Sparkles,
} from 'lucide-react';
import { api } from '../api';
import { BRAND, writeStorage } from '../brand';
import { ModelTable } from '../components/ModelTable';
import { PROVIDER_LABELS, PROVIDER_META, PROVIDER_ORDER, readSavedAiPreference } from '../lib/appState';
import { displayTime } from '../utils';

// Mirrors MODEL_TEST_MAX_MODELS in backend/app/schemas.py — the most models one test request
// will accept for a single provider.
const MODEL_TEST_BATCH = 40;
// How many of those batches run at once. Each one already does 4 concurrent pings server-side
// (MODEL_TEST_CONCURRENCY in main.py), so this caps total concurrent outbound calls rather than
// firing every batch in the catalogue at a provider simultaneously.
const TEST_BATCH_CONCURRENCY = 3;

export const REASONING_MODE_META = [
  { id: 'light', label: 'Normal', icon: Radio, desc: 'Fast, everyday answers — default effort' },
  { id: 'thinking', label: 'High', icon: Sparkles, desc: 'Reads everything selected and reasons across it' },
  { id: 'deep_summary', label: 'Max', icon: BookOpen, desc: 'Exhaustive section-by-section document coverage' },
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
  const [enabledModels, setEnabledModels] = useState(null);
  const [savingModels, setSavingModels] = useState(false);
  // Which models actually answered a probe, keyed provider -> model. Saved server-side by the
  // test endpoint, so the tags are still there on the next visit.
  const [health, setHealth] = useState({});
  const [respondingOnly, setRespondingOnly] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testProgress, setTestProgress] = useState({ done: 0, total: 0 });
  // Auto-select on failure: a toggle saved as `auto_select_model`, plus the record of the
  // last automatic switch (`auto_select_last_switch`) so the page can explain it.
  const [autoSelect, setAutoSelect] = useState(false);
  const [lastSwitch, setLastSwitch] = useState(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.llmConfig(),
      api.preference('explore_ai').catch(() => ({ value: {} })),
      api.systemLimits().catch(() => null),
      api.preference('enabled_models').catch(() => ({ value: {} })),
      api.preference('model_health').catch(() => ({ value: {} })),
      api.preference('auto_select_model').catch(() => ({ value: {} })),
      api.preference('auto_select_last_switch').catch(() => ({ value: {} })),
    ])
      .then(([llmConfig, preference, systemLimits, enabledModelsPref, modelHealthPref, autoSelectPref, lastSwitchPref]) => {
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
        // Only providers the user has actually customized get an entry here — a provider with
        // no entry means "every one of its models is enabled" (models default to shown), so
        // most providers never need a stored list at all.
        const initialEnabledModels = {};
        for (const [provider, ids] of Object.entries(enabledModelsPref.value || {})) {
          if (Array.isArray(ids)) initialEnabledModels[provider] = new Set(ids);
        }
        setEnabledModels(initialEnabledModels);
        setHealth(modelHealthPref.value || {});
        const autoSelectValue = autoSelectPref.value;
        setAutoSelect(typeof autoSelectValue === 'boolean' ? autoSelectValue : Boolean(autoSelectValue?.enabled));
        const switchRecord = lastSwitchPref.value;
        setLastSwitch(
          switchRecord && typeof switchRecord === 'object' && switchRecord.model && !switchRecord.acknowledged
            ? switchRecord
            : null,
        );
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const isModelEnabled = (provider, modelId) => !enabledModels[provider] || enabledModels[provider].has(modelId);

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
  // on whatever the search/provider/responding filters currently leave visible, which can span
  // several providers at once now that the catalogue is one merged table.
  const setRowsEnabled = (rows, enabled) => {
    const idsByProvider = {};
    for (const { provider, id } of rows) {
      (idsByProvider[provider] ||= []).push(id);
    }
    setEnabledModels(current => {
      const next = { ...current };
      for (const [provider, ids] of Object.entries(idsByProvider)) {
        const baseSet = next[provider] ? new Set(next[provider]) : new Set(config?.providers?.[provider] || []);
        for (const modelId of ids) {
          if (enabled) baseSet.add(modelId);
          else baseSet.delete(modelId);
        }
        next[provider] = baseSet;
      }
      return next;
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

  // Rows can span multiple providers now, so one "Test" click fans out into one request per
  // provider represented in the selection and merges every result back into `health`.
  // One implementation for both "test whatever's visible" (ModelTable's own button, rows
  // already capped at 40) and "test every model in the catalogue" (the section-level button
  // below, which can hand this hundreds of rows). Splits into batches the backend will accept
  // (MODEL_TEST_MAX_MODELS in schemas.py) and runs a bounded number of batches at a time so a
  // full-catalogue test does not fire hundreds of requests at once.
  const testModels = async (rows) => {
    if (!rows.length) return;
    const idsByProvider = {};
    for (const { provider, id } of rows) {
      (idsByProvider[provider] ||= []).push(id);
    }
    const batches = [];
    for (const [provider, ids] of Object.entries(idsByProvider)) {
      for (let i = 0; i < ids.length; i += MODEL_TEST_BATCH) {
        batches.push({ provider, ids: ids.slice(i, i + MODEL_TEST_BATCH) });
      }
    }
    setTesting(true);
    setTestProgress({ done: 0, total: rows.length });
    let responded = 0;
    let total = 0;
    const failedProviders = new Set();
    try {
      let cursor = 0;
      const worker = async () => {
        while (cursor < batches.length) {
          const batch = batches[cursor++];
          try {
            const result = await api.testModels(batch.provider, batch.ids);
            setHealth(current => ({
              ...current,
              [batch.provider]: { ...(current[batch.provider] || {}), ...result.results },
            }));
            responded += Object.values(result.results).filter(item => item.ok).length;
            total += Object.keys(result.results).length;
          } catch {
            failedProviders.add(batch.provider);
          } finally {
            setTestProgress(current => ({ done: current.done + batch.ids.length, total: current.total }));
          }
        }
      };
      await Promise.all(Array.from({ length: Math.min(TEST_BATCH_CONCURRENCY, batches.length) }, worker));
      if (total) toast(`${responded} of ${total} model${total === 1 ? '' : 's'} responded`, responded ? 'success' : 'error');
      if (failedProviders.size) toast(`Could not test ${[...failedProviders].map(id => PROVIDER_LABELS[id] || id).join(', ')}`, 'error');
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

  if (loading || !draft || !enabledModels) {
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
  const allModelEntries = providers.flatMap(provider => providerModels(provider).map(id => ({ provider, id })));

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
    // A hand-typed id runs on whichever provider the Model dropdown above is currently set to —
    // this field overrides the id, not the provider.
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
      // The user just took the wheel — a prior automatic switch note is stale now.
      if (lastSwitch) {
        setLastSwitch(null);
        await api.updatePreference('auto_select_last_switch', { ...lastSwitch, acknowledged: true }).catch(() => {});
      }
      toast('Default provider, model, and mode saved', 'success');
    } catch (error) {
      toast(error.message || 'Could not save settings', 'error');
    } finally {
      setSaving(false);
    }
  };

  const toggleAutoSelect = async () => {
    const next = !autoSelect;
    setAutoSelect(next);
    try {
      await api.updatePreference('auto_select_model', { enabled: next });
      toast(next ? 'Auto-select on failure is on' : 'Auto-select on failure is off', 'success');
    } catch (error) {
      setAutoSelect(!next);
      toast(error.message || 'Could not save the auto-select setting', 'error');
    }
  };

  const dismissLastSwitch = async () => {
    const record = lastSwitch;
    setLastSwitch(null);
    try {
      await api.updatePreference('auto_select_last_switch', { ...record, acknowledged: true });
    } catch {
      // Hiding the note for this session is enough if the write fails.
    }
  };

  return (
    <div className="page settings-page">
      <div className="inner-title">
        <div>
          <span className="kicker">SETTINGS</span>
          <h1>Providers & models</h1>
          <p>{BRAND.name} answers with one model everywhere — Ask and Private Chats. Choose it here.</p>
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

        {lastSwitch && (
          <div className="settings-auto-switch-note">
            <span>
              Auto-switched to <strong>{PROVIDER_LABELS[lastSwitch.provider] || lastSwitch.provider} / {lastSwitch.model}</strong>
              {' '}— {lastSwitch.previous_model} wasn't responding{lastSwitch.timestamp ? ` at ${displayTime(lastSwitch.timestamp)}` : ''}. It is now the default; this note just explains the change.
            </span>
            <button type="button" onClick={dismissLastSwitch}>Got it</button>
          </div>
        )}

        <label className="settings-auto-select-toggle">
          <input type="checkbox" checked={autoSelect} onChange={toggleAutoSelect} />
          <span>
            <strong>Auto-select a working model if the default fails</strong>
            <small>If the saved default errors out during a request, Locus retries once with the fastest model that passed a health check and, if that works, keeps it as the new default. Untested or disabled models are never chosen.</small>
          </span>
        </label>

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
          <div className="settings-section-head-row">
            <h3>Available models</h3>
            <button
              type="button"
              className="settings-test-all-btn"
              onClick={() => testModels(allModelEntries)}
              disabled={testing || allModelEntries.length === 0}
              title={`Send one tiny prompt to every model across every provider (${allModelEntries.length} total) and tag the ones that answer. Runs in batches, so this takes a while.`}
            >
              {testing
                ? <><Loader2 size={13} className="spin" /> Testing {testProgress.done}/{testProgress.total}...</>
                : `Test all ${allModelEntries.length} models`}
            </button>
          </div>
          <p className="settings-hint-text">Housekeeping only: what stays in this catalogue. Unticking something never changes the default above.</p>
        </div>
        <ModelTable
          entries={allModelEntries}
          modelMeta={modelMeta}
          providerOptions={providers.map(provider => ({
            id: provider,
            label: PROVIDER_LABELS[provider] || provider,
            icon: PROVIDER_META[provider]?.icon,
            count: providerModels(provider).length,
            ready: providerReady(provider),
            envHint: PROVIDER_META[provider]?.envHint,
          }))}
          selectedProvider={draft.provider}
          selectedModel={draft.model}
          onSelect={(provider, model) => { setDraft(current => ({ ...current, provider, model })); setCustomModel(''); }}
          isEnabled={isModelEnabled}
          onToggleEnabled={toggleModelEnabled}
          onSetEnabled={setRowsEnabled}
          health={health}
        />
        <div className="settings-save-bar settings-save-bar-inline">
          <button type="button" className="btn-primary" onClick={saveEnabledModels} disabled={savingModels}>
            {savingModels ? 'Saving...' : 'Save enabled models'}
          </button>
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
        <h3>Default answer effort</h3>
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
