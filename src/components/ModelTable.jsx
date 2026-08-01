import React, { useMemo, useState } from 'react';
import { Check, Search } from 'lucide-react';
import { formatContextLength, formatPrice } from '../lib/format';

const SORT_ACCESSORS = {
  name: item => (item.name || item.id).toLowerCase(),
  params: item => Number.parseFloat(item.paramSize) || 0,
  context: item => item.contextLength || 0,
  price: item => item.priceValue ?? -1,
};

export function ModelTable({ models, modelMeta, selectedModel, onSelect, enabledModelIds, onToggleEnabled }) {
  const [query, setQuery] = useState('');
  const [freeOnly, setFreeOnly] = useState(false);
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
    };
  }), [models, modelMeta]);

  const filtered = rows
    .filter(row => (freeOnly ? row.free : true))
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
