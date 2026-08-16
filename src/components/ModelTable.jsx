import React, { useMemo, useState } from 'react';
import { AlertTriangle, Check, Search } from 'lucide-react';
import { formatContextLength, formatPrice } from '../lib/format';

const SORT_ACCESSORS = {
  name: item => (item.name || item.id).toLowerCase(),
  provider: item => item.providerLabel.toLowerCase(),
  params: item => Number.parseFloat(item.paramSize) || 0,
  context: item => item.contextLength || 0,
  price: item => item.priceValue ?? -1,
};

/* An untested model shows a dash, not a cross: never asked is not the same as asked and
   silent, and only the second one is a reason to avoid picking it. */
function statusCell(result) {
  if (!result) return <span className="mt-status untested">—</span>;
  if (result.ok) {
    return (
      <span className="mt-status ok" title={`Answered in ${result.latency_ms} ms`}>
        Responding{result.latency_ms ? ` · ${result.latency_ms} ms` : ''}
      </span>
    );
  }
  return <span className="mt-status failed" title={result.error || 'No answer'}>No answer</span>;
}

// One catalogue across every provider — the provider is a column and a filter, not a separate
// screen you navigate into first. A model is picked the same way regardless of which provider
// happens to offer it; testing and enabling work the same way too, just across a wider set of
// rows at once instead of one provider's worth.
export function ModelTable({
  entries,
  modelMeta,
  providerOptions,
  selectedProvider,
  selectedModel,
  onSelect,
  isEnabled,
  onToggleEnabled,
  onSetEnabled,
  health = {},
}) {
  const [query, setQuery] = useState('');
  const [activeProviders, setActiveProviders] = useState(null); // null = every provider shown
  const [respondingOnly, setRespondingOnly] = useState(false);
  const [sortKey, setSortKey] = useState('context');
  const [sortDir, setSortDir] = useState('desc');

  const rows = useMemo(() => {
    const labelById = Object.fromEntries(providerOptions.map(p => [p.id, p.label]));
    return entries.map(({ provider, id }) => {
      const meta = modelMeta[id] || {};
      const pricing = meta.pricing;
      const promptCost = pricing ? Number(pricing.prompt ?? pricing.input ?? pricing.input_cost_per_token) : null;
      return {
        provider,
        providerLabel: labelById[provider] || provider,
        id,
        name: meta.name || null,
        paramSize: meta.param_size || null,
        contextLength: meta.context_length || null,
        pricing,
        priceValue: Number.isFinite(promptCost) ? promptCost : null,
        free: !!meta.free,
      };
    });
  }, [entries, modelMeta, providerOptions]);

  const toggleProviderFilter = providerId => {
    setActiveProviders(current => {
      const base = current || providerOptions.map(p => p.id);
      const next = new Set(base);
      if (next.has(providerId)) next.delete(providerId);
      else next.add(providerId);
      return next;
    });
  };

  const filtered = rows
    .filter(row => (activeProviders ? activeProviders.has(row.provider) : true))
    .filter(row => (respondingOnly ? health[row.provider]?.[row.id]?.ok : true))
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
  // Select/deselect/test act on whatever the search + provider + responding filters currently
  // leave visible, so narrowing to one provider and clicking Deselect all only hides that
  // provider's rows, not the whole catalogue.
  const visibleRows = sorted.map(row => ({ provider: row.provider, id: row.id }));

  return (
    <div className="model-table-wrap">
      <div className="model-table-provider-filter">
        {providerOptions.map(option => {
          const active = !activeProviders || activeProviders.has(option.id);
          return (
            <button
              type="button"
              key={option.id}
              className={`model-table-provider-chip ${active ? 'active' : ''} ${option.ready ? '' : 'idle'}`}
              onClick={() => toggleProviderFilter(option.id)}
              aria-pressed={active}
              title={option.ready ? `${option.count} model${option.count === 1 ? '' : 's'}` : option.envHint}
            >
              <span className="model-table-provider-chip-icon">{option.icon}</span>
              <span>{option.label}</span>
              {option.ready ? (
                <span className="model-table-provider-chip-count">{option.count}</span>
              ) : (
                <AlertTriangle size={11} />
              )}
            </button>
          );
        })}
      </div>
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
          className={`settings-free-toggle ${respondingOnly ? 'active' : ''}`}
          onClick={() => setRespondingOnly(current => !current)}
          aria-pressed={respondingOnly}
          title="Only models that answered the last test"
        >
          Responding only
        </button>
        <button
          type="button"
          className="settings-free-toggle"
          onClick={() => onSetEnabled(visibleRows, true)}
          disabled={visibleRows.length === 0}
        >
          Select all
        </button>
        <button
          type="button"
          className="settings-free-toggle"
          onClick={() => onSetEnabled(visibleRows, false)}
          disabled={visibleRows.length === 0}
        >
          Deselect all
        </button>
      </div>

      {sorted.length === 0 ? (
        <p className="settings-empty-note">No models match your search.</p>
      ) : (
        <div className="model-table-scroll">
          <table className="model-table">
            <thead>
              <tr>
                <th className="mt-col-show">Show</th>
                <th className="mt-col-name" onClick={() => toggleSort('name')}>Name {sortIndicator('name')}</th>
                <th className="mt-col-provider" onClick={() => toggleSort('provider')}>Provider {sortIndicator('provider')}</th>
                <th className="mt-col-params" onClick={() => toggleSort('params')}>Parameters {sortIndicator('params')}</th>
                <th className="mt-col-context" onClick={() => toggleSort('context')}>Context {sortIndicator('context')}</th>
                <th className="mt-col-price" onClick={() => toggleSort('price')}>Price {sortIndicator('price')}</th>
                <th className="mt-col-status">Test</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(row => {
                const active = row.id === selectedModel && row.provider === selectedProvider;
                const enabled = isEnabled(row.provider, row.id);
                const priceLabel = formatPrice(row.pricing);
                const contextLabel = formatContextLength(row.contextLength);
                return (
                  <tr key={`${row.provider}::${row.id}`} className={`${active ? 'active' : ''} ${enabled ? '' : 'disabled'}`}>
                    <td data-label="Show" className="mt-col-show">
                      <input
                        type="checkbox"
                        checked={enabled}
                        onChange={() => onToggleEnabled(row.provider, row.id)}
                        aria-label={`Show ${row.name || row.id} in Locus`}
                      />
                    </td>
                    <td data-label="Name" className="mt-col-name">
                      <button type="button" className="mt-name-select" onClick={() => onSelect(row.provider, row.id)} title={row.id}>
                        <span className="mt-name-text">
                          <span className="mt-name-main">{row.name || row.id}</span>
                          {row.name && <span className="mt-name-sub">{row.id}</span>}
                        </span>
                        {row.free && <span className="settings-model-chip-free">Free</span>}
                        {active && <Check size={13} className="mt-name-check" />}
                      </button>
                    </td>
                    <td data-label="Provider" className="mt-col-provider">{row.providerLabel}</td>
                    <td data-label="Parameters" className="mt-col-params">{row.paramSize || '—'}</td>
                    <td data-label="Context" className="mt-col-context">{contextLabel || '—'}</td>
                    <td data-label="Price" className="mt-col-price">{priceLabel || (row.free ? 'Free' : '—')}</td>
                    <td data-label="Test" className="mt-col-status">{statusCell(health[row.provider]?.[row.id])}</td>
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
