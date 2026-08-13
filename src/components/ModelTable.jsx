import React, { useMemo, useState } from 'react';
import { Check, CircleCheck, CircleX, Loader2, Search, Zap } from 'lucide-react';
import { formatContextLength, formatPrice } from '../lib/format';

const SORT_ACCESSORS = {
  name: item => (item.name || item.id).toLowerCase(),
  params: item => Number.parseFloat(item.paramSize) || 0,
  context: item => item.contextLength || 0,
  price: item => item.priceValue ?? -1,
  // Untested rows sort below every tested one in both directions; among tested rows the
  // fastest responder ranks highest, and failures rank below every success.
  test: item => (item.test ? (item.test.ok ? 1 / (1 + (item.test.latency_ms || 0)) : -1) : -2),
};

const formatLatency = ms => {
  if (!Number.isFinite(ms)) return '';
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
};

export function ModelTable({
  models,
  modelMeta,
  selectedModel,
  onSelect,
  enabledModelIds,
  onToggleEnabled,
  onSetEnabled,
  testResults = null,
  testing = false,
  testProgress = null,
  onTest,
  onSelectRespondents,
  onClearSelection,
}) {
  const [query, setQuery] = useState('');
  const [freeOnly, setFreeOnly] = useState(false);
  const [respondedOnly, setRespondedOnly] = useState(false);
  const [sortKey, setSortKey] = useState('context');
  const [sortDir, setSortDir] = useState('desc');

  const rows = useMemo(() => models.map(id => {
    const meta = modelMeta[id] || {};
    const pricing = meta.pricing;
    const promptCost = pricing ? Number(pricing.prompt ?? pricing.input ?? pricing.input_cost_per_token) : null;
    return {
      id,
      name: meta.name || null,
      paramSize: meta.param_size || null,
      contextLength: meta.context_length || null,
      pricing,
      priceValue: Number.isFinite(promptCost) ? promptCost : null,
      free: !!meta.free,
      test: testResults ? testResults[id] || null : null,
    };
  }), [models, modelMeta, testResults]);

  const respondents = useMemo(() => rows.filter(row => row.test?.ok).map(row => row.id), [rows]);

  const filtered = rows
    .filter(row => (freeOnly ? row.free : true))
    .filter(row => (respondedOnly ? !!row.test?.ok : true))
    .filter(row => {
      if (!query.trim()) return true;
      const needle = query.trim().toLowerCase();
      return row.id.toLowerCase().includes(needle) || (row.name || '').toLowerCase().includes(needle);
    });

  const sorted = filtered.slice().sort((a, b) => {
    const accessor = SORT_ACCESSORS[sortKey];
    const diff = accessor(a) - accessor(b);
    return sortDir === 'desc' ? -diff : diff;
  });

  const toggleSort = key => {
    if (sortKey === key) {
      setSortDir(current => (current === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  const sortIndicator = key => (sortKey === key ? (sortDir === 'desc' ? '↓' : '↑') : '');
  const isEnabled = id => !enabledModelIds || enabledModelIds.has(id);
  // Select/deselect act on whatever the search + free-only filters currently leave visible, so
  // typing "grok" then clicking Deselect all only hides the Grok rows, not the whole provider.
  const visibleIds = sorted.map(row => row.id);
  const testedCount = testResults ? Object.keys(testResults).length : 0;

  return (
    <div className="model-table-wrap">
      <div className="model-table-controls">
        <div className="model-table-search">
          <Search size={13} className="model-table-search-icon" />
          <input
            type="text"
            placeholder="Search models by name or id..."
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
        </div>
        <button
          type="button"
          className={`settings-free-toggle ${freeOnly ? 'active' : ''}`}
          onClick={() => setFreeOnly(current => !current)}
          aria-pressed={freeOnly}
        >
          Free only
        </button>
        {testedCount > 0 && (
          <button
            type="button"
            className={`settings-free-toggle ${respondedOnly ? 'active' : ''}`}
            onClick={() => setRespondedOnly(current => !current)}
            aria-pressed={respondedOnly}
          >
            Responded only
          </button>
        )}
        <button
          type="button"
          className="settings-free-toggle"
          onClick={() => onSetEnabled(visibleIds, true)}
          disabled={visibleIds.length === 0}
        >
          Select all
        </button>
        <button
          type="button"
          className="settings-free-toggle"
          onClick={() => onSetEnabled(visibleIds, false)}
          disabled={visibleIds.length === 0}
        >
          Deselect all
        </button>
      </div>

      <div className="model-table-test-bar">
        <button
          type="button"
          className="settings-test-button"
          onClick={() => onTest(visibleIds)}
          disabled={testing || visibleIds.length === 0}
        >
          {testing ? <Loader2 size={13} className="model-test-spin" /> : <Zap size={13} />}
          {testing && testProgress
            ? `Pinging ${testProgress.done}/${testProgress.total}...`
            : testing
              ? 'Pinging models...'
              : `Test ${visibleIds.length} model${visibleIds.length === 1 ? '' : 's'}`}
        </button>
        <button
          type="button"
          className="settings-free-toggle"
          onClick={onSelectRespondents}
          disabled={testing || respondents.length === 0}
        >
          Select all respondents ({respondents.length})
        </button>
        <button type="button" className="settings-free-toggle" onClick={onClearSelection} disabled={testing}>
          Clear all selection
        </button>
        {testing && testProgress && (
          <span className="model-table-test-summary">Pinging {testProgress.total} model{testProgress.total === 1 ? '' : 's'}, this can take a minute...</span>
        )}
        {!testing && testedCount > 0 && (
          <span className="model-table-test-summary">
            {respondents.length} of {testedCount} tested model{testedCount === 1 ? '' : 's'} responded
          </span>
        )}
      </div>

      {sorted.length === 0 ? (
        <p className="settings-empty-note">
          {respondedOnly && testedCount > 0 ? 'None of the tested models responded.' : 'No models match your search.'}
        </p>
      ) : (
        <div className="model-table-scroll">
          <table className="model-table">
            <thead>
              <tr>
                <th className="mt-col-show">Show</th>
                <th className="mt-col-name" onClick={() => toggleSort('name')}>Name {sortIndicator('name')}</th>
                <th className="mt-col-test" onClick={() => toggleSort('test')}>Test {sortIndicator('test')}</th>
                <th className="mt-col-params" onClick={() => toggleSort('params')}>Parameters {sortIndicator('params')}</th>
                <th className="mt-col-context" onClick={() => toggleSort('context')}>Context {sortIndicator('context')}</th>
                <th className="mt-col-price" onClick={() => toggleSort('price')}>Price {sortIndicator('price')}</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(row => {
                const active = row.id === selectedModel;
                const enabled = isEnabled(row.id);
                const priceLabel = formatPrice(row.pricing);
                const contextLabel = formatContextLength(row.contextLength);
                return (
                  <tr key={row.id} className={`${active ? 'active' : ''} ${enabled ? '' : 'disabled'}`}>
                    <td data-label="Show" className="mt-col-show">
                      <input
                        type="checkbox"
                        checked={enabled}
                        onChange={() => onToggleEnabled(row.id)}
                        aria-label={`Show ${row.name || row.id} in Locus`}
                      />
                    </td>
                    <td data-label="Name" className="mt-col-name">
                      <button type="button" className="mt-name-select" onClick={() => onSelect(row.id)} title={row.id}>
                        <span className="mt-name-text">
                          <span className="mt-name-main">{row.name || row.id}</span>
                          {row.name && <span className="mt-name-sub">{row.id}</span>}
                        </span>
                        {row.free && <span className="settings-model-chip-free">Free</span>}
                        {active && <Check size={13} className="mt-name-check" />}
                      </button>
                    </td>
                    <td data-label="Test" className="mt-col-test">
                      {row.test ? (
                        <span
                          className={`mt-test-badge ${row.test.ok ? 'ok' : 'failed'}`}
                          // The full provider error only fits in a tooltip; the badge keeps the row scannable.
                          title={row.test.ok ? `Replied: ${row.test.reply || '(empty)'}` : row.test.error || 'No response'}
                        >
                          {row.test.ok ? <CircleCheck size={13} /> : <CircleX size={13} />}
                          {row.test.ok ? formatLatency(row.test.latency_ms) || 'Responded' : 'Failed'}
                        </span>
                      ) : '—'}
                    </td>
                    <td data-label="Parameters" className="mt-col-params">{row.paramSize || '—'}</td>
                    <td data-label="Context" className="mt-col-context">{contextLabel || '—'}</td>
                    <td data-label="Price" className="mt-col-price">{priceLabel || (row.free ? 'Free' : '—')}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
