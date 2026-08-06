import React from 'react';
import { ChevronDown, RotateCcw } from 'lucide-react';
import { PROVIDER_ORDER } from '../lib/appState';

/* Run settings for Ticket Analysis.
 *
 * Organised as the questions a user actually asks, in the order the pipeline
 * answers them: what creates groups -> which rules -> how tickets are compared
 * -> how groups are discovered -> what AI may touch -> what comes out.
 *
 * A setting the current configuration cannot use is hidden rather than greyed
 * out, so the panel only ever shows controls that will change this run. */

export const GROUPING_MODES = [
  {
    value: 'rules_then_discovery',
    label: 'Rules first, then discovery',
    blurb: 'Taxonomy rules claim what they confidently match; everything left over is clustered.',
    effect: 'Most complete coverage. Best default.',
  },
  {
    value: 'rules_only',
    label: 'Rules only',
    blurb: 'Only taxonomy rules create groups. Anything unmatched is held for review instead of guessed at.',
    effect: 'Nothing invented — but unmatched tickets stay unsorted.',
  },
  {
    value: 'discovery_only',
    label: 'Discovery only',
    blurb: 'Ignore the rules entirely and let clustering find the shape of the data.',
    effect: 'Finds patterns your taxonomy has no rule for yet.',
  },
];

export const EMBEDDING_OPTIONS = [
  { value: 'tfidf', label: 'Keyword (TF-IDF)', blurb: 'Compares the words tickets share, weighted so boilerplate every ticket repeats counts for little.' },
  { value: 'neural_hash', label: 'Meaning (embeddings)', blurb: 'Compares meaning rather than exact words, so differently-worded tickets about the same thing still match.' },
  { value: 'hybrid', label: 'Both', blurb: 'Requires shared wording and similar meaning to agree before two tickets are called alike.' },
];

export const CLUSTERING_OPTIONS = [
  { value: 'taxonomy_semantic', label: 'Similarity chains', blurb: 'Links any two tickets above the similarity bar and keeps the chain going. Fast, forgiving, can produce a few large groups.', uses: ['similarity'] },
  { value: 'agglomerative', label: 'Merge closest first', blurb: 'Repeatedly merges the two most similar groups until they stop being similar, or until your target count is reached.', uses: ['similarity', 'targetClusters'] },
  { value: 'kmeans', label: 'Fixed number of groups', blurb: 'Splits tickets into exactly the number of groups you ask for. Use when you already know roughly how many themes exist.', uses: ['targetClusters'] },
  { value: 'hdbscan_lite', label: 'Dense groups + outliers', blurb: 'Only forms a group where tickets genuinely crowd together; the rest are reported as outliers instead of forced into a group.', uses: ['similarity', 'minSamples'] },
  { value: 'google_kwikbucks', label: 'Strict pairs (KwikBucks)', blurb: 'Ranks candidate pairs cheaply, then confirms only the strongest few. Precision over recall on messy long-tail wording.', uses: ['similarity'] },
];

export const TAXONOMY_SOURCES = [
  { value: 'default', label: 'Built-in ITSM rules', blurb: 'The shipped OKF/ITSM taxonomy.' },
  { value: 'custom', label: 'My own rules', blurb: 'Paste or edit a JSON rule set. An empty list is allowed — it means no rules at all.' },
];

export const PRESETS = [
  {
    key: 'balanced', label: 'Balanced', hint: 'Rules first, keyword similarity, AI naming on.',
    config: { groupingMode: 'rules_then_discovery', taxonomySource: 'default', embeddingMethod: 'tfidf', clusteringMethod: 'taxonomy_semantic', useLlmFallback: false, useLlmLabels: true, suggestTaxonomyRules: false },
  },
  {
    key: 'strict', label: 'Rules only', hint: 'No clustering, no AI. Fully deterministic.',
    config: { groupingMode: 'rules_only', taxonomySource: 'default', useLlmFallback: false, useLlmLabels: false, suggestTaxonomyRules: false },
  },
  {
    key: 'discover', label: 'Find new patterns', hint: 'Ignore rules, cluster on meaning, suggest new rules.',
    config: { groupingMode: 'discovery_only', embeddingMethod: 'hybrid', clusteringMethod: 'hdbscan_lite', useLlmFallback: true, useLlmLabels: true, suggestTaxonomyRules: true },
  },
  {
    key: 'ai', label: 'Maximum AI', hint: 'Rules first, then AI for unknowns, naming and rule suggestions.',
    config: { groupingMode: 'rules_then_discovery', taxonomySource: 'default', embeddingMethod: 'hybrid', clusteringMethod: 'agglomerative', useLlmFallback: true, useLlmLabels: true, suggestTaxonomyRules: true },
  },
];

function Field({ label, help, children, wide = false }) {
  return (
    <div className={`tset-field${wide ? ' wide' : ''}`}>
      <div className="tset-field-label">{label}</div>
      {children}
      {help && <div className="tset-field-help">{help}</div>}
    </div>
  );
}

function Choice({ options, value, onChange, name }) {
  return (
    <div className="tset-choices" role="radiogroup" aria-label={name}>
      {options.map(option => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={value === option.value}
          className={`tset-choice${value === option.value ? ' active' : ''}`}
          onClick={() => onChange(option.value)}
        >
          <span className="tset-choice-label">{option.label}</span>
          <span className="tset-choice-blurb">{option.blurb}</span>
          {option.effect && <span className="tset-choice-effect">{option.effect}</span>}
        </button>
      ))}
    </div>
  );
}

function Toggle({ label, help, checked, onChange, status }) {
  return (
    <div className="tset-toggle-row">
      <div className="tset-toggle-copy">
        <div className="tset-toggle-label">{label}</div>
        <div className="tset-toggle-help">{help}</div>
        {status && <div className="tset-toggle-status">{status}</div>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        className={`tset-switch${checked ? ' on' : ''}`}
        onClick={() => onChange(!checked)}
      />
    </div>
  );
}

function Section({ step, title, question, children }) {
  return (
    <section className="tset-section">
      <header className="tset-section-head">
        <span className="tset-step">{step}</span>
        <div>
          <h3>{title}</h3>
          <p>{question}</p>
        </div>
      </header>
      <div className="tset-section-body">{children}</div>
    </section>
  );
}

export default function TicketAnalysisSettings({
  config,
  setConfigValue,
  applyPreset,
  resetConfig,
  customTaxonomy,
  taxonomyRuleCount,
  onResetTaxonomyText,
  llmConfig,
  providerModelOptions,
  onProviderChange,
  llmSummaries,
}) {
  const usesRules = config.groupingMode !== 'discovery_only';
  const usesDiscovery = config.groupingMode !== 'rules_only';
  const method = CLUSTERING_OPTIONS.find(option => option.value === config.clusteringMethod) || CLUSTERING_OPTIONS[0];
  const uses = (param) => usesDiscovery && method.uses.includes(param);
  const aiOn = config.useLlmFallback || config.useLlmLabels || config.suggestTaxonomyRules;
  const providers = llmConfig?.provider_order?.length ? llmConfig.provider_order : PROVIDER_ORDER;
  const noRules = usesRules && config.taxonomySource === 'custom' && taxonomyRuleCount === 0 && !customTaxonomy.error;

  return (
    <div className="tset">
      <div className="tset-presets">
        <span className="tset-presets-label">Start from</span>
        {PRESETS.map(preset => (
          <button key={preset.key} type="button" className="tset-preset" title={preset.hint} onClick={() => applyPreset(preset)}>
            {preset.label}
          </button>
        ))}
        <button type="button" className="tset-preset ghost" onClick={resetConfig}>
          <RotateCcw size={12} /> Reset all
        </button>
      </div>

      <Section step="1" title="What creates the groups" question="Should rules, discovery, or both be allowed to form a problem group?">
        <Choice name="Grouping mode" options={GROUPING_MODES} value={config.groupingMode} onChange={value => setConfigValue('groupingMode', value)} />
      </Section>

      {usesRules && (
        <Section step="2" title="Which rules" question="Which taxonomy decides what a ticket is?">
          <Choice name="Taxonomy source" options={TAXONOMY_SOURCES} value={config.taxonomySource} onChange={value => setConfigValue('taxonomySource', value)} />
          {config.taxonomySource === 'custom' && (
            <div className="tset-editor">
              <div className="tset-editor-head">
                <span className={customTaxonomy.error ? 'bad' : noRules ? 'warn' : 'ok'}>
                  {customTaxonomy.error
                    || (noRules
                      ? 'No rules — every ticket will go to discovery instead'
                      : `${taxonomyRuleCount} rule${taxonomyRuleCount === 1 ? '' : 's'} ready`)}
                </span>
                <div className="tset-editor-actions">
                  <button type="button" onClick={onResetTaxonomyText}>Load built-in rules</button>
                  <button type="button" onClick={() => setConfigValue('taxonomyRulesText', '[]')}>Clear all</button>
                </div>
              </div>
              <textarea
                value={config.taxonomyRulesText}
                onChange={event => setConfigValue('taxonomyRulesText', event.target.value)}
                spellCheck="false"
                aria-label="Custom taxonomy rules as JSON"
              />
              <div className="tset-field-help">
                Each rule needs a <code>name</code> and at least one entry in <code>patterns</code>. Optional:{' '}
                <code>description</code>, <code>contexts</code>, <code>excludes</code>.
              </div>
            </div>
          )}
        </Section>
      )}

      {usesDiscovery && (
        <Section step={usesRules ? '3' : '2'} title="How tickets are compared" question="What makes two tickets count as the same problem?">
          <Choice name="Comparison method" options={EMBEDDING_OPTIONS} value={config.embeddingMethod} onChange={value => setConfigValue('embeddingMethod', value)} />
        </Section>
      )}

      {usesDiscovery && (
        <Section step={usesRules ? '4' : '3'} title="How groups are discovered" question="Once tickets are comparable, how should they be gathered into groups?">
          <Choice name="Clustering method" options={CLUSTERING_OPTIONS} value={config.clusteringMethod} onChange={value => setConfigValue('clusteringMethod', value)} />
          <div className="tset-params">
            {uses('similarity') && (
              <Field label={`How alike is "alike" — ${Number(config.similarityThreshold).toFixed(2)}`} help="Lower joins more tickets into fewer, broader groups. Higher splits into more, tighter ones.">
                <input
                  className="tset-range" type="range" min="0.1" max="0.9" step="0.01"
                  value={config.similarityThreshold}
                  onChange={event => setConfigValue('similarityThreshold', Number(event.target.value))}
                />
                <div className="tset-range-ends"><span>broader</span><span>tighter</span></div>
              </Field>
            )}
            {uses('targetClusters') && (
              <Field label="Number of groups to aim for" help={config.clusteringMethod === 'kmeans' ? 'Exact — this method always returns this many.' : 'A floor for merging; merging also stops when groups stop being similar.'}>
                <input className="tset-input" type="number" min="2" max="200" value={config.targetClusters}
                  onChange={event => setConfigValue('targetClusters', Number(event.target.value))} />
              </Field>
            )}
            {uses('minSamples') && (
              <Field label="Tickets needed to form a dense group" help="Higher means stricter: fewer groups, and more tickets reported as outliers.">
                <input className="tset-input" type="number" min="1" max="200" value={config.hdbscanMinSamples}
                  onChange={event => setConfigValue('hdbscanMinSamples', Number(event.target.value))} />
              </Field>
            )}
          </div>
        </Section>
      )}

      <Section step={usesDiscovery ? (usesRules ? '5' : '4') : '3'} title="What AI is allowed to do" question="Every AI step runs after grouping is already decided. None of them move a ticket.">
        <Toggle
          label="Group the leftovers it recognises"
          help="Clusters nothing could label are sent to the model, which may form a group from them."
          checked={config.useLlmFallback}
          onChange={value => setConfigValue('useLlmFallback', value)}
          status={llmSummaries.fallback}
        />
        <Toggle
          label="Rewrite group names and descriptions"
          help="Replaces generated labels with plainer language. Cannot merge, split or move anything."
          checked={config.useLlmLabels}
          onChange={value => setConfigValue('useLlmLabels', value)}
          status={llmSummaries.naming}
        />
        <Toggle
          label="Suggest new taxonomy rules"
          help="Proposes rules for recurring patterns nothing matched. Advisory only — never applied automatically."
          checked={config.suggestTaxonomyRules}
          onChange={value => setConfigValue('suggestTaxonomyRules', value)}
          status={llmSummaries.suggestions}
        />
        {aiOn && (
          <div className="tset-params">
            <Field label="Provider" help="Where the model runs.">
              <div className="tset-select-wrap">
                <select className="tset-select" value={config.llmProvider} onChange={event => onProviderChange(event.target.value)}>
                  {providers.map(provider => <option key={provider} value={provider}>{provider}</option>)}
                </select>
                <ChevronDown size={14} />
              </div>
            </Field>
            <Field label="Model" help="Small models often fail the naming format. Prefer a larger instruct model.">
              <div className="tset-select-wrap">
                <select className="tset-select" value={config.model || ''} onChange={event => setConfigValue('model', event.target.value)}>
                  <option value="">Backend default</option>
                  {providerModelOptions.map(model => <option key={model} value={model}>{model}</option>)}
                </select>
                <ChevronDown size={14} />
              </div>
            </Field>
          </div>
        )}
      </Section>

      <Section step={usesDiscovery ? (usesRules ? '6' : '5') : '4'} title="What comes out" question="Shape of the report this run produces.">
        <div className="tset-params">
          <Field label="Most groups to report" help="Extra small or low-confidence groups fold into one 'Other' bucket.">
            <input className="tset-input" type="number" min="1" max="100" value={config.maxGroups}
              onChange={event => setConfigValue('maxGroups', Number(event.target.value))} />
          </Field>
          <Field label="Smallest group worth reporting" help="Groups below this size are held back rather than shown as a pattern.">
            <input className="tset-input" type="number" min="1" max="1000" value={config.minGroupSize}
              onChange={event => setConfigValue('minGroupSize', Number(event.target.value))} />
          </Field>
          <Field label="Example tickets per group" help="Shown as evidence under each group.">
            <input className="tset-input" type="number" min="1" max="25" value={config.representativeCount}
              onChange={event => setConfigValue('representativeCount', Number(event.target.value))} />
          </Field>
        </div>
        <Toggle label="Record stage timings" help="Keeps the per-stage telemetry used by the pipeline view." checked={config.includeTelemetry} onChange={value => setConfigValue('includeTelemetry', value)} />
        <Toggle label="Include debug samples" help="Attaches raw samples to the run for troubleshooting." checked={config.includeDebugSamples} onChange={value => setConfigValue('includeDebugSamples', value)} />
      </Section>
    </div>
  );
}
