import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, AlertCircle, Brain, CheckCircle, ChevronDown,
  Clock, Database, Download, FileText, GitBranch, History, Loader2,
  Menu, Network, Play, RefreshCw, Trash2,
} from 'lucide-react';
import { api } from '../api';
import { DEFAULT_PROVIDER_MODELS } from '../lib/appState';
import TicketAnalysisSettings, { CLUSTERING_OPTIONS, EMBEDDING_OPTIONS, GROUPING_MODES } from './TicketAnalysisSettings';
import './TicketAnalysisPage.css';

const TICKET_EXTENSIONS = ['.csv', '.tsv', '.xlsx', '.xlsm', '.json', '.txt', '.md'];

const DEFAULT_CONFIG = {
  groupingMode: 'rules_then_discovery',
  taxonomySource: 'default',
  taxonomyRulesText: '',
  embeddingMethod: 'tfidf',
  clusteringMethod: 'taxonomy_semantic',
  similarityThreshold: 0.45,
  targetClusters: 12,
  hdbscanMinSamples: 3,
  maxGroups: 20,
  minGroupSize: 3,
  representativeCount: 3,
  useLlmFallback: false,
  useLlmLabels: true,
  suggestTaxonomyRules: false,
  llmProvider: 'groq',
  model: '',
  includeTelemetry: true,
  includeDebugSamples: true,
};

// Runs saved before the settings rewrite carry the old strategy/taxonomyMode
// keys. Reopening one has to land on the equivalent new configuration rather
// than silently resetting the user's run to defaults.
const LEGACY_STRATEGY_TO_MODE = {
  taxonomy_then_cluster: 'rules_then_discovery',
  okf_first: 'rules_then_discovery',
  taxonomy_semantic: 'rules_then_discovery',
  taxonomy_only: 'rules_only',
  okf_only: 'rules_only',
  cluster_only: 'discovery_only',
  cluster_first: 'discovery_only',
};

function normalizeConfig(saved = {}) {
  const merged = { ...DEFAULT_CONFIG, ...saved };
  if (!saved.groupingMode) {
    merged.groupingMode = saved.pauseOkfTaxonomy
      ? 'discovery_only'
      : LEGACY_STRATEGY_TO_MODE[saved.problemGroupStrategy] || DEFAULT_CONFIG.groupingMode;
  }
  if (!saved.taxonomySource) {
    merged.taxonomySource = saved.taxonomyMode === 'custom' ? 'custom' : 'default';
  }
  delete merged.problemGroupStrategy;
  delete merged.taxonomyMode;
  delete merged.pauseOkfTaxonomy;
  return merged;
}

const STRATEGY_LABELS = Object.fromEntries(GROUPING_MODES.map(mode => [mode.value, mode.label]));

const BACKEND_STRATEGY = {
  rules_then_discovery: 'taxonomy_then_cluster',
  rules_only: 'taxonomy_only',
  discovery_only: 'cluster_only',
};

const PIPELINE_SKELETON = [
  ['select_file', 'Select File', 'The selected export becomes the only input for this run.'],
  ['parse_clean', 'Parse & Clean', 'Rows are parsed, empty records removed, and duplicates collapsed.'],
  ['field_mapping', 'Field Mapping', 'Ticket id, title, description, category, subcategory, and metadata fields are detected.'],
  ['metadata_grouping', 'Metadata Grouping', 'Structured metadata can create deterministic groups.'],
  ['okf_taxonomy', 'OKF Taxonomy Match', 'Known OKF/ITSM rules claim high-confidence tickets.'],
  ['unmatched', 'Unmatched Tickets', 'Unclaimed tickets move into discovery.'],
  ['vectorization', 'Vectorization / Embedding', 'Fresh vectors are generated from the selected file and config.'],
  ['semantic_clustering', 'Semantic Clustering', 'Unmatched vectors are clustered by the selected method.'],
  ['llm', 'LLM Fallback / LLM Naming', 'LLM can classify unknowns or improve labels when enabled.'],
  ['consolidation', 'Consolidation', 'Duplicate groups are merged and ranked.'],
  ['final_groups', 'Final Problem Groups', 'Final groups expose source, confidence, and evidence.'],
  ['taxonomy_suggestions', 'Taxonomy Suggestions', 'Reusable rules are suggested from durable unmatched patterns.'],
];

function formatFileSize(bytes = 0) {
  const size = Number(bytes) || 0;
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(size >= 10 * 1024 * 1024 ? 0 : 1)} MB`;
  if (size >= 1024) return `${(size / 1024).toFixed(size >= 10 * 1024 ? 0 : 1)} KB`;
  return `${size} B`;
}

function fileMetaLine(file) {
  if (!file) return 'No file metadata';
  return `${formatFileSize(file.size)} \u00B7 ${Number(file.embedding_chunks || 0)} indexed chunks`;
}

function pct(value, total) {
  if (!total) return '0%';
  return `${((Number(value || 0) / total) * 100).toFixed(1)}%`;
}

function optionLabel(options, value) {
  return options.find(o => o.value === value)?.label || value || 'n/a';
}

function buildFallbackTrace(result, config, selectedFile) {
  const manifest = result?.manifest || {};
  return {
    run_id: result?.analysisOptions?.runId || result?.historyId || 'current',
    created_at: new Date().toISOString(),
    input: {
      file_name: selectedFile?.name || 'Unknown file',
      file_hash: result?.analysisOptions?.fileHash || 'pending',
      total_rows: manifest.totalRows || 0,
      valid_tickets: manifest.validTickets || 0,
      detected_fields: result?.analysisOptions?.detectedFields || {},
    },
    config: result?.analysisOptions || config,
    fingerprint: `${selectedFile?.name || 'file'}:${config.embeddingMethod}:${config.clusteringMethod}:${config.similarityThreshold}:${config.problemGroupStrategy}`,
    vectorization: { fresh: true, cache_key: null, message: 'Fresh vectors generated for this run.' },
    stages: PIPELINE_SKELETON.map(([key, label, explanation], index) => ({
      key, label, explanation,
      status: result ? 'completed' : 'pending',
      input_count: index === 0 ? 1 : manifest.validTickets || 0,
      output_count: key === 'final_groups' ? manifest.problemGroups || 0 : manifest.validTickets || 0,
      duration_ms: result?.pipeline?.[index]?.elapsedMs || 0,
      details: result?.pipeline?.[index]?.meta || {},
    })),
    coverage: { taxonomy_matched: 0, clustered: manifest.validTickets || 0, llm_assisted: 0, unresolved: 0 },
    problem_groups: result?.groups || [],
    taxonomy_suggestions: result?.taxonomySuggestions || [],
  };
}

function historyTrace(item) {
  return item?.config?.pipelineTrace || item?.config?.pipeline_trace || null;
}

function metricDelta(current, previous, key) {
  const diff = Number(current?.[key] || 0) - Number(previous?.[key] || 0);
  return `${diff > 0 ? '+' : ''}${diff}`;
}

function shortHash(value = '') {
  return value ? `${String(value).slice(0, 8)}...` : 'pending';
}

function editableTaxonomyFromOkf(okfTaxonomy) {
  return JSON.stringify((okfTaxonomy?.rules || []).map(rule => ({
    name: rule.name,
    description: rule.description,
    patterns: rule.includes || [],
    contexts: rule.contexts || [],
    excludes: rule.excludes || [],
  })), null, 2);
}

const STAGE_KEYS = ['intake', 'taxonomy', 'discovery', 'llm', 'consolidation', 'output'];

// The backend emits fine-grained pipeline stages; the rail shows six. Anything
// unmapped is ignored rather than guessed at, so the rail never lights a stage
// the run did not actually reach.
const BACKEND_STAGE_TO_RAIL = {
  ingest: 'intake', clean: 'intake', embed: 'intake',
  strategy: 'taxonomy', taxonomy: 'taxonomy',
  cluster: 'discovery',
  gathering: 'llm', llm_labels: 'llm', llm_fallback: 'llm', llm_fallback_result: 'llm', llm_labels_result: 'llm', taxonomy_suggestions: 'llm',
  consolidate: 'consolidation',
  complete: 'output',
};

function TicketAnalysisPage({ files, openMenu }) {
  const [selectedFileId, setSelectedFileId] = useState(null);
  const [config, setConfig] = useState(DEFAULT_CONFIG);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [runStatus, setRunStatus] = useState({ type: 'idle', message: 'Select a ticket file to start analysis.' });
  const [activeStepKey, setActiveStepKey] = useState('select_file');
  const [liveStage, setLiveStage] = useState(null);
  const [doneStages, setDoneStages] = useState(new Set());
  const [stageDetail, setStageDetail] = useState({});
  const [selectedStepKey, setSelectedStepKey] = useState('select_file');
  const [expandedGroups, setExpandedGroups] = useState(new Set());
  const [expandedStages, setExpandedStages] = useState(new Set());
  const [expandedTech, setExpandedTech] = useState(new Set());
  const [expandedTraces, setExpandedTraces] = useState(new Set());
  const [controlsOpen, setControlsOpen] = useState(true);
  const [activeTab, setActiveTab] = useState('groups');
  const [savedRunId, setSavedRunId] = useState(null);
  const [compareLeftId, setCompareLeftId] = useState('');
  const [compareRightId, setCompareRightId] = useState('');
  const [historyPanelOpen, setHistoryPanelOpen] = useState(false);
  const [llmConfig, setLlmConfig] = useState(null);
  const [okfTaxonomy, setOkfTaxonomy] = useState(null);
  const [selectedOkfIndex, setSelectedOkfIndex] = useState(0);
  const [availableFiles, setAvailableFiles] = useState(files || []);
  const [filesLoading, setFilesLoading] = useState(false);
  const [consoleLines, setConsoleLines] = useState([]);
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const runStartRef = useRef(0);
  const consoleBodyRef = useRef(null);

  const ticketFiles = useMemo(() => availableFiles.filter(f => TICKET_EXTENSIONS.includes(`.${f.name.split('.').pop().toLowerCase()}`)), [availableFiles]);
  const selectedFile = ticketFiles.find(f => f.id === selectedFileId);
  const trace = result?.pipeline_trace || buildFallbackTrace(result, config, selectedFile);
  const stages = trace?.stages?.length ? trace.stages : buildFallbackTrace(result, config, selectedFile).stages;
  const groups = trace?.problem_groups?.length ? trace.problem_groups : result?.groups || [];
  const manifest = result?.manifest || {};
  const coverage = trace?.coverage || {};
  const detectedFields = trace?.input?.detected_fields || {};
  const isTaxonomyOnly = config.groupingMode === 'rules_only';
  const isClusterOnly = config.groupingMode === 'discovery_only';
  const compareLeft = history.find(item => String(item.id) === String(compareLeftId));
  const compareRight = history.find(item => String(item.id) === String(compareRightId));
  const validTickets = trace.input?.valid_tickets || manifest.validTickets || 0;
  const sourceBreakdown = useMemo(() => groups.reduce((acc, g) => { acc[g.source || 'Unknown'] = (acc[g.source || 'Unknown'] || 0) + Number(g.incidentCount || g.count || 0); return acc; }, {}), [groups]);
  const providerModelOptions = useMemo(() => { const bm = llmConfig?.providers?.[config.llmProvider] || []; const pm = config.llmProvider === llmConfig?.provider ? (llmConfig?.presets || []) : []; return [...new Set([config.model, ...bm, ...pm].filter(Boolean))]; }, [config.llmProvider, config.model, llmConfig]);
  const llmStage = stages.find(s => s.key === 'llm');
  const llmHitCount = Number(coverage.llm_assisted || llmStage?.output_count || 0);
  const llmLabelCount = Number(llmStage?.details?.groups_renamed || 0);
  const llmLabelStatus = llmStage?.details?.naming_status || trace.config?.llmLabelStatus || 'disabled';
  const llmLabelSummary = String(llmLabelStatus).startsWith('failed')
    ? `naming call failed (${llmLabelStatus.replace('failed: ', '')}) — deterministic labels kept`
    : llmLabelStatus === 'disabled' ? 'not run for this analysis'
    : llmLabelStatus === 'no_usable_response' ? `${config.model || 'the selected model'} did not return usable labels — try a stronger model`
    : `${llmLabelCount} of ${groups.length} group labels rewritten by LLM`;
  const llmSuggestionCount = Number(llmStage?.details?.taxonomy_suggestions_generated || trace.taxonomy_suggestions?.length || 0);
  const llmSummaries = {
    fallback: `${llmHitCount} leftover cluster(s) grouped this run`,
    naming: llmLabelSummary,
    suggestions: `${llmSuggestionCount} rule suggestion(s) this run`,
  };
  const okfMatchedCount = isClusterOnly ? 0 : Number(coverage.taxonomy_matched || 0);
  const clusterInputCount = isTaxonomyOnly ? 0 : isClusterOnly ? validTickets : Math.max(0, validTickets - okfMatchedCount);
  const clusterOutputCount = Number(coverage.clustered || 0);
  const semanticGroupCount = groups.filter(g => String(g.source || '').toLowerCase().includes('semantic')).length;
  const okfRules = okfTaxonomy?.rules || [];
  // An empty rule list is a legitimate configuration meaning "no rules at all",
  // so only malformed JSON or an unusable rule is an error here.
  const customTaxonomy = useMemo(() => {
    if (config.taxonomySource !== 'custom') return { rules: null, error: '' };
    try {
      const parsed = JSON.parse(config.taxonomyRulesText || '[]');
      if (!Array.isArray(parsed)) return { rules: null, error: 'Rules must be a JSON array.' };
      const invalid = parsed.findIndex(rule => !rule || !rule.name || !(rule.patterns || rule.includes || rule.signals)?.length);
      if (invalid >= 0) return { rules: null, error: `Rule #${invalid + 1} needs a name and at least one pattern.` };
      return { rules: parsed, error: '' };
    } catch (err) {
      return { rules: null, error: 'That is not valid JSON.' };
    }
  }, [config.taxonomySource, config.taxonomyRulesText]);
  const selectedOkfRule = okfRules[selectedOkfIndex] || okfRules[0];
  const rulesCount = isClusterOnly ? 0 : config.taxonomySource === 'custom' ? (customTaxonomy.rules?.length || 0) : (okfTaxonomy?.ruleCount || 0);

  const toggleSet = (setState, key) => setState(prev => { const n = new Set(prev); if (n.has(key)) n.delete(key); else n.add(key); return n; });
  const toggleGroup = (index) => toggleSet(setExpandedGroups, index);
  const toggleStage = (key) => toggleSet(setExpandedStages, key);
  const toggleTech = (key) => toggleSet(setExpandedTech, key);
  const toggleTrace = (index) => toggleSet(setExpandedTraces, index);
  const setAllStages = (open) => setExpandedStages(new Set(open ? STAGE_KEYS : []));
  const setAllGroups = (open) => setExpandedGroups(new Set(open ? groups.map((_, i) => i) : []));

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try { setHistory(await api.ticketAnalysisHistory()); } catch (err) { console.error(err); }
    finally { setHistoryLoading(false); }
  }, []);

  const refreshTicketFiles = useCallback(async () => {
    setFilesLoading(true);
    try {
      const nextFiles = await api.files();
      setAvailableFiles(nextFiles);
      const nextTicketFiles = nextFiles.filter(f => TICKET_EXTENSIONS.includes(`.${f.name.split('.').pop().toLowerCase()}`));
      if (selectedFileId && !nextTicketFiles.some(file => file.id === selectedFileId)) {
        setSelectedFileId(null);
      }
      setRunStatus(prev => prev.type === 'idle' ? prev : { type: 'success', message: `Loaded ${nextTicketFiles.length} ticket file${nextTicketFiles.length === 1 ? '' : 's'}.` });
    } catch (err) {
      setRunStatus({ type: 'error', message: err.message || 'Could not refresh files.' });
    } finally {
      setFilesLoading(false);
    }
  }, [selectedFileId]);

  useEffect(() => { setAvailableFiles(files || []); }, [files]);
  useEffect(() => { loadHistory(); }, [loadHistory]);
  useEffect(() => { refreshTicketFiles(); }, []);
  useEffect(() => {
    api.llmConfig().then(data => {
      setLlmConfig(data);
      setConfig(prev => {
        const provider = prev.llmProvider || data.provider || 'groq';
        const opts = data.providers?.[provider] || [];
        return { ...prev, llmProvider: provider, model: prev.model || opts[0] || (provider === data.provider ? data.model : DEFAULT_PROVIDER_MODELS[provider]) || '' };
      });
    }).catch(() => {});
  }, []);
  useEffect(() => {
    api.ticketAnalysisOkfTaxonomy().then(data => {
      setOkfTaxonomy(data);
      setConfig(prev => prev.taxonomyRulesText ? prev : { ...prev, taxonomyRulesText: editableTaxonomyFromOkf(data) });
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!analyzing) return;
    const clockTimer = setInterval(() => setElapsedMs(Date.now() - runStartRef.current), 100);
    return () => clearInterval(clockTimer);
  }, [analyzing]);

  useEffect(() => {
    if (consoleBodyRef.current) consoleBodyRef.current.scrollTop = consoleBodyRef.current.scrollHeight;
  }, [consoleLines]);

  const pipelineProgressPct = analyzing
    ? Math.min(100, (PIPELINE_SKELETON.findIndex(s => s[0] === activeStepKey) / (PIPELINE_SKELETON.length - 1)) * 100)
    : result ? 100 : 0;

  const setConfigValue = (key, value) => setConfig(prev => ({ ...prev, [key]: value }));
  const resetRun = () => { setResult(null); setSavedRunId(null); setActiveStepKey('select_file'); setSelectedStepKey('select_file'); setRunStatus({ type: 'idle', message: 'Run reset.' }); setConsoleLines([]); setConsoleOpen(false); };

  const handleAnalyze = async () => {
    if (!selectedFileId) { setRunStatus({ type: 'error', message: 'Select a ticket file.' }); return; }
    if (config.taxonomySource === 'custom' && customTaxonomy.error) { setRunStatus({ type: 'error', message: customTaxonomy.error }); return; }
    setAnalyzing(true); setResult(null); setSavedRunId(null);
    runStartRef.current = Date.now();
    setElapsedMs(0);
    setConsoleOpen(true);
    setConsoleLines([{ t: 0, text: `Starting pipeline on ${selectedFile?.name || 'selected file'}` }]);
    setLiveStage(null); setDoneStages(new Set()); setStageDetail({});
    setActiveStepKey(PIPELINE_SKELETON[0][0]); setSelectedStepKey(PIPELINE_SKELETON[0][0]);
    setRunStatus({ type: 'running', message: 'Running pipeline. Fresh vectors will be generated.' });

    // Each stage event is the backend telling us what it is doing right now, so
    // the rail advances on real work rather than on a timer.
    const onStreamEvent = (event) => {
      if (event.type !== 'stage') return;
      const rail = BACKEND_STAGE_TO_RAIL[event.stage];
      setConsoleLines(prev => [...prev, { t: Date.now() - runStartRef.current, text: `${event.stage} — ${event.detail}` }]);
      if (!rail) return;
      setLiveStage(prev => {
        if (prev && prev !== rail) setDoneStages(done => new Set(done).add(prev));
        return rail;
      });
      setStageDetail(prev => ({ ...prev, [rail]: event.detail }));
      if (PIPELINE_SKELETON.some(([key]) => key === event.stage)) {
        setActiveStepKey(event.stage); setSelectedStepKey(event.stage);
      }
    };

    try {
      const data = await api.ticketAnalysisStream(selectedFileId, config.maxGroups || undefined, config.minGroupSize || undefined, config.useLlmFallback, config.model || undefined, {
        embeddingMethod: config.embeddingMethod,
        clusteringMethod: config.clusteringMethod,
        problemGroupStrategy: BACKEND_STRATEGY[config.groupingMode],
        similarityThreshold: Number(config.similarityThreshold) || undefined,
        targetClusters: Number(config.targetClusters) || undefined,
        hdbscanMinSamples: Number(config.hdbscanMinSamples) || undefined,
        representativeCount: Number(config.representativeCount) || undefined,
        includeTelemetry: config.includeTelemetry,
        includeDebugSamples: config.includeDebugSamples,
        useLlmLabels: config.useLlmLabels,
        suggestTaxonomyRules: config.suggestTaxonomyRules,
        llmProvider: config.llmProvider,
        // Discovery-only means "ignore the rule set" — the backend pause flag says
        // exactly that, and keeps a custom rule set from leaking into the run.
        pauseOkfTaxonomy: isClusterOnly,
        taxonomyRules: !isClusterOnly && config.taxonomySource === 'custom' ? customTaxonomy.rules : undefined,
      }, onStreamEvent);
      setLiveStage(null); setDoneStages(new Set(STAGE_KEYS));
      setResult(data); setActiveStepKey('final_groups'); setSelectedStepKey('final_groups');
      setRunStatus({ type: 'success', message: 'Analysis complete. Saving snapshot.' });
      setConsoleLines(prev => [...prev, { t: Date.now() - runStartRef.current, text: `Done — ${data.manifest?.problemGroups ?? (data.groups || []).length} problem group(s) from ${data.manifest?.validTickets ?? '?'} valid tickets.` }]);
      await saveSnapshot(data, 'auto');
    } catch (err) {
      setLiveStage(null);
      setRunStatus({ type: 'error', message: err.message || 'Analysis failed' });
      setConsoleLines(prev => [...prev, { t: Date.now() - runStartRef.current, text: `Error — ${err.message || 'Analysis failed'}` }]);
    }
    finally { setAnalyzing(false); }
  };

  const saveSnapshot = async (data = result, mode = 'manual') => {
    if (!data) return null;
    const file = ticketFiles.find(item => item.id === selectedFileId);
    try {
      const saved = await api.saveTicketAnalysis({
        fileId: selectedFileId, fileName: file?.name || data.pipeline_trace?.input?.file_name || 'Unknown',
        manifest: data.manifest || {}, groups: data.groups || [],
        taxonomySuggestions: data.taxonomySuggestions || data.pipeline_trace?.taxonomy_suggestions || [],
        config: { runConfig: config, pipelineTrace: data.pipeline_trace, pipeline: data.pipeline || [], analysisOptions: data.analysisOptions || {}, savedMode: mode, summary: { topGroups: (data.groups || []).slice(0, 3).map(g => g.groupName || g.name), finalGroupCount: data.manifest?.problemGroups || (data.groups || []).length, durationMs: data.pipeline_trace?.duration_ms || 0 } },
      });
      setSavedRunId(saved.id); setRunStatus({ type: 'success', message: `Run #${saved.id} saved.` });
      await loadHistory(); return saved;
    } catch (err) { setRunStatus({ type: 'error', message: err.message || 'Failed to save' }); return null; }
  };

  const loadHistoricalResult = async (id) => {
    try {
      const item = await api.ticketAnalysisHistoryDetail(id);
      const sc = item.config || {};
      setResult({ manifest: item.manifest, groups: item.groups || [], taxonomySuggestions: item.taxonomy_suggestions || [], pipeline_trace: sc.pipelineTrace || sc.pipeline_trace, pipeline: sc.pipeline || [], analysisOptions: sc.analysisOptions || sc.runConfig || {}, historyId: item.id });
      setSelectedFileId(item.file_id); setConfig(normalizeConfig(sc.runConfig || {})); setSavedRunId(item.id);
      setActiveTab('groups'); setSelectedStepKey('final_groups');
      setRunStatus({ type: 'success', message: `Reopened run #${item.id}.` });
    } catch (err) { setRunStatus({ type: 'error', message: err.message || 'Failed to reopen' }); }
  };

  const deleteHistory = async (id) => { try { await api.deleteTicketAnalysisHistory(id); setRunStatus({ type: 'success', message: `Deleted #${id}.` }); await loadHistory(); } catch (err) { setRunStatus({ type: 'error', message: err.message }); } };
  const exportJson = (item = null) => { const p = item || { manifest, groups, pipeline_trace: trace, config }; const b = new Blob([JSON.stringify(p, null, 2)], { type: 'application/json' }); const u = URL.createObjectURL(b); const a = document.createElement('a'); a.href = u; a.download = `patterns-run-${item?.id || trace?.run_id || Date.now()}.json`; a.click(); URL.revokeObjectURL(u); };
  const exportMarkdown = () => { if (!result) return; const lines = ['# Patterns Run Report', '', `File: ${trace.input?.file_name || 'Unknown'}`, `Fingerprint: ${trace.fingerprint || 'n/a'}`, '', '## Problem Groups', '']; groups.forEach((g, i) => { lines.push(`### ${i + 1}. ${g.groupName || g.name}`, `- Count: ${g.incidentCount || g.count}`, `- Source: ${g.source || 'not recorded'}`, `- Why: ${g.why || g.matched_reason || 'not recorded'}`, ''); }); const b = new Blob([lines.join('\n')], { type: 'text/markdown' }); const u = URL.createObjectURL(b); const a = document.createElement('a'); a.href = u; a.download = `patterns-report-${Date.now()}.md`; a.click(); URL.revokeObjectURL(u); };
  const applyPreset = (preset) => setConfig(prev => ({ ...prev, ...preset.config }));
  const resetConfig = () => setConfig(prev => ({ ...DEFAULT_CONFIG, taxonomyRulesText: prev.taxonomyRulesText, llmProvider: prev.llmProvider, model: prev.model }));
  const changeLlmProvider = (provider) => { const opts = llmConfig?.providers?.[provider] || []; setConfig(prev => ({ ...prev, llmProvider: provider, model: opts[0] || (provider === llmConfig?.provider ? llmConfig?.model : DEFAULT_PROVIDER_MODELS[provider]) || '' })); };

  const pipelineConfig = [
    { key: 'intake', tone: 'var(--amber)', icon: FileText, tag: 'Stage 01 \u00B7 Intake', title: 'Parse & Clean', body: 'Reads CSV, XLSX, JSON, or Markdown exports and normalizes the fields that matter \u2014 title, description, id, metadata. Duplicate and empty rows are stripped before anything else touches the data.', chips: [`${trace.input?.total_rows || manifest.totalRows || 0} \u2192 ${validTickets} valid`, `${(manifest.emptyTicketsRemoved || 0) + (manifest.duplicatesRemoved || 0)} dropped`], tech: 'Reader auto-detects delimiter/schema per file type. Field mapper aligns columns to <code>title / description / id / metadata</code> via header aliases, falling back to positional heuristics when headers are missing. Rows with empty <code>title + description</code> are dropped; exact-duplicate hashes of <code>title+description</code> collapse to one record.' },
    { key: 'taxonomy', tone: 'var(--amber)', icon: GitBranch, tag: 'Stage 02 \u00B7 Taxonomy gate', title: 'Hierarchical Grouping', body: isClusterOnly ? 'Taxonomy is skipped for this run, so clustering receives the full dataset.' : `Tickets sharing <em>category</em>/<em>subcategory</em> metadata are grouped first, then matched against ${config.taxonomyMode === 'custom' ? 'your custom' : 'known OKF/ITSM'} taxonomy rules.`, chips: [`${rulesCount} rules checked`, `${okfMatchedCount} matched direct`], tech: `Groups are keyed by the <code>(category, subcategory)</code> tuple. Each group\'s combined text is checked against the loaded ${config.taxonomyMode === 'custom' ? 'custom' : 'default'} taxonomy rules (keyword/regex based). In taxonomy-only mode, unmatched tickets stay in review instead of falling through to clustering.` },
    { key: 'discovery', tone: 'var(--teal)', icon: Network, tag: 'Stage 03 \u00B7 Discovery', title: 'Clustering Fallback', body: isTaxonomyOnly ? 'Clustering is disabled for this run; only taxonomy rules produce groups.' : isClusterOnly ? 'All tickets are vectorized and grouped by the selected clustering method.' : 'Whatever taxonomy can\'t claim moves here. Titles and descriptions are vectorized and grouped by the selected clustering method.', chips: [`${clusterInputCount} sent to cluster`, `${optionLabel(CLUSTERING_OPTIONS, config.clusteringMethod)}`], tech: 'Tickets are vectorized as normalized, stopword-stripped bag-of-words counters. Pairwise cosine similarity feeds the selected clustering method (semantic / agglomerative / HDBSCAN-lite / K-means). Minimum cluster size is 2; singletons can go to LLM fallback or review.' },
    { key: 'llm', tone: 'var(--violet)', icon: Brain, tag: 'Stage 04 \u00B7 LLM assist', title: 'LLM Fallback', body: 'Clusters that still resist a clean label go to an LLM, which either matches them against existing taxonomy or proposes new rules to extend it \u2014 a suggestion, never an automatic change to the rule set.', chips: [`${llmHitCount} fallback hits`, `${llmSuggestionCount} suggestions`], tech: 'The cluster centroid plus up to 5 representative tickets are sent to the configured provider/model. The prompt asks: does this match an existing taxonomy leaf, and if not, what new rule (name, keywords, parent) would capture it. A malformed response gets one retry, then falls back to "Unclassified".' },
    { key: 'consolidation', tone: 'var(--violet)', icon: Database, tag: 'Stage 05 \u00B7 Consolidation', title: 'Merge & Roll Up', body: 'Duplicate groups merge. Small generated groups roll up into their taxonomy parents. Overflow groups get capped, so forty near-identical slivers never drown out the signal that matters.', chips: [`${semanticGroupCount} semantic`, `${groups.length || manifest.problemGroups || 0} final groups`], tech: 'Groups with high keyword overlap merge via Jaccard similarity on their rule/cluster keyword sets. Groups below the minimum incident count roll up into the nearest taxonomy parent by rule hierarchy. Groups beyond the max-groups cap are folded into a ranked "Other" bucket.' },
    { key: 'output', tone: 'var(--muted)', icon: CheckCircle, tag: 'Stage 06 \u00B7 Output', title: 'Ranked Problem Groups', body: 'A manifest of counts and coverage, plus ranked problem groups \u2014 name, description, incident count, confidence, representative tickets, and taxonomy suggestions where the rule set could grow.', chips: [`${groups.length || 0} groups ranked`, 'manifest attached'], tech: 'Manifest and groups are serialized to JSON/CSV. Each group carries a <code>confidence_breakdown</code> object (<code>rule_or_cluster</code>, <code>coverage</code>, <code>human_review</code>), its top representative tickets by centrality, and an optional <code>taxonomy_suggestion</code> field for promotion review.' },
  ];

  return (
    <div className="ticket-analysis-page">
      <nav className="ti-nav">
        <div className="ti-nav-inner">
          <button className="menu-button icon-button ti-menu-button" onClick={openMenu} aria-label="Open menu">
            <Menu size={20} />
          </button>
          <div className="ti-brand"><span className="dot" /> Patterns</div>
          <div className={`ti-nav-status${analyzing ? ' running' : runStatus.type === 'idle' ? '' : ` ${runStatus.type}`}`}>
            {analyzing ? <Loader2 size={12} className="ti-spin" /> : runStatus.type === 'error' ? <AlertCircle size={12} /> : runStatus.type === 'success' ? <CheckCircle size={12} /> : <Activity size={12} />}
            <span>{analyzing ? 'Running' : runStatus.type === 'error' ? 'Error' : runStatus.type === 'success' ? 'Done' : 'Idle'}</span>
          </div>
          <div className="ti-nav-links">
            <a href="#pipeline">Pipeline</a>
            <a href="#results">Results</a>
            <a href="#controls">Controls</a>
          </div>
        </div>
      </nav>

      <div className="ti-scroll">
        <div className="ti-wrap">

          {/* ─── HERO ─── */}
          <section className="ti-hero">
            <div className="ti-hero-copy">
              <div className="ti-eyebrow">ticket_analysis.py / analysis cockpit</div>
              <h1 className="ti-title">Patterns</h1>
              <p className="ti-lede">Turn raw exports into ranked problem groups with visible evidence, confidence, telemetry, and configurable taxonomy rules.</p>
            </div>
            <div className="ti-hero-stats">
              <div className="ti-hero-stat"><div className="num">{trace.input?.total_rows || manifest.totalRows || 0}</div><div className="lbl">Input rows</div></div>
              <div className="ti-hero-stat"><div className="num">{validTickets || 0}</div><div className="lbl">Valid tickets</div></div>
              <div className="ti-hero-stat"><div className="num accent">{groups.length || manifest.problemGroups || 0}</div><div className="lbl">Final groups</div></div>
              <div className="ti-hero-stat"><div className="num">{pct(okfMatchedCount, validTickets)}</div><div className="lbl">Taxonomy matched</div></div>
              <div className="ti-hero-stat"><div className="num">{rulesCount || 0}</div><div className="lbl">Rules loaded</div></div>
            </div>
          </section>

          {/* ─── FILE BAR ─── */}
          <div className="ti-file-bar">
            <div className="ti-file-select">
              <label>Ticket file</label>
              <select value={selectedFileId || ''} onChange={e => setSelectedFileId(e.target.value ? Number(e.target.value) : null)} disabled={filesLoading || ticketFiles.length === 0}>
                <option value="">{filesLoading ? 'Loading files...' : ticketFiles.length ? 'Select a ticket file...' : 'No ticket files found'}</option>
                {ticketFiles.map(f => <option key={f.id} value={f.id}>{f.name} — {fileMetaLine(f)}</option>)}
              </select>
              <div className="ti-select-meta">{selectedFile ? `${fileMetaLine(selectedFile)} \u00B7 hash ${shortHash(trace.input?.file_hash)}` : ticketFiles.length ? 'Choose one uploaded CSV/XLSX/JSON/TXT/MD ticket export' : 'Upload a CSV, TSV, XLSX, JSON, TXT, or MD ticket export in Library, then refresh.'}</div>
            </div>
            <div className="ti-file-kpis">
              <span><strong>{validTickets || '-'}</strong> tickets</span>
              <span><strong>{trace.run_id || '-'}</strong> run</span>
              <span>{STRATEGY_LABELS[config.groupingMode]}</span>
              {!isClusterOnly && <span>{config.taxonomySource === 'custom' ? `${rulesCount} custom rule(s)` : 'Built-in rules'}</span>}
            </div>
            <div className="ti-btn-group">
              <button className="ti-btn ti-btn-primary" onClick={handleAnalyze} disabled={!selectedFileId || analyzing || (config.taxonomyMode === 'custom' && Boolean(customTaxonomy.error))}>
                {analyzing ? <Loader2 size={16} className="ti-spin" /> : <Play size={16} />}
                {analyzing ? 'Running' : 'Run Analysis'}
              </button>
              <button className="ti-btn" onClick={refreshTicketFiles} disabled={filesLoading}>
                <RefreshCw size={14} className={filesLoading ? 'ti-spin' : ''} />Refresh files
              </button>
              <button className="ti-btn" onClick={resetRun}><RefreshCw size={14} />Reset</button>
              <button className="ti-btn ti-btn-sm" onClick={() => setHistoryPanelOpen(true)}><History size={14} />History</button>
              <button className="ti-btn ti-btn-sm" onClick={() => result && exportJson()} disabled={!result}><Download size={14} />Export</button>
            </div>
          </div>

          {/* ─── STATUS ─── */}
          {runStatus.type !== 'idle' && (
            <div className={`ti-status ${runStatus.type}`}>
              {runStatus.type === 'running' ? <Loader2 size={15} className="ti-spin" /> : runStatus.type === 'error' ? <AlertCircle size={15} /> : <CheckCircle size={15} />}
              <span>{runStatus.message}</span>
            </div>
          )}

          {/* ─── LIVE PIPELINE CONSOLE ─── */}
          {(analyzing || consoleLines.length > 0) && (
            <div className={`ti-console${analyzing ? ' live' : ''}`}>
              <div className="ti-console-head">
                <div className="ti-console-head-left">
                  <span className="ti-console-dot" />
                  <Activity size={13} />
                  <span className="ti-console-title">{analyzing ? 'Pipeline running' : 'Last run log'}</span>
                </div>
                <div className="ti-console-head-right">
                  <span className="ti-console-timer">{(elapsedMs / 1000).toFixed(1)}s</span>
                  {!analyzing && (
                    <button className="ti-detail-toggle" onClick={() => setConsoleOpen(o => !o)}>
                      <ChevronDown size={14} className={`ti-chevron${consoleOpen ? ' open-rot' : ''}`} />
                      {consoleOpen ? 'Hide log' : 'Show log'}
                    </button>
                  )}
                </div>
              </div>
              <div className="ti-console-progress"><div className="ti-console-progress-fill" style={{ width: `${pipelineProgressPct}%` }} /></div>
              {(analyzing || consoleOpen) && (
                <div className="ti-console-body" ref={consoleBodyRef}>
                  {consoleLines.map((line, i) => (
                    <div key={i} className="ti-console-line">
                      <span className="ti-console-ts">+{(line.t / 1000).toFixed(1)}s</span>
                      <span>{line.text}</span>
                    </div>
                  ))}
                  {analyzing && <div className="ti-console-line ti-console-cursor"><span className="ti-console-ts" /><span className="ti-console-blink">▍</span></div>}
                </div>
              )}
            </div>
          )}

          {/* ═══════ SETTINGS ═══════ */}
          <section className="ti-section" id="controls">
            <div className="ti-section-head">
              <div className="htext">
                <div className="ti-eyebrow">Run settings</div>
                <h2>Set up the run</h2>
                <p>Six decisions, top to bottom, in the order the pipeline makes them. Settings that cannot affect this configuration are hidden rather than greyed out.</p>
              </div>
              <div className="ti-bulk-actions">
                <button className="ti-bulk-btn" onClick={() => setControlsOpen(open => !open)}>
                  {controlsOpen ? 'Hide settings' : 'Show settings'}
                </button>
              </div>
            </div>

            <div className="ti-summary-chips" style={{ marginBottom: 18 }}>
              <span className="ti-chip">{STRATEGY_LABELS[config.groupingMode]}</span>
              {!isClusterOnly && <span className="ti-chip">{rulesCount} rule{rulesCount === 1 ? '' : 's'}</span>}
              {!isTaxonomyOnly && <span className="ti-chip">{optionLabel(EMBEDDING_OPTIONS, config.embeddingMethod)}</span>}
              {!isTaxonomyOnly && <span className="ti-chip">{optionLabel(CLUSTERING_OPTIONS, config.clusteringMethod)}</span>}
              <span className="ti-chip">AI: {[config.useLlmFallback && 'grouping', config.useLlmLabels && 'naming', config.suggestTaxonomyRules && 'suggestions'].filter(Boolean).join(' + ') || 'off'}</span>
              {(config.useLlmFallback || config.useLlmLabels || config.suggestTaxonomyRules) && <span className="ti-chip">{config.model || 'default model'}</span>}
            </div>

            {controlsOpen && (
              <TicketAnalysisSettings
                config={config}
                setConfigValue={setConfigValue}
                applyPreset={applyPreset}
                resetConfig={resetConfig}
                customTaxonomy={customTaxonomy}
                taxonomyRuleCount={customTaxonomy.rules?.length || 0}
                onResetTaxonomyText={() => setConfigValue('taxonomyRulesText', editableTaxonomyFromOkf(okfTaxonomy))}
                llmConfig={llmConfig}
                providerModelOptions={providerModelOptions}
                onProviderChange={changeLlmProvider}
                llmSummaries={llmSummaries}
              />
            )}

            {result && (
              <div className="ti-ctrl-card ti-full-span" style={{ marginTop: 18 }}>
                <h4><span className="sw" style={{ background: 'var(--amber)' }} /> This run</h4>
                <div className="ti-detection">
                  <code>{trace.fingerprint}</code>
                  <span className={trace.vectorization?.fresh ? 'fresh' : 'cached'}>{trace.vectorization?.message}</span>
                  <div className="ti-detection-grid">
                    {['id', 'title', 'description', 'category', 'subcategory'].map(field => (
                      <span key={field} className="ti-detection-chip"><strong>{field}</strong> {detectedFields[field] || 'not detected'}</span>
                    ))}
                    <span className="ti-detection-chip"><strong>metadata</strong> {detectedFields.metadata?.length ? detectedFields.metadata.join(', ') : 'none'}</span>
                  </div>
                </div>
                <div className="ti-btn-group">
                  <button className="ti-btn ti-btn-sm" onClick={() => saveSnapshot(result, 'manual')} disabled={Boolean(savedRunId)}><Download size={12} />{savedRunId ? `Saved #${savedRunId}` : 'Save snapshot'}</button>
                  <button className="ti-btn ti-btn-sm" onClick={exportMarkdown}><FileText size={12} />Report (.md)</button>
                  <button className="ti-btn ti-btn-sm" onClick={() => exportJson()}><Download size={12} />Data (.json)</button>
                </div>
              </div>
            )}
          </section>


          {/* ═══════ PIPELINE ═══════ */}
          <section className="ti-section" id="pipeline">
            <div className="ti-section-head">
              <div className="htext">
                <div className="ti-eyebrow">How a ticket gets classified</div>
                <h2>Six stages, one direction</h2>
                <p>A ticket moves down the line and stops at the first stage confident enough to claim it. Click a stage to see how; click again inside for the technical detail.</p>
              </div>
              <div className="ti-bulk-actions">
                <button className="ti-bulk-btn" onClick={() => setAllStages(true)}>Expand all</button>
                <button className="ti-bulk-btn" onClick={() => setAllStages(false)}>Collapse all</button>
              </div>
            </div>

            <div className="ti-rail">
              <div className="ti-rail-line" />
              {pipelineConfig.map(st => {
                const Icon = st.icon;
                const open = expandedStages.has(st.key);
                const techOpen = expandedTech.has(st.key);
                const running = liveStage === st.key;
                const done = doneStages.has(st.key);
                return (
                  <div key={st.key} className={`ti-stage ti-acc-parent${open ? ' open' : ''}${running ? ' running' : ''}${done ? ' done' : ''}`} style={{ '--stage-color': st.tone }}>
                    <div className="ti-stage-node">{running ? <Loader2 size={19} className="ti-stage-spin" /> : done ? <CheckCircle size={19} /> : <Icon size={19} />}</div>
                    <div className="ti-stage-card">
                      <button className="ti-stage-head" onClick={() => toggleStage(st.key)}>
                        <div className="ti-stage-head-main">
                          <span className="ti-stage-tag">{st.tag}</span>
                          <h3>{st.title}</h3>
                          {(running || stageDetail[st.key]) && (
                            <div className="ti-stage-live">{running && <span className="ti-stage-dot" />}{stageDetail[st.key] || 'Working…'}</div>
                          )}
                        </div>
                        <div className="ti-stage-head-side">
                          {st.chips.map(ch => <span key={ch} className="ti-chip">{ch}</span>)}
                          <ChevronDown size={18} className="ti-chevron" />
                        </div>
                      </button>
                      <div className="ti-acc-body"><div className="ti-acc-inner"><div className="ti-acc-inner-pad">
                        <p dangerouslySetInnerHTML={{ __html: st.body }} />
                        <div className="ti-stage-meta">
                          {st.chips.map(ch => <span key={ch} className="ti-chip">{ch}</span>)}
                        </div>
                        <div className={`ti-nested ti-acc-parent${techOpen ? ' open' : ''}`}>
                          <button className="ti-detail-toggle" onClick={(e) => { e.stopPropagation(); toggleTech(st.key); }}>
                            <ChevronDown size={14} className="ti-chevron" />
                            Technical detail
                          </button>
                          <div className="ti-acc-body"><div className="ti-acc-inner">
                            <div className="ti-tech-detail" dangerouslySetInnerHTML={{ __html: st.tech }} />
                          </div></div>
                        </div>
                      </div></div></div>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="ti-manifest">
              <pre className="ti-manifest-term">{`// run manifest\n{\n  "input_rows": ${trace.input?.total_rows || manifest.totalRows || 0},\n  "valid_tickets": ${validTickets || 0},\n  "taxonomy_matched": ${okfMatchedCount},\n  "clustered": ${clusterOutputCount},\n  "llm_fallback_hits": ${llmHitCount},\n  "final_groups": ${groups.length || manifest.problemGroups || 0},\n  "rules_loaded": ${rulesCount || 0}\n}`}</pre>
              <div className="ti-manifest-note">
                <div className="big">Read the manifest before the groups.</div>
                <p>{isTaxonomyOnly ? 'Taxonomy-only mode keeps unmatched tickets in review instead of clustering them.' : isClusterOnly ? 'Clustering-only mode skips taxonomy so the selected clustering method owns the full dataset.' : okfMatchedCount > 0 && clusterInputCount === 0 ? 'A 100% taxonomy match with 0 clustering means every ticket had a home already; a low match rate means the taxonomy needs new rules, not a better model.' : 'Unmatched tickets moved from taxonomy into clustering and optional LLM fallback.'}</p>
              </div>
            </div>
          </section>

          {/* ═══════ RESULTS ═══════ */}
          <section className="ti-section ti-section-alt" id="results">
            <div className="ti-section-head">
              <div className="htext">
                <div className="ti-eyebrow">Sample run</div>
                <h2>Problem groups, ranked</h2>
                <p>Click a group for evidence and confidence. Inside, "Show full trace" gives the ticket-by-ticket breakdown.</p>
              </div>
              {groups.length > 0 && (
                <div className="ti-bulk-actions">
                  <button className="ti-bulk-btn" onClick={() => setAllGroups(true)}>Expand all</button>
                  <button className="ti-bulk-btn" onClick={() => setAllGroups(false)}>Collapse all</button>
                </div>
              )}
            </div>

            {/* ─── TABS ─── */}
            <div className="ti-tabs-row">
              {[
                ['groups', 'Problem Groups'],
                ['evidence', 'Pipeline Evidence'],
                ['okf', 'Taxonomy'],
                ['suggestions', 'Taxonomy Suggestions'],
                ['debug', 'Debug'],
                ['history', 'History / Compare'],
              ].map(([key, label]) => (
                <button key={key} className={`ti-bulk-btn ti-tab${activeTab === key ? ' active' : ''}`}
                  onClick={() => setActiveTab(key)}>{label}</button>
              ))}
            </div>

            {activeTab === 'groups' && (
              <>
                <div className="ti-stat-row">
                  <div className="cell"><div className="n">{validTickets || 0}</div><div className="l">Valid tickets</div></div>
                  <div className="cell"><div className="n">{groups.length || manifest.problemGroups || 0}</div><div className="l">Final groups</div></div>
                  <div className="cell"><div className="n">{pct(okfMatchedCount, validTickets)}</div><div className="l">Taxonomy</div></div>
                  <div className="cell"><div className="n">{pct(clusterOutputCount, validTickets)}</div><div className="l">Clustered</div></div>
                </div>

                <div className="ti-group-list">
                  {groups.length === 0 ? (
                    <div className="ti-empty">No problem groups created yet. Select a ticket file and run analysis.</div>
                  ) : groups.map((group, index) => {
                    const gc = Number(group.confidence || 0);
                    const gp = group.percentage || ((group.incidentCount || group.count || 0) / Math.max(1, validTickets) * 100).toFixed(1) + '%';
                    const barColor = gc >= 0.85 ? 'var(--amber)' : gc >= 0.7 ? 'var(--teal)' : 'var(--rose)';
                    const open = expandedGroups.has(index);
                    const traceOpen = expandedTraces.has(index);
                    return (
                      <div key={group.id || index} className={`ti-group-card ti-acc-parent${open ? ' open' : ''}`}>
                        <button className="ti-group-head" onClick={() => toggleGroup(index)}>
                          <span className="ti-group-rank">{String(index + 1).padStart(2, '0')}</span>
                          <span className="ti-group-bar" style={{ background: barColor }} />
                          <div className="ti-group-main">
                            <h4>{group.groupName || group.name}</h4>
                            <p>{group.description}</p>
                          </div>
                          <div className="ti-group-figs">
                            <div className="ti-fig"><div className="n">{group.incidentCount || group.count}</div><div className="l">Tickets</div></div>
                            <div className="ti-fig"><div className="n">{gp}</div><div className="l">Share</div></div>
                            <span className="ti-conf-pill">{gc.toFixed(2)}</span>
                          </div>
                          <ChevronDown size={18} className="ti-chevron" />
                        </button>
                        <div className="ti-acc-body"><div className="ti-acc-inner">
                          <div className="ti-group-body-inner">
                            <div>
                              <div className="ti-evidence-label"><b>Why this group formed:</b> {group.why || group.matched_reason || 'matched directly against taxonomy rules \u2014 no clustering or LLM involved.'}</div>
                              <div className="ti-tag-row">
                                <span className="ti-tag">rule: {group.matched_rule || 'taxonomy direct match'}</span>
                                <span className="ti-tag">cluster: {group.cluster_id || 'none'}</span>
                                {group.source && <span className="ti-tag">source: {group.source}</span>}
                              </div>
                              <ul className="ti-rep-list">
                                {(group.representativeTickets || group.representative_tickets || []).length > 0
                                  ? (group.representativeTickets || group.representative_tickets || []).map((t, ti) => (
                                    <li key={ti}>{t.ticketId ? `${t.ticketId} \u2014 ` : ''}{t.title}</li>
                                  ))
                                  : <li>No representative tickets recorded.</li>}
                              </ul>
                              <div className={`ti-nested ti-acc-parent${traceOpen ? ' open' : ''}`}>
                                <button className="ti-detail-toggle" onClick={(e) => { e.stopPropagation(); toggleTrace(index); }}>
                                  <ChevronDown size={14} className="ti-chevron" />
                                  Show full trace
                                </button>
                                <div className="ti-acc-body"><div className="ti-acc-inner">
                                  <div className="ti-table-scroll">
                                  <table className="ti-trace-table">
                                    <thead><tr><th>Ticket</th><th>Matched rule</th><th>Confidence</th></tr></thead>
                                    <tbody>
                                      {(group.representativeTickets || group.representative_tickets || []).length > 0
                                        ? (group.representativeTickets || group.representative_tickets || []).map((t, ti) => (
                                          <tr key={ti}>
                                            <td>{t.title}</td>
                                            <td className="mono">{group.matched_rule || group.source || 'taxonomy'}</td>
                                            <td>{gc.toFixed(2)}</td>
                                          </tr>
                                        ))
                                        : <tr><td colSpan={3} style={{ color: 'var(--muted-dim)' }}>No trace data</td></tr>}
                                    </tbody>
                                  </table>
                                  </div>
                                </div></div>
                              </div>
                            </div>
                            <div className="ti-confidence-block">
                              <div className="ti-conf-row"><span className="conf-label">rule_or_cluster</span><div className="ti-conf-track"><div className="ti-conf-fill" style={{ width: `${(gc * 100).toFixed(0)}%`, background: 'var(--amber)' }} /></div><span className="ti-conf-val">{gc.toFixed(2)}</span></div>
                              <div className="ti-conf-row"><span className="conf-label">coverage</span><div className="ti-conf-track"><div className="ti-conf-fill" style={{ width: `${((group.incidentCount || group.count || 0) / Math.max(1, validTickets) * 100).toFixed(0)}%`, background: 'var(--teal)' }} /></div><span className="ti-conf-val">{gp}</span></div>
                              <div className="ti-conf-row"><span className="conf-label">human_review</span><div className="ti-conf-track"><div className="ti-conf-fill" style={{ width: '0%', background: 'var(--violet)' }} /></div><span className="ti-conf-val">0.00</span></div>
                            </div>
                          </div>
                        </div></div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}

            {activeTab === 'evidence' && (
              <div>
                <div style={{ display: 'flex', gap: 0, border: '1px solid var(--line)', borderRadius: 'var(--radius)', overflow: 'hidden', marginBottom: 20 }}>
                  {Object.entries(sourceBreakdown).length > 0
                    ? Object.entries(sourceBreakdown).map(([src, cnt]) => (
                      <div key={src} style={{ flex: 1, padding: '14px 16px', borderRight: '1px solid var(--line)', minWidth: 80, textAlign: 'center' }}>
                        <div style={{ fontFamily: 'var(--mono)', fontSize: 20, fontWeight: 600 }}>{cnt}</div>
                        <div style={{ fontSize: 10.5, color: 'var(--muted-dim)', textTransform: 'uppercase', letterSpacing: '0.06em', marginTop: 1 }}>{src}</div>
                      </div>
                    ))
                    : <div style={{ flex: 1, padding: 20, textAlign: 'center', color: 'var(--muted-dim)' }}>No evidence data</div>}
                </div>
                {stages.map(step => (
                  <div key={step.key} className="ti-stage-card" style={{ marginBottom: 8 }}>
                    <div className="ti-stage-head" style={{ cursor: 'default' }}>
                      <div className="ti-stage-head-main">
                        <span className="ti-stage-tag" style={{ color: 'var(--muted)' }}>{step.label}</span>
                      </div>
                      <div className="ti-stage-head-side">
                        <span className="ti-chip">{step.input_count ?? '-'} in</span>
                        <span className="ti-chip">{step.output_count ?? '-'} out</span>
                        <span className="ti-chip">{step.duration_ms || 0} ms</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {activeTab === 'okf' && (
              <div className="ti-okf-browser">
                <div className="ti-okf-list">
                  {okfRules.length === 0 ? <div style={{ padding: 20, color: 'var(--muted-dim)' }}>Loading...</div>
                    : okfRules.map((rule, i) => (
                      <button key={rule.name} className={i === selectedOkfIndex ? 'active' : ''} onClick={() => setSelectedOkfIndex(i)}>
                        <strong>{rule.name}</strong>
                        <span>{rule.includes?.length || 0} signals</span>
                      </button>
                    ))}
                </div>
                <div className="ti-okf-detail">
                  {selectedOkfRule ? (
                    <>
                      <h3>{selectedOkfRule.name}</h3>
                      <p>{selectedOkfRule.description}</p>
                      <div className="ti-info"><GitBranch size={14} />Active run mode: {config.taxonomyMode === 'custom' ? `${rulesCount} custom rule(s)` : `${rulesCount} default OKF/ITSM rule(s)`}</div>
                      <div className="ti-tag-row">
                        {(selectedOkfRule.assignmentHints || []).map(item => <span key={item} className="ti-tag">owner: {item}</span>)}
                        {(selectedOkfRule.recordTypes || []).map(item => <span key={item} className="ti-tag">record: {item}</span>)}
                      </div>
                      <strong style={{ fontSize: 11.5, color: 'var(--muted)', display: 'block', marginBottom: 8, fontFamily: 'var(--mono)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Signals OKF matches</strong>
                      <div className="ti-okf-chip-cloud">
                        {(selectedOkfRule.includes || []).slice(0, 42).map(item => <span key={item}>{item}</span>)}
                      </div>
                      {(selectedOkfRule.excludes || []).length > 0 && (
                        <>
                          <strong style={{ fontSize: 11.5, color: 'var(--muted-dim)', display: 'block', marginBottom: 8, marginTop: 8, fontFamily: 'var(--mono)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Exclusions</strong>
                          <div className="ti-okf-chip-cloud muted">{selectedOkfRule.excludes.map(item => <span key={item}>{item}</span>)}</div>
                        </>
                      )}
                    </>
                  ) : <div style={{ padding: 20, color: 'var(--muted-dim)' }}>OKF taxonomy is loading.</div>}
                </div>
              </div>
            )}

            {activeTab === 'suggestions' && (
              <div className="ti-suggestions">
                {(trace.taxonomy_suggestions || []).length === 0
                  ? <div className="ti-empty">No taxonomy suggestions yet.</div>
                  : trace.taxonomy_suggestions.map((s, i) => (
                    <div key={i} className="ti-suggestion">
                      <strong>{s.name}</strong>
                      <p>{s.description}</p>
                      <p className="ti-patterns">{(s.patterns || []).join(', ')}</p>
                    </div>
                  ))}
              </div>
            )}

            {activeTab === 'debug' && (
              <div className="ti-debug"><pre>{JSON.stringify(trace, null, 2)}</pre></div>
            )}

            {activeTab === 'history' && (
              <div className="ti-compare">
                <h4>Compare Runs</h4>
                <select value={compareLeftId} onChange={e => setCompareLeftId(e.target.value)}>
                  <option value="">Current run</option>
                  {history.map(item => <option key={item.id} value={item.id}>#{item.id} {item.file_name}</option>)}
                </select>
                <select value={compareRightId} onChange={e => setCompareRightId(e.target.value)}>
                  <option value="">Select previous run...</option>
                  {history.map(item => <option key={item.id} value={item.id}>#{item.id} {item.file_name}</option>)}
                </select>
                {compareRight ? (
                  <div className="ti-compare-grid">
                    <span>Groups</span><strong>{metricDelta(compareLeft?.manifest || manifest, compareRight.manifest, 'problemGroups')}</strong>
                    <span>Unresolved</span><strong>{metricDelta((historyTrace(compareLeft) || trace)?.coverage, historyTrace(compareRight)?.coverage, 'unresolved')}</strong>
                  </div>
                ) : <p className="ti-empty-inline">Select two runs to compare.</p>}
              </div>
            )}
          </section>

          {/* ─── FOOTER ─── */}
          <footer style={{ padding: '40px 0', borderTop: '1px solid var(--line-soft)' }}>
            <div className="ti-wrap" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12, padding: 0 }}>
              <p style={{ fontSize: 12.5, color: 'var(--muted-dim)', fontFamily: 'var(--mono)', margin: 0 }}>Patterns · pipeline explainability</p>
              <p style={{ fontSize: 12.5, color: 'var(--muted-dim)', fontFamily: 'var(--mono)', margin: 0 }}>ticket_analysis.py</p>
            </div>
          </footer>

        </div>
      </div>

      {/* ─── HISTORY DRAWER ─── */}
      {historyPanelOpen && <div className="ti-history-backdrop" onClick={() => setHistoryPanelOpen(false)} />}
      <aside className={`ti-history-drawer${historyPanelOpen ? ' open' : ''}`}>
        <div className="ti-section-head">
          <h2>Run History</h2>
          <div className="ti-btn-group">
            <button className="ti-btn ti-btn-icon" onClick={loadHistory} disabled={historyLoading}><RefreshCw size={14} className={historyLoading ? 'ti-spin' : ''} /></button>
            <button className="ti-btn ti-btn-icon" onClick={() => setHistoryPanelOpen(false)}>x</button>
          </div>
        </div>
        {history.length === 0 ? <p className="ti-empty-inline">No completed runs yet.</p>
          : <div className="ti-history-list">
            {history.map(item => {
              const it = historyTrace(item);
              const v = it?.input?.valid_tickets || item.manifest?.validTickets || 0;
              return (
                <div key={item.id} className="ti-history-item" onClick={() => loadHistoricalResult(item.id)}>
                  <div className="ti-history-icon"><CheckCircle size={14} /></div>
                  <div className="ti-history-info">
                    <span className="ti-history-file">{item.file_name}</span>
                    <span className="ti-history-meta">{item.manifest?.problemGroups || 0} groups · {v} tickets</span>
                    <span className="ti-history-meta">taxonomy {pct(it?.coverage?.taxonomy_matched, v)} · clustered {pct(it?.coverage?.clustered, v)}</span>
                    <span className="ti-history-meta">top: {(item.config?.summary?.topGroups || (item.groups || []).slice(0, 3).map(g => g.groupName)).join(', ') || 'none'}</span>
                    <span className="ti-history-time"><Clock size={10} />{new Date(item.created_at).toLocaleString()}</span>
                  </div>
                  <div className="ti-history-actions">
                    <button onClick={e => { e.stopPropagation(); exportJson(item); }} title="Export"><Download size={12} /></button>
                    <button className="delete" onClick={e => { e.stopPropagation(); deleteHistory(item.id); }} title="Delete"><Trash2 size={12} /></button>
                  </div>
                </div>
              );
            })}
          </div>}
        <div className="ti-compare">
          <h4>Compare</h4>
          <select value={compareLeftId} onChange={e => setCompareLeftId(e.target.value)}><option value="">Current run</option>{history.map(item => <option key={item.id} value={item.id}>#{item.id} {item.file_name}</option>)}</select>
          <select value={compareRightId} onChange={e => setCompareRightId(e.target.value)}><option value="">Select previous run...</option>{history.map(item => <option key={item.id} value={item.id}>#{item.id} {item.file_name}</option>)}</select>
          {compareRight ? (
            <div className="ti-compare-grid">
              <span>Groups</span><strong>{metricDelta(compareLeft?.manifest || manifest, compareRight.manifest, 'problemGroups')}</strong>
              <span>Unresolved</span><strong>{metricDelta((historyTrace(compareLeft) || trace)?.coverage, historyTrace(compareRight)?.coverage, 'unresolved')}</strong>
            </div>
          ) : <p className="ti-empty-inline">Select two runs to compare.</p>}
        </div>
      </aside>

    </div>
  );
}

export default TicketAnalysisPage;
