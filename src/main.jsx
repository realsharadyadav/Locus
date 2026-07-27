import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { createPortal } from 'react-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeSlug from 'rehype-slug';
import {
  Activity, AlertTriangle, ArrowLeft, ArrowRight, BarChart3, BookOpen, BrainCircuit, Check, CircleCheck,
  Code2, Compass, Copy, Cpu, Database, FileText, Folder, History, Home, Info, KeyRound, Layers3,
  LockKeyhole, Menu, MoonStar, PanelLeftClose, PanelLeftOpen, PenLine, Plus, Radio, Search, Send, Settings2, ShieldCheck,
  RotateCcw, SlidersHorizontal, Sparkles, Square, Terminal, Trash2, Upload, Download,
  WandSparkles, X, Zap, ChevronDown, ChevronRight, Globe, FilePlus2,
  LayoutDashboard, Library, MessagesSquare, ChartNoAxesCombined, Fingerprint, Sun, Moon,
  List, Maximize2,
} from 'lucide-react';
import './styles.css';
import { api } from './api';
import { CommandPalette } from './components/CommandPalette';
import { ConfirmModal } from './components/ConfirmModal';
import { ToastStack } from './components/Toast';
import { SecretChatPage, SecretChatStandalone, useSecretChatRoute, secretChatApi } from './secret-chat';
import TicketAnalysisPage from './pages/TicketAnalysisPage';
import { BRAND, assistantLabel, readStorage, readSessionFlag, storageKey, writeSessionFlag, writeStorage } from './brand';
import { displayTime, parseServerTime, resizeTextarea, STORE_COLORS } from './utils';
import { useVisualViewportShell } from './hooks/useVisualViewportShell';

function Logo() {
  return (
    <div className="logo">
      <svg className="logo-mark" viewBox="0 0 25 25" width="34" height="34" aria-hidden="true">
        <circle className="logo-ping" cx="12.5" cy="12.5" r="9" fill="none" strokeWidth="1.4" />
        <circle className="logo-ring-outer" cx="12.5" cy="12.5" r="10" fill="none" strokeWidth="2" />
        <circle className="logo-ring-inner" cx="12.5" cy="12.5" r="5.6" fill="none" strokeWidth="2" />
        <circle className="logo-dot" cx="12.5" cy="12.5" r="2.4" />
      </svg>
      <span>{BRAND.name}</span>
    </div>
  );
}

const tip = text => ({ 'data-tooltip': text, 'aria-description': text });

const NAV_SECTIONS = [
  {
    label: 'Workspace',
    items: [
      { id: 'home', Icon: LayoutDashboard, label: 'Home', accent: '166 84% 55%' },
      { id: 'hub', Icon: Library, label: 'Library', accent: '38 94% 60%' },
      { id: 'explore', Icon: MessagesSquare, label: 'Ask', accent: '255 88% 74%' },
    ],
  },
  {
    label: 'Signals',
    items: [
      { id: 'ticket-analysis', Icon: ChartNoAxesCombined, label: 'Patterns', accent: '205 92% 62%' },
      { id: 'secret-chat', Icon: Fingerprint, label: 'Private', accent: '341 85% 66%' },
    ],
  },
];

function Sidebar({
  page, setPage, mobileOpen, close, fileCount, readyCount, compact, toggleCompact,
  files = [], onOpenFile, onOpenSecretChat, onNewChat, historyCollapsed, setHistoryCollapsed,
  theme, setTheme,
}) {
  const railRef = useRef(null);
  const [marker, setMarker] = useState(null);

  // Measure the active nav button so a single indicator can glide between items
  // instead of each button popping its own highlight.
  useLayoutEffect(() => {
    const rail = railRef.current;
    if (!rail) return;
    const measure = () => {
      const active = rail.querySelector('.nav-item.active');
      if (!active) { setMarker(null); return; }
      setMarker({
        top: active.offsetTop,
        height: active.offsetHeight,
        accent: active.style.getPropertyValue('--nav-accent'),
      });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(rail);
    return () => observer.disconnect();
  }, [page, compact]);

  return (
    <>
      <aside className={`sidebar ${mobileOpen ? 'open' : ''} ${compact ? 'compact' : ''} ${page === 'explore' ? 'sidebar-explore' : ''}`}>
        <div className="side-top">
          <Logo />
          <button className="mobile-close icon-button" onClick={close} aria-label="Close navigation">
            <X size={18} />
          </button>
        </div>
        <nav ref={railRef} className="nav-rail">
          <span
            className={`nav-marker ${marker ? 'visible' : ''}`}
            aria-hidden="true"
            style={marker ? {
              transform: `translateY(${marker.top}px)`,
              height: `${marker.height}px`,
              '--nav-accent': marker.accent,
            } : undefined}
          />
          {NAV_SECTIONS.map((section, sectionIndex) => (
            <div className="nav-group" key={section.label}>
              <span className="nav-group-label">{section.label}</span>
              {section.items.map(({ id, Icon, label, accent }, itemIndex) => (
                <button
                  key={id}
                  className={`nav-item ${page === id ? 'active' : ''}`}
                  style={{ '--nav-accent': accent, '--nav-order': sectionIndex * 3 + itemIndex }}
                  onClick={() => {
                    if (id === 'secret-chat') {
                      onOpenSecretChat?.();
                    } else {
                      setPage(id);
                      close();
                    }
                  }}
                >
                  <span className="nav-icon">
                    <Icon size={18} strokeWidth={1.9} />
                  </span>
                  <span className="nav-label">{label}</span>
                  {id === 'hub' && <span className="nav-count">{fileCount}</span>}
                  {id === 'explore' && readyCount > 0 && <span className="nav-ready-dot" title={`${readyCount} answer${readyCount === 1 ? '' : 's'} ready`} />}
                </button>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <button
            className="sidebar-collapse-btn nav-item"
            style={{ '--nav-accent': '220 12% 66%' }}
            onClick={toggleCompact}
            aria-label={compact ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            <span className="nav-icon">
              {compact ? <PanelLeftOpen size={17} strokeWidth={1.9} /> : <PanelLeftClose size={17} strokeWidth={1.9} />}
            </span>
            <span className="nav-label">Collapse</span>
          </button>
          {compact ? (
            <button
              className="theme-nav-toggle nav-item"
              style={{ '--nav-accent': theme === 'dark' ? '45 96% 62%' : '235 70% 66%' }}
              onClick={() => setTheme?.(theme === 'dark' ? 'light' : 'dark')}
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            >
              <span className="nav-icon">
                <span className="theme-nav-glyphs" data-theme-state={theme}>
                  <Sun size={18} strokeWidth={1.9} />
                  <Moon size={18} strokeWidth={1.9} />
                </span>
              </span>
            </button>
          ) : (
            <div className="theme-switch" role="group" aria-label="Colour theme">
              <span className="theme-switch-thumb" data-theme-state={theme} aria-hidden="true" />
              <button
                type="button"
                className={theme === 'light' ? 'active' : ''}
                onClick={() => setTheme?.('light')}
                aria-pressed={theme === 'light'}
              >
                <Sun size={15} strokeWidth={2} />
                <span>Bright</span>
              </button>
              <button
                type="button"
                className={theme === 'dark' ? 'active' : ''}
                onClick={() => setTheme?.('dark')}
                aria-pressed={theme === 'dark'}
              >
                <Moon size={15} strokeWidth={2} />
                <span>Dark</span>
              </button>
            </div>
          )}
          <button
            className={`sidebar-settings-btn nav-item ${page === 'settings' ? 'active' : ''}`}
            style={{ '--nav-accent': '220 12% 66%' }}
            onClick={() => { setPage('settings'); close(); }}
          >
            <span className="nav-icon">
              <Settings2 size={17} strokeWidth={1.9} />
            </span>
            <span className="nav-label">Settings</span>
          </button>
        </div>
      </aside>
      {mobileOpen && <button className="scrim" aria-label="Close navigation" onClick={close} />}
    </>
  );
}

function Header({ query, setQuery, openMenu, openCreate, openCommand, page }) {
  return (
    <header>
      <button className="menu-button icon-button" onClick={openMenu} aria-label="Open menu">
        <Menu size={20} />
      </button>
      <button className="global-search" onClick={openCommand} aria-label="Open search">
        <Search size={17} />
        <span>{query || 'Search everything you know...'}</span>
        <kbd>⌘ K</kbd>
      </button>
      {page === 'hub' && (
        <button className="new-button" onClick={openCreate}>
          <Plus size={17} /> New store
        </button>
      )}
    </header>
  );
}

function HomePage({ stores, files, chats, loading, onNavigate, onOpenChat }) {
  if (loading) {
    return (
      <div className="page home-page">
        <div className="loading-grid">
          {[1, 2, 3].map(item => <div key={item} className="skeleton-card" />)}
        </div>
      </div>
    );
  }

  const empty = !files.length;

  return (
    <div className="page home-page">
      <section className="home-hero">
        <div className="welcome-mark"><Sparkles size={24} /></div>
        <span className="kicker">YOUR SECOND BRAIN</span>
        <h1>{empty ? `Welcome to ${BRAND.name}` : 'Welcome back'}</h1>
        <p>{empty ? 'Upload files to a store, then ask a question.' : 'Your knowledge is ready to explore.'}</p>
      </section>

      <section className="stat-grid">
        <article><strong>{stores.length}</strong><span>Stores</span></article>
        <article><strong>{files.length}</strong><span>Files</span></article>
        <article><strong>{chats.length}</strong><span>Chats</span></article>
      </section>

      <section className="quick-actions">
        <button onClick={() => onNavigate('hub', { create: true })}><Folder size={16} /> Create store</button>
        <button onClick={() => onNavigate('hub')}><Upload size={16} /> Upload files</button>
        <button onClick={() => onNavigate('explore')}><Compass size={16} /> Ask a question</button>
      </section>

      {empty ? (
        <section className="onboarding-card">
          <h2>Get started in two steps</h2>
          <ol>
            <li>Create a store in Library and upload your documents.</li>
            <li>Open Ask and ask questions grounded in those files.</li>
          </ol>
        </section>
      ) : (
        <section className="home-panels">
          <div className="panel">
            <div className="panel-head"><h2>Recent files</h2></div>
            {files.slice(0, 5).map(file => (
              <button key={file.id} className="panel-row" onClick={() => onNavigate('hub', { storeId: file.store_id })}>
                <FileText size={15} />
                <span>
                  <strong>{file.name}</strong>
                  <small>{fileMetaLine(file)}</small>
                </span>
                <small>{displayTime(file.created_at)}</small>
              </button>
            ))}
          </div>
          <div className="panel">
            <div className="panel-head"><h2>Recent chats</h2></div>
            {!chats.length && <p className="panel-empty">No chats yet. Start one in Explore.</p>}
            {chats.slice(0, 5).map(chat => (
              <button key={chat.id} className="panel-row" onClick={() => onOpenChat(chat.id)}>
                <Compass size={15} />
                <span>{chat.title}</span>
                <small>{displayTime(chat.updated_at)}</small>
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function formatElapsedTime(totalSeconds) {
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function formatFileSize(bytes = 0) {
  const size = Number(bytes) || 0;
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(size >= 10 * 1024 * 1024 ? 0 : 1)} MB`;
  if (size >= 1024) return `${(size / 1024).toFixed(size >= 10 * 1024 ? 0 : 1)} KB`;
  return `${size} B`;
}

function fileMetaLine(file) {
  if (!file) return 'No metadata';
  const chunks = Number(file.embedding_chunks || 0);
  const chunkLabel = chunks === 1 ? '1 chunk' : `${chunks} chunks`;
  return `${formatFileSize(file.size)} · ${chunkLabel}`;
}

function embeddingMeta(file) {
  const status = file.embedding_status || 'pending';
  const chunks = file.embedding_chunks || 0;
  const backend = file.embedding_backend || 'local';
  const model = file.embedding_model || 'local-hash-embedding-v1';
  const labels = {
    embedded: `${chunks} chunks indexed`,
    indexing: 'Embedding now',
    pending: 'Waiting to index',
    empty: 'No searchable text',
    failed: 'Index failed',
  };
  return {
    status,
    backend,
    model,
    label: labels[status] || 'Index pending',
    detail: status === 'embedded' ? `${backend} · ${model}` : (file.embedding_error || model),
  };
}

const PROVIDER_LABELS = { ollama: 'Ollama', groq: 'Groq', openai: 'OpenAI', gemini: 'Gemini' };
const DEFAULT_PROVIDER_MODELS = { ollama: 'llama3.2:latest', groq: 'openai/gpt-oss-20b', openai: 'gpt-5.4-mini', gemini: 'gemini-2.5-flash' };
const AI_PREFERENCE_STORAGE_KEY = storageKey('explore-ai');
const ACTIVE_CHAT_STORAGE_KEY = storageKey('explore-active-chat');
const APP_DATA_CACHE_KEY = storageKey('last-data');
const APP_PAGES = ['home', 'hub', 'explore', 'ticket-analysis', 'secret-chat', 'settings'];
const normalizePageId = pageId => {
  if (pageId === 'ticketinsight' || pageId === 'ticket-analysis-lab') return 'ticket-analysis';
  return pageId;
};

function readSavedAiPreference() {
  try {
    return JSON.parse(readStorage('explore-ai', '{}'));
  } catch {
    return {};
  }
}

function readCachedAppData() {
  try {
    return JSON.parse(readStorage('last-data', '{}'));
  } catch {
    return {};
  }
}

function modelProvider(model) {
  if (model.includes('/') || model.startsWith('llama-3.')) return 'Groq';
  if (model.startsWith('gpt-')) return 'OpenAI';
  if (model.startsWith('gemini-')) return 'Google Gemini';
  if (model.includes('cloud')) return 'Ollama Cloud';
  return 'On-device';
}

function formatContextLength(value) {
  if (!value) return null;
  if (value >= 1000000) return `${(value / 1000000).toFixed(value % 1000000 === 0 ? 0 : 1)}M ctx`;
  if (value >= 1000) return `${Math.round(value / 1000)}K ctx`;
  return `${value} ctx`;
}

function ModelControl({ config, provider, setProvider, model, setModel }) {
  const providerIcons = { ollama: '🦙', groq: '⚡', openai: '🤖', gemini: '✨' };
  const [openMenu, setOpenMenu] = useState(null);
  const [modelQuery, setModelQuery] = useState('');
  const [freeOnly, setFreeOnly] = useState(false);
  const controlRef = useRef(null);
  const modelSearchRef = useRef(null);
  const fallbackModels = {
    ollama: [],
    groq: [],
    openai: [],
    gemini: [],
  };
  useEffect(() => {
    const onPointerDown = event => {
      if (controlRef.current && !controlRef.current.contains(event.target)) setOpenMenu(null);
    };
    window.addEventListener('mousedown', onPointerDown);
    return () => window.removeEventListener('mousedown', onPointerDown);
  }, []);
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

function jobFailureMessage(job) {
  const error = job?.error || job?.detail || 'The answer could not be completed.';
  const diagnosticId = job?.id ? `\n\nDiagnostic ID: ${job.id}` : '';
  const lowered = error.toLowerCase();
  if (job?.model?.startsWith('gemini-') && lowered.includes('quota')) {
    const zeroLimit = lowered.includes('limit: 0');
    return `Gemini quota exceeded for ${job.model}. ${zeroLimit ? 'Google reports that this project has no available quota for this model. Enable billing or quota in Google AI Studio, or select Gemini 2.5 Flash.' : 'Wait for the quota window to reset, increase your quota, or select another model.'}${diagnosticId}`;
  }
  if (lowered.includes('api key') || lowered.includes('authentication')) {
    return `${modelProvider(job?.model || '')} authentication failed. Check the API key in .env and restart the backend.${diagnosticId}`;
  }
  return `${error}${diagnosticId}`;
}

const humanizePipelineDetail = (detail = '') => {
  const text = String(detail || '').replace(/\s+/g, ' ').trim();
  const lowered = text.toLowerCase();
  if (!text) return 'Starting the pipeline.';
  if (lowered.startsWith('auto-enabled')) return 'Search intent detected. Auto-enabling web research and collecting sources.';
  if (lowered.includes('planning up to')) return 'Planning the query first, so the search is not random.';
  if (lowered.includes('round') && lowered.includes('follow-up')) return `Initial results were weak, trying the next search angle: ${text}`;
  if (lowered.includes('search') && lowered.includes(':')) return `Running search: ${text.split(':').slice(1).join(':').trim() || text}`;
  if (lowered.startsWith('→')) return `Found source: ${text.replace(/^→\s*/, '')}`;
  if (lowered.includes('collected') && lowered.includes('unique sources')) return `Collecting sources: ${text}`;
  if (lowered.includes('semantic retrieval')) return `Searching local files for relevant chunks: ${text}`;
  if (lowered.startsWith('searching')) return `Scanning uploaded files: ${text}`;
  if (lowered.includes('analysis plan ready')) return `Plan is ready. Building the answer against the evidence now.`;
  if (lowered.includes('calling') && lowered.includes('understand')) return `Understanding the question's intent and building the answer structure.`;
  if (lowered.startsWith('preparing')) return `Composing the draft: ${text}`;
  if (lowered.includes('synthesizing')) return `Merging sources and writing the final answer.`;
  if (lowered.includes('verify') || lowered.includes('quality')) return `Checking answer quality and grounding.`;
  if (lowered.includes('repair')) return `Found a gap, refining the answer.`;
  if (lowered.includes('answer ready') || lowered.includes('ready')) return `Answer is ready.`;
  if (lowered.includes('still') || lowered.includes('active')) return `Still working: ${text}`;
  return text.length > 170 ? `${text.slice(0, 167)}...` : text;
};

const buildWorkingNotes = (events = [], pipeline = {}) => {
  const notes = [];
  const candidates = [
    ...events.filter(event => event.detail).map(event => ({
      id: `${event.at || ''}-${event.stage || ''}-${event.detail}`,
      stage: event.stage || pipeline.stage || 'working',
      text: humanizePipelineDetail(event.detail),
      live: false,
    })),
  ];
  if (pipeline.detail) {
    candidates.push({
      id: `current-${pipeline.stage}-${pipeline.detail}`,
      stage: pipeline.stage || 'working',
      text: humanizePipelineDetail(pipeline.detail),
      live: true,
    });
  }
  const seen = new Set();
  for (const item of candidates.reverse()) {
    const key = item.text.toLowerCase();
    if (!item.text || seen.has(key)) continue;
    seen.add(key);
    notes.unshift(item);
    if (notes.length >= 4) break;
  }
  return notes.length ? notes : [{ id: 'start', stage: 'starting', text: 'Got it. Processing the request.', live: true }];
};

const directActivityToNote = item => {
  const label = item?.label || '';
  const detail = item?.detail || '';
  if (/sending/i.test(label)) return `Request sent: ${detail}`;
  if (/connecting/i.test(label)) return `Connecting to the model: ${detail}`;
  if (/streaming/i.test(label)) return `Answer is streaming in: ${detail}`;
  if (/saving/i.test(label)) return `Saving chat history.`;
  if (/stopped/i.test(label)) return `Stopped. You can change the model here and ask again.`;
  return detail || label || 'Working...';
};

function PipelineActivity({ pipeline, model, provider, events, startedAt, reasoningMode, webSearch, fileCount, question, liveLlmHits = 0, liveWebQueries = 0, liveTotalTokens = 0 }) {
  const directModelChat = !webSearch && ((reasoningMode === 'light' && fileCount === 0) || reasoningMode === 'unrestricted');
  const responseStages = [
    ['understanding', 'Plan', BrainCircuit, 'Understanding intent'],
    ['gathering', 'Gather', Database, 'Collecting evidence'],
    ['drafting', 'Compose', PenLine, 'Building the answer'],
  ];
  const directStages = [
    ['drafting', 'Chat', Cpu, 'Direct model chat'],
  ];
  const qualityStages = [
    ['verifying', 'Verify', ShieldCheck, 'Checking quality'],
    ['repairing', 'Refine', Sparkles, 'Resolving gaps'],
  ];
  const stages = directModelChat ? directStages : ['thinking', 'deep_summary'].includes(reasoningMode) ? [...responseStages, ...qualityStages] : responseStages;
  const current = stages.findIndex(([id]) => id === pipeline.stage);
  const activeIndex = Math.max(0, current);
  const [elapsed, setElapsed] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const consoleRef = useRef(null);
  const eventConfig = {
    request: ['REQ', Code2],
    llm_call: ['CALL', Cpu],
    llm_result: ['RECV', Radio],
    retrieval: ['READ', Database],
    chunk: ['MAP', Layers3],
    reduce: ['REDUCE', GitBranchIcon],
    synthesis: ['MERGE', Sparkles],
    quality: ['QA', ShieldCheck],
    heartbeat: ['PING', Activity],
    complete: ['DONE', CircleCheck],
    error: ['ERR', X],
    status: ['LOG', Terminal],
    web: ['WEB', Search],
    web_search: ['SRCH', Search],
  };
  const latestEvent = events[events.length - 1];
  const visibleEvents = events.slice(-18);
  const lastUpdateAge = latestEvent?.at
    ? Math.max(0, Math.floor((Date.now() - parseServerTime(latestEvent.at)) / 1000))
    : 0;
  const progress = Math.max(8, ((activeIndex + .35) / stages.length) * 100);
  const modeLabel = webSearch
    ? reasoningMode === 'unrestricted' ? 'Unrestricted Web Research' : 'Web Research'
    : directModelChat ? 'Direct chat' : reasoningMode === 'unrestricted' ? 'Unrestricted' : reasoningMode === 'ticket_analysis' ? 'Ticket Analysis' : reasoningMode === 'deep_summary' ? 'Deep Summary' : reasoningMode === 'thinking' ? 'Full library' : reasoningMode === 'web_research' ? 'Web Research' : 'Focused retrieval';
  const llmHitKey = event => {
    const preview = event.payload_preview || event.detail || '';
    const normalizedPreview = preview.toLowerCase();
    if (normalizedPreview.includes('still generating this step') || normalizedPreview.startsWith('evidence processing is active:')) return null;
    if (event.type === 'llm_call') {
      if (normalizedPreview.startsWith('preparing a ')) return null;
      return `call:${event.at}:${event.method}:${preview}`;
    }
    if (event.type === 'chunk') {
      const tag = event.tags?.find(item => /^chunk \d+\/\d+$/i.test(item));
      return tag ? `chunk:${tag}` : `chunk:${event.method}:${preview}`;
    }
    if (['reduce', 'synthesis'].includes(event.type)) return `${event.type}:${event.method}:${event.response_preview || preview}`;
    if (event.type === 'quality' && event.direction === 'outbound') return `quality:${event.method}:${preview}`;
    return null;
  };
  const llmHits = new Set(events.map(llmHitKey).filter(Boolean)).size;
  const modelSignals = events.filter(event => ['llm_call', 'llm_result', 'quality'].includes(event.type)).length;
  const chunks = events.filter(event => ['chunk', 'reduce', 'synthesis'].includes(event.type)).length;
  const heartbeats = events.filter(event => event.type === 'heartbeat').length;
  const webSourceKeys = events
    .filter(event => event.type === 'web')
    .map(event => event.tags?.find(tag => /^https?:\/\//i.test(tag)) || event.detail)
    .filter(Boolean);
  const webSources = new Set(webSourceKeys).size;
  const currentEvent = latestEvent || {};
  const currentMethod = currentEvent.method || 'pipeline.tick()';
  const requestPreview = currentEvent.payload_preview || events.find(event => event.type === 'request')?.payload_preview || question || pipeline.detail;
  const responsePreview = currentEvent.response_preview || [...events].reverse().find(event => event.response_preview)?.response_preview || pipeline.detail;
  const providerLabel = provider ? (PROVIDER_LABELS[provider] || provider) : modelProvider(model);
  const compact = (value, fallback = 'Waiting for signal...') => {
    const text = String(value || fallback).replace(/\s+/g, ' ').trim();
    return text.length > 180 ? `${text.slice(0, 177)}...` : text;
  };
  const eventTime = value => {
    const age = value ? Math.max(0, Math.floor((Date.now() - parseServerTime(value)) / 1000)) : 0;
    return age < 2 ? 'now' : `${formatElapsedTime(age)} ago`;
  };
  const methodBadge = event => {
    const source = `${event.http_method || ''} ${event.method || ''} ${(event.tags || []).join(' ')}`.toUpperCase();
    const match = source.match(/\b(GET|POST|PUT|PATCH|DELETE)\b/);
    return match?.[1] || null;
  };
  const workingNotes = buildWorkingNotes(events, pipeline);

  useEffect(() => {
    const update = () => setElapsed(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [startedAt]);

  useEffect(() => {
    consoleRef.current?.scrollTo({
      top: consoleRef.current.scrollHeight,
      behavior: 'smooth',
    });
  }, [events.length, latestEvent?.detail]);

  if (!expanded) {
    return (
      <div className="chat-message assistant" aria-busy="true">
        <div className="assistant-avatar pulse"><Sparkles size={15} /></div>
        <div className="message-body">
          <div className="message-head">
            <span>{BRAND.name} · {model}</span>
            <button className="dev-trace-toggle icon-button" onClick={() => setExpanded(true)} aria-label="Show developer trace" title="Show developer trace">
              <Terminal size={13} />
              <span>Trace</span>
            </button>
          </div>
          <div className="thinking-container">
            <div className="thinking-content">
              <div className="thinking-header">
                <div className="thinking-mode-badge">{modeLabel}</div>
                <span className="thinking-elapsed">{formatElapsedTime(elapsed)}</span>
                <span className="thinking-file-count">{fileCount} file{fileCount !== 1 ? 's' : ''}</span>
              </div>
              {(liveLlmHits > 0 || liveWebQueries > 0 || liveTotalTokens > 0) && (
                <div className="thinking-stats" aria-label="Live usage while processing">
                  {liveLlmHits > 0 && (
                    <span className="thinking-stat"><Cpu size={11} /><strong>{liveLlmHits}</strong> LLM {liveLlmHits === 1 ? 'hit' : 'hits'}</span>
                  )}
                  {liveWebQueries > 0 && (
                    <span className="thinking-stat"><Search size={11} /><strong>{liveWebQueries}</strong> {liveWebQueries === 1 ? 'search' : 'searches'}</span>
                  )}
                  {liveTotalTokens > 0 && (
                    <span className="thinking-stat"><Zap size={11} /><strong>{liveTotalTokens.toLocaleString()}</strong> tokens</span>
                  )}
                </div>
              )}
              <div className="working-notes" aria-label="Live working notes">
                {workingNotes.map((note, index) => {
                  const isLive = index === workingNotes.length - 1;
                  return (
                    <div className={isLive ? 'live' : 'done'} key={note.id}>
                      <span className="note-node" aria-hidden="true">
                        <span className="note-node-ring" />
                        <span className="note-node-core">{isLive ? <span className="note-node-pulse" /> : <Check size={10} />}</span>
                      </span>
                      <p>{note.text}</p>
                    </div>
                  );
                })}
              </div>
              <div className="thinking-animation" aria-hidden="true">
                <span className="thinking-dot" />
                <span className="thinking-dot" />
                <span className="thinking-dot" />
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-message assistant pipeline-message" aria-busy="true">
      <div className="pipeline-card">
        <div className="pipeline-head">
          <div className="pipeline-core" aria-hidden="true">
            <Terminal size={18} />
          </div>
          <div className="pipeline-heading">
            <span className="pipeline-eyebrow">DEVELOPER TRACE</span>
            <strong>{stages[activeIndex][3]}</strong>
            <small>{compact(pipeline.detail)}</small>
          </div>
          <div className="pipeline-time"><strong>{formatElapsedTime(elapsed)}</strong><span>elapsed</span></div>
        </div>

        <div className="pipeline-operation">
          <span className="operation-live"><i /> LIVE OPERATION</span>
          <strong>{currentMethod}</strong>
          <small>Updated {lastUpdateAge < 2 ? 'just now' : `${formatElapsedTime(lastUpdateAge)} ago`}</small>
        </div>

        <div className="pipeline-track">
          {stages.map(([id, label, Icon], index) => (
            <div className={`${index < current ? 'done' : ''} ${index === current ? 'active' : ''}`} key={id}>
              <i>{index < current ? <Check size={11} /> : <Icon size={11} />}</i>
              <span>{label}</span>
            </div>
          ))}
        </div>

        <div className="pipeline-progress"><span style={{ width: `${progress}%` }} /></div>

        <div className="pipeline-dev-grid">
          <div className="pipeline-panel current-call">
            <div className="panel-label"><Code2 size={12} /> Current call</div>
            <code>{currentMethod}</code>
            <div className="call-flow">
              <span className={`direction ${currentEvent.direction || 'internal'}`}>{currentEvent.direction || 'internal'}</span>
              <span>{currentEvent.stage || pipeline.stage}</span>
              <span>{currentEvent.type || 'status'}</span>
            </div>
          </div>
          <div className="pipeline-panel packet-panel">
            <div className="panel-label"><ArrowRight size={12} /> Sending</div>
            <p>{compact(requestPreview)}</p>
          </div>
          <div className="pipeline-panel packet-panel">
            <div className="panel-label"><Radio size={12} /> Receiving</div>
            <p>{compact(responsePreview)}</p>
          </div>
        </div>

        <div className="pipeline-telemetry">
          <span><Activity size={12} /><strong>{events.length}</strong> events</span>
          <span title={`${modelSignals} total model-related signal${modelSignals === 1 ? '' : 's'}`}>
            <Cpu size={12} /><strong>{llmHits}</strong> LLM {llmHits === 1 ? 'hit' : 'hits'}
          </span>
          <span><Layers3 size={12} /><strong>{chunks}</strong> evidence steps</span>
          <span><Radio size={12} /><strong>{heartbeats}</strong> heartbeats</span>
          <span><Search size={12} /><strong>{webSources}</strong> web sources</span>
          <span><FileText size={12} /><strong>{fileCount}</strong> {fileCount === 1 ? 'file' : 'files'}</span>
        </div>

        <div className="pipeline-console">
          <div className="console-head">
            <span><Terminal size={13} /> Runtime console</span>
            <small>{providerLabel} · {modeLabel} · {model}</small>
            <button className="dev-trace-close" onClick={() => setExpanded(false)}>
              <X size={14} /> Hide trace
            </button>
          </div>
          <div className="console-feed" ref={consoleRef}>
            {visibleEvents.map((event, index) => {
              const isLatest = index === visibleEvents.length - 1;
              const [label, Icon] = eventConfig[event.type] || eventConfig.status;
              const httpMethod = methodBadge(event);
              const eventTone = httpMethod ? `http-${httpMethod.toLowerCase()}` : event.type || 'status';
              const webUrl = event.type === 'web' && event.tags?.[0]?.startsWith('http') ? event.tags[0] : null;
              return (
                <div className={`${isLatest ? 'live' : ''} event-${eventTone}`} key={`${event.stage}-${event.at}-${index}`}>
                  <i>{isLatest ? <span className="event-pulse" /> : <Icon size={12} />}</i>
                  <time>{eventTime(event.at)}</time>
                  <b className={`console-badge ${eventTone}`}>{httpMethod || label}</b>
                  <code>{event.method || 'pipeline.tick()'}</code>
                  {webUrl ? (
                    <a className="web-source-link" href={webUrl} target="_blank" rel="noopener noreferrer" title={webUrl}>
                      {compact(event.detail.replace(/https?:\/\/[^\s]+/, '').trim(), 'Event received')}
                    </a>
                  ) : (
                    <span>{compact(event.detail, 'Event received')}</span>
                  )}
                  {!!event.tags?.length && !webUrl && <em>{event.tags.slice(0, 3).join(' · ')}</em>}
                </div>
              );
            })}
          </div>
        </div>

        <div className="pipeline-lower">
          <div className="pipeline-meta">
            <span>{providerLabel}</span>
            <span>{modeLabel}</span>
            <span>{fileCount} {fileCount === 1 ? 'file' : 'files'}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function DirectStreamTrace({ activity = [], model, provider, text = '', streaming = false }) {
  const [expanded, setExpanded] = useState(false);
  if (!activity.length) return null;
  const providerLabel = provider ? (PROVIDER_LABELS[provider] || provider) : modelProvider(model || '');
  const visibleActivity = activity.slice(-10);
  const directNotes = visibleActivity.slice(-4).map((item, index) => ({
    id: item.id || `${item.label}-${index}`,
    text: directActivityToNote(item),
    live: item.state === 'live',
  }));
  return (
    <>
      <div className="direct-working-notes" aria-label="Live working notes">
        {directNotes.map((note, index) => {
          const isLive = note.live || (index === directNotes.length - 1 && streaming);
          return (
            <div className={isLive ? 'live' : 'done'} key={note.id}>
              <span className="note-node" aria-hidden="true">
                <span className="note-node-ring" />
                <span className="note-node-core">{isLive ? <span className="note-node-pulse" /> : <Check size={10} />}</span>
              </span>
              <p>{note.text}</p>
            </div>
          );
        })}
      </div>
      <div className="direct-stream-trace" aria-label="Live answer activity">
        {activity.slice(0, 4).map(item => (
          <div className={`direct-stream-step ${item.state || 'pending'}`} key={item.id}>
            <span aria-hidden="true" />
            <div>
              <strong>{item.label}</strong>
              {item.detail && <small>{item.detail}</small>}
            </div>
          </div>
        ))}
        <button
          type="button"
          className="dev-trace-toggle direct"
          onClick={() => setExpanded(value => !value)}
          aria-expanded={expanded}
          aria-label={expanded ? 'Hide developer trace' : 'Show developer trace'}
          title={expanded ? 'Hide developer trace' : 'Show developer trace'}
        >
          <Terminal size={13} />
          <span>Trace</span>
        </button>
      </div>
      {expanded && (
        <div className="direct-dev-panel">
          <div className="console-head">
            <span><Terminal size={13} /> Direct stream trace</span>
            <small>{providerLabel} · {model}</small>
            <button className="dev-trace-close" onClick={() => setExpanded(false)}>
              <X size={14} /> Hide trace
            </button>
          </div>
          <div className="direct-dev-grid">
            <div>
              <strong>Mode</strong>
              <span>{streaming ? 'Streaming live' : 'Completed'}</span>
            </div>
            <div>
              <strong>Output</strong>
              <span>{text.length.toLocaleString()} chars</span>
            </div>
            <div>
              <strong>Provider</strong>
              <span>{providerLabel}</span>
            </div>
          </div>
          <div className="console-feed direct-console-feed">
            {visibleActivity.map(item => (
              <div className={`${item.state === 'live' ? 'live' : ''} event-${item.state || 'status'}`} key={item.id}>
                <i><Terminal size={11} /></i>
                <time>{item.state || 'status'}</time>
                <b className={`console-badge ${item.state === 'failed' ? 'error' : item.state === 'done' ? 'complete' : 'status'}`}>
                  {item.state === 'failed' ? 'WARN' : item.state === 'done' ? 'DONE' : 'LIVE'}
                </b>
                <code>{item.label}</code>
                <span>{item.detail || 'Waiting for signal'}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

function GitBranchIcon(props) {
  return <Code2 {...props} />;
}

const CODE_FILE_EXTENSIONS = {
  html: 'html', htm: 'html', xml: 'xml', svg: 'svg',
  javascript: 'js', js: 'js', jsx: 'jsx', typescript: 'ts', ts: 'ts', tsx: 'tsx',
  python: 'py', py: 'py', json: 'json', css: 'css', scss: 'scss',
  bash: 'sh', sh: 'sh', shell: 'sh', zsh: 'sh',
  yaml: 'yaml', yml: 'yaml', sql: 'sql', java: 'java', c: 'c', cpp: 'cpp', 'c++': 'cpp',
  go: 'go', rust: 'rs', rb: 'rb', ruby: 'rb', php: 'php', markdown: 'md', md: 'md',
};

let mermaidModulePromise = null;
function loadMermaid() {
  if (!mermaidModulePromise) mermaidModulePromise = import('mermaid').then(module => module.default);
  return mermaidModulePromise;
}

function readMermaidTheme() {
  return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'neutral';
}

// LLMs frequently emit unquoted node labels like Ingress[Ingress Controller (NGINX/Traefik)] —
// Mermaid's grammar treats "(" right after "[" as the start of a different node shape, so the
// parser breaks on any punctuation inside a plain [label]. Auto-quoting is a safe, mechanical fix:
// a quoted label accepts arbitrary text, so this can only turn an invalid diagram valid, never the
// reverse. Only touched as a retry after the model's original syntax has already failed to render.
function autoQuoteMermaidLabels(code) {
  return code.replace(/([A-Za-z_][\w-]*)\[([^[\]]*)\]/g, (match, id, content) => {
    const trimmed = content.trim();
    if (!trimmed || trimmed.startsWith('"')) return match;
    if (trimmed.startsWith('(') && trimmed.endsWith(')')) return match; // [(cylinder shape)]
    if (!/[()/\\{}|#;]/.test(trimmed)) return match;
    return `${id}["${trimmed.replace(/"/g, "'")}"]`;
  });
}

function renameWholeWordOutsideQuotes(line, oldId, newId) {
  const quoted = [];
  const withoutQuotes = line.replace(/"[^"]*"/g, match => {
    quoted.push(match);
    return `\x00${quoted.length - 1}\x00`;
  });
  const renamed = withoutQuotes.replace(new RegExp(`\\b${oldId}\\b`, 'g'), newId);
  return renamed.replace(/\x00(\d+)\x00/g, (_, index) => quoted[Number(index)]);
}

// A subgraph id is itself a graph node, so a node inside it declared with the same id
// ("subgraph API[...]" containing "API[...]") makes that node its own parent — Mermaid
// rejects this as a cycle. Detect subgraph/node id collisions and rename the inner node,
// rewriting every bare reference to it (edges included) but never touching quoted label text
// or the subgraph's own id.
function autoFixMermaidSubgraphCycles(code) {
  const lines = code.split('\n');
  const subgraphDeclareRegex = /^\s*subgraph\s+([A-Za-z_][\w-]*)/;
  const nodeDeclareRegex = /^\s*([A-Za-z_][\w-]*)\s*[[({]/;
  const stack = [];
  const renameMap = new Map();

  for (const line of lines) {
    const subgraphMatch = line.match(subgraphDeclareRegex);
    if (subgraphMatch) {
      stack.push(subgraphMatch[1]);
      continue;
    }
    if (/^\s*end\s*$/.test(line)) {
      stack.pop();
      continue;
    }
    const nodeMatch = line.match(nodeDeclareRegex);
    if (nodeMatch && stack.includes(nodeMatch[1]) && !renameMap.has(nodeMatch[1])) {
      renameMap.set(nodeMatch[1], `${nodeMatch[1]}Node`);
    }
  }

  if (renameMap.size === 0) return code;

  return lines
    .map(line => {
      const subgraphMatch = line.match(subgraphDeclareRegex);
      let result = line;
      for (const [oldId, newId] of renameMap) {
        if (subgraphMatch && subgraphMatch[1] === oldId) continue; // keep the subgraph's own id
        result = renameWholeWordOutsideQuotes(result, oldId, newId);
      }
      return result;
    })
    .join('\n');
}

function repairMermaidCode(code) {
  return autoFixMermaidSubgraphCycles(autoQuoteMermaidLabels(code));
}

let mermaidDiagramSeq = 0;

function useMermaidRender(code) {
  const [result, setResult] = useState({ svg: null, error: null });
  const [themeTick, setThemeTick] = useState(0);
  const idRef = useRef(null);
  if (!idRef.current) idRef.current = `mermaid-diagram-${++mermaidDiagramSeq}`;

  useEffect(() => {
    const observer = new MutationObserver(() => setThemeTick(tick => tick + 1));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    loadMermaid()
      .then(async mermaid => {
        if (cancelled) return null;
        mermaid.initialize({ startOnLoad: false, theme: readMermaidTheme(), securityLevel: 'strict', fontFamily: 'inherit', suppressErrorRendering: true });
        try {
          return await mermaid.render(idRef.current, code);
        } catch (firstError) {
          const repaired = repairMermaidCode(code);
          if (repaired === code) throw firstError;
          try {
            return await mermaid.render(`${idRef.current}-repaired`, repaired);
          } catch {
            throw firstError;
          }
        }
      })
      .then(rendered => { if (!cancelled && rendered) setResult({ svg: rendered.svg, error: null }); })
      .catch(error => { if (!cancelled) setResult({ svg: null, error: error?.message || 'Invalid diagram syntax' }); });
    return () => { cancelled = true; };
  }, [code, themeTick]);

  return result;
}

function DiagramLightbox({ svg, onClose }) {
  const [transform, setTransform] = useState({ scale: 1, x: 0, y: 0 });
  const dragRef = useRef(null);

  useEffect(() => {
    const handleKey = event => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [onClose]);

  const handleWheel = event => {
    event.preventDefault();
    setTransform(current => ({
      ...current,
      scale: Math.min(4, Math.max(0.5, current.scale * (event.deltaY < 0 ? 1.12 : 0.89))),
    }));
  };

  const handlePointerDown = event => {
    dragRef.current = { startX: event.clientX, startY: event.clientY, originX: transform.x, originY: transform.y };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const handlePointerMove = event => {
    if (!dragRef.current) return;
    const { startX, startY, originX, originY } = dragRef.current;
    setTransform(current => ({ ...current, x: originX + (event.clientX - startX), y: originY + (event.clientY - startY) }));
  };
  const stopDrag = () => { dragRef.current = null; };

  return createPortal(
    <div className="diagram-lightbox" onClick={onClose}>
      <div className="diagram-lightbox-toolbar" onClick={event => event.stopPropagation()}>
        <button type="button" className="diagram-lightbox-action" onClick={() => setTransform({ scale: 1, x: 0, y: 0 })} title="Reset zoom">
          <RotateCcw size={15} />
        </button>
        <button type="button" className="diagram-lightbox-action" onClick={onClose} title="Close">
          <X size={17} />
        </button>
      </div>
      <div
        className="diagram-lightbox-canvas"
        onClick={event => event.stopPropagation()}
        onWheel={handleWheel}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={stopDrag}
        onPointerLeave={stopDrag}
        onDoubleClick={() => setTransform({ scale: 1, x: 0, y: 0 })}
      >
        <div
          className="diagram-lightbox-content"
          style={{ transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})` }}
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      </div>
    </div>,
    document.body,
  );
}

function MermaidBlock({ code }) {
  const [copied, setCopied] = useState(false);
  const [showSource, setShowSource] = useState(false);
  const [zoomed, setZoomed] = useState(false);
  const { svg, error } = useMermaidRender(code);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="code-block mermaid-block">
      <div className="code-block-toolbar">
        <span className="code-block-lang">diagram</span>
        <div className="code-block-actions">
          {svg && !showSource && (
            <button type="button" className="code-block-action" onClick={() => setZoomed(true)} title="Expand diagram">
              <Maximize2 size={12} />
            </button>
          )}
          <button type="button" className="code-block-action" onClick={() => setShowSource(value => !value)} title={showSource ? 'Show diagram' : 'View source'}>
            <Code2 size={12} />
          </button>
          <button type="button" className="code-block-action" onClick={handleCopy} title="Copy source">
            {copied ? <Check size={12} /> : <Copy size={12} />}
          </button>
        </div>
      </div>
      {showSource ? (
        <pre><code>{code}</code></pre>
      ) : error ? (
        <div className="mermaid-error">
          <p className="mermaid-error-message">Couldn't render this diagram: {error}</p>
          <pre><code>{code}</code></pre>
        </div>
      ) : svg ? (
        <div className="mermaid-canvas mermaid-canvas-zoomable" onClick={() => setZoomed(true)} dangerouslySetInnerHTML={{ __html: svg }} />
      ) : (
        <div className="mermaid-loading">Rendering diagram…</div>
      )}
      {zoomed && svg && <DiagramLightbox svg={svg} onClose={() => setZoomed(false)} />}
    </div>
  );
}

let highlighterPromise = null;
function loadHighlighter() {
  if (!highlighterPromise) {
    highlighterPromise = Promise.all([
      import('highlight.js'),
      import('highlight.js/styles/atom-one-dark.css'),
    ]).then(([module]) => module.default);
  }
  return highlighterPromise;
}

const HLJS_LANGUAGE_OVERRIDES = { jsx: 'javascript', tsx: 'typescript', 'c++': 'cpp', golang: 'go', vue: 'xml' };

function useHighlightedCode(code, language) {
  const [html, setHtml] = useState(null);
  useEffect(() => {
    if (!code) {
      setHtml(null);
      return;
    }
    let cancelled = false;
    loadHighlighter()
      .then(hljs => {
        if (cancelled) return;
        const resolved = HLJS_LANGUAGE_OVERRIDES[language] || language;
        const result = hljs.getLanguage(resolved)
          ? hljs.highlight(code, { language: resolved, ignoreIllegals: true })
          : hljs.highlightAuto(code);
        setHtml(result.value);
      })
      .catch(() => { if (!cancelled) setHtml(null); });
    return () => { cancelled = true; };
  }, [code, language]);
  return html;
}

const LANGUAGE_ACCENT_COLORS = {
  javascript: '#f0db4f', js: '#f0db4f', jsx: '#f0db4f',
  typescript: '#3178c6', ts: '#3178c6', tsx: '#3178c6',
  python: '#ffd43b', py: '#ffd43b',
  json: '#8bc34a', css: '#42a5f5', scss: '#c06ed6',
  bash: '#8bc9a8', sh: '#8bc9a8', shell: '#8bc9a8', zsh: '#8bc9a8',
  yaml: '#e08ec2', yml: '#e08ec2', sql: '#ff9e64',
  java: '#ea9d5a', c: '#7aa2f7', cpp: '#7aa2f7', 'c++': '#7aa2f7',
  go: '#5bc8af', rust: '#dd8866', ruby: '#e0605b', php: '#8892c7',
  html: '#e0714f', xml: '#e0714f', markdown: '#9aa5ce', md: '#9aa5ce',
};

function CodeBlock({ className, children, streaming }) {
  const [copied, setCopied] = useState(false);
  const match = /language-(\w+)/.exec(className || '');
  const language = match ? match[1].toLowerCase() : '';
  const codeText = String(children).replace(/\n$/, '');
  const isMermaid = language === 'mermaid';
  const highlighted = useHighlightedCode(match && !isMermaid ? codeText : '', language);

  if (!match) {
    return <code className={className}>{children}</code>;
  }

  if (isMermaid) {
    if (streaming) {
      return (
        <div className="code-block mermaid-block mermaid-block-pending">
          <div className="code-block-toolbar"><span className="code-block-lang">diagram</span></div>
          <pre><code className={className}>{children}</code></pre>
        </div>
      );
    }
    return <MermaidBlock code={codeText} />;
  }

  const handleCopy = async () => {
    await navigator.clipboard.writeText(codeText);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  const handleDownload = () => {
    const extension = CODE_FILE_EXTENSIONS[language] || 'txt';
    const blob = new Blob([codeText], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `snippet.${extension}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="code-block">
      <div className="code-block-toolbar">
        <span className="code-block-lang">
          <span className="code-block-lang-dot" style={{ background: LANGUAGE_ACCENT_COLORS[language] || '#8b95a5' }} aria-hidden="true" />
          {language}
        </span>
        <div className="code-block-actions">
          <button type="button" className="code-block-action" onClick={handleCopy} title="Copy code">
            {copied ? <Check size={12} /> : <Copy size={12} />}
          </button>
          <button type="button" className="code-block-action" onClick={handleDownload} title="Download as file">
            <Download size={12} />
          </button>
        </div>
      </div>
      {highlighted != null ? (
        <pre><code className={`hljs language-${language}`} dangerouslySetInnerHTML={{ __html: highlighted }} /></pre>
      ) : (
        <pre><code className={className}>{children}</code></pre>
      )}
    </div>
  );
}

function AnswerToc({ headings }) {
  const [collapsed, setCollapsed] = useState(false);

  if (headings.length < 3) return null;

  const jumpTo = id => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="answer-toc">
      <button type="button" className="answer-toc-toggle" onClick={() => setCollapsed(value => !value)}>
        <List size={13} />
        <span>Contents · {headings.length}</span>
        <ChevronDown size={13} className={`answer-toc-chevron ${collapsed ? 'collapsed' : ''}`} />
      </button>
      {!collapsed && (
        <ul className="answer-toc-list">
          {headings.map(heading => (
            <li key={heading.id} className={`answer-toc-item level-${heading.level}`}>
              <button type="button" onClick={() => jumpTo(heading.id)}>{heading.text}</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AssistantMarkdown({ text, streaming, messageKey }) {
  const containerRef = useRef(null);
  const [headings, setHeadings] = useState([]);
  // components must stay referentially stable across re-renders (e.g. from chat-job
  // polling) — react-markdown remounts the code renderer whenever its identity changes,
  // which would restart any in-flight Mermaid render before it ever resolves.
  const components = useMemo(
    () => ({ code: props => <CodeBlock {...props} streaming={streaming} /> }),
    [streaming],
  );
  const rehypePlugins = useMemo(() => [[rehypeSlug, { prefix: `md-${messageKey}-` }]], [messageKey]);

  useLayoutEffect(() => {
    if (streaming || !containerRef.current) return;
    const nodes = containerRef.current.querySelectorAll('h1[id], h2[id], h3[id]');
    setHeadings(Array.from(nodes).map(node => ({ id: node.id, level: Number(node.tagName[1]), text: node.textContent })));
  }, [streaming, text]);

  return (
    <div ref={containerRef}>
      {!streaming && <AnswerToc headings={headings} />}
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={rehypePlugins} components={components}>{text || ' '}</ReactMarkdown>
    </div>
  );
}



function HubPage({
  query, files, stores, focusStoreId, clearFocusStore, openCreate,
  uploadFile, requestDeleteFile, requestDeleteStore, toast,
}) {
  const [activeStore, setActiveStore] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadStage, setUploadStage] = useState(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (focusStoreId) {
      const store = stores.find(item => item.id === focusStoreId);
      if (store) setActiveStore(store);
      clearFocusStore();
    }
  }, [focusStoreId, stores, clearFocusStore]);

  const visibleStores = stores.filter(store =>
    store.title.toLowerCase().includes(query.toLowerCase()) ||
    store.description?.toLowerCase().includes(query.toLowerCase()),
  );
  const visibleFiles = files.filter(file =>
    file.store_id === activeStore?.id &&
    file.name.toLowerCase().includes(query.toLowerCase()),
  );

  const handleUpload = async (fileList) => {
    const file = fileList?.[0];
    if (!file || !activeStore) return;
    setUploading(true);
    setUploadStage({
      step: 0,
      title: 'Receiving file',
      detail: `${file.name} · ${formatFileSize(file.size)}`,
    });
    const timers = [
      window.setTimeout(() => setUploadStage({ step: 1, title: 'Extracting text', detail: 'Reading pages, sheets, rows and code blocks' }), 500),
      window.setTimeout(() => setUploadStage({ step: 2, title: 'Creating embeddings', detail: 'Model: local-hash-embedding-v1' }), 1200),
      window.setTimeout(() => setUploadStage({ step: 3, title: 'Writing vector index', detail: 'Persisting chunks to local Chroma/SQLite store' }), 2200),
    ];
    try {
      const uploaded = await uploadFile(activeStore.id, file);
      const meta = embeddingMeta(uploaded || {});
      setUploadStage({
        step: 4,
        title: meta.status === 'failed' ? 'Upload saved, index failed' : 'Ready for semantic search',
        detail: `${meta.label} · ${meta.detail}`,
      });
      toast(meta.status === 'failed' ? 'File uploaded, indexing failed' : 'File uploaded and indexed', meta.status === 'failed' ? 'error' : 'success');
    } catch (error) {
      setUploadStage({ step: 4, title: 'Upload failed', detail: error.message });
      toast(error.message, 'error');
    } finally {
      timers.forEach(timer => window.clearTimeout(timer));
      window.setTimeout(() => setUploadStage(null), 1800);
      setUploading(false);
    }
  };

  if (activeStore) {
    return (
      <div className="page inner-page">
        <button className="back-button" onClick={() => setActiveStore(null)}>
          <ArrowLeft size={15} /> All stores
        </button>
        <div className="inner-title store-title">
          <div>
            <span className="kicker">STORE</span>
            <h1>{activeStore.title}</h1>
            <p>{activeStore.description || 'Files in this store are available to Explore.'}</p>
          </div>
          <label className={`new-button upload-button ${uploading ? 'disabled' : ''}`}>
            <Upload size={16} />{uploading ? 'Uploading...' : 'Upload file'}
            <input
              type="file"
              accept=".xlsx,.xlsm,.csv,.tsv,.txt,.md,.pdf,.docx,.json,.html,.css,.js,.jsx,.py"
              onChange={event => handleUpload(event.target.files).finally(() => { event.target.value = ''; })}
              disabled={uploading}
            />
          </label>
        </div>

        <div
          className={`drop-zone ${dragging ? 'dragging' : ''} ${uploading ? 'processing' : ''}`}
          onDragOver={event => { event.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={event => {
            event.preventDefault();
            setDragging(false);
            handleUpload(event.dataTransfer.files);
          }}
        >
          <Upload size={18} />
          <div>
            <span>{uploadStage?.title || 'Drop files here to upload'}</span>
            {uploadStage ? <small>{uploadStage.detail}</small> : <small>PDF, DOCX, XLSX, XLSM, CSV, TSV and text · up to 250 MB</small>}
          </div>
          {uploadStage && (
            <div className="upload-pipeline" aria-live="polite">
              {['Upload', 'Extract', 'Embed', 'Index', 'Ready'].map((label, index) => (
                <span key={label} className={index <= uploadStage.step ? 'active' : ''}>
                  <i>{index < uploadStage.step ? <Check size={10} /> : index + 1}</i>
                  {label}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="simple-files">
          {visibleFiles.map(file => {
            const meta = embeddingMeta(file);
            return (
              <article key={file.id}>
                <div className="file-icon"><FileText /></div>
                <div>
                  <h3>{file.name}</h3>
                  <p>{fileMetaLine(file)} · {displayTime(file.created_at)}</p>
                  <span className={`embedding-badge ${meta.status}`} title={meta.detail}>
                    <Database size={11} /> {meta.label}
                  </span>
                </div>
                <button
                  className="icon-button delete-button"
                  onClick={() => requestDeleteFile(file)}
                  aria-label={`Delete ${file.name}`}
                >
                  <Trash2 size={16} />
                </button>
              </article>
            );
          })}
          {!visibleFiles.length && (
            <div className="store-empty">
              <Upload size={24} />
              <h3>No files yet</h3>
              <p>Upload a document or spreadsheet to make it available in Explore.</p>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="page inner-page">
      <div className="inner-title">
        <div>
          <span className="kicker">LIBRARY</span>
          <h1>Your stores</h1>
          <p>Create a store, then add the files you want {BRAND.name} to understand.</p>
          {query && <p className="filter-note">Showing stores matching “{query}”</p>}
        </div>
        <button className="new-button" onClick={openCreate}><Plus size={17} /> New store</button>
      </div>
      <div className="stores-grid">
        {visibleStores.map(store => (
          <article className="store-card" key={store.id}>
            <button className="store-open" onClick={() => setActiveStore(store)}>
              <span className={`store-folder ${store.color}`}><Folder size={23} /></span>
              <span>
                <strong>{store.title}</strong>
                <small>{store.count} {store.count === 1 ? 'file' : 'files'}</small>
              </span>
            </button>
            <button
              className="store-delete icon-button"
              onClick={() => requestDeleteStore(store)}
              aria-label={`Delete ${store.title}`}
            >
              <Trash2 size={16} />
            </button>
          </article>
        ))}
        <button className="store-card create-store" onClick={openCreate}>
          <span className="store-folder"><Plus size={22} /></span>
          <span><strong>Create a store</strong><small>Organize a new topic</small></span>
        </button>
      </div>
    </div>
  );
}

function CollapsibleSources({ sources, index, isExpanded, onToggle, onOpenStore, model, provider, llmHits = 0, webQueries = 0 }) {
  const panelRef = useRef(null);
  const webSources = sources.filter(source => source.store_id === 0);
  const fileSources = sources.filter(source => source.store_id !== 0);
  const sourceDomain = source => {
    const candidates = [
      source.url,
      source.source_url,
      source.link,
      source.domain,
      source.engine && String(source.engine).includes('.') ? source.engine : '',
      source.name,
    ].filter(Boolean);
    const domainPattern = /(?:https?:\/\/)?(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)(?:[/:?#]|$)/i;
    for (const candidate of candidates) {
      const value = String(candidate).trim();
      if (!value) continue;
      const match = value.match(domainPattern);
      if (match?.[1]) return match[1].replace(/^www\./, '');
    }
    try {
      return source.url ? new URL(source.url).hostname.replace(/^www\./, '') : '';
    } catch {
      return source.url?.replace(/^https?:\/\//, '').split('/')[0] || '';
    }
  };
  const sourceHref = source => source.url || source.source_url || source.link || '';
  const faviconUrl = source => {
    const domain = sourceDomain(source);
    return domain ? `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=32` : '';
  };
  const sourceInitial = source => (sourceDomain(source) || source.name || 'W')[0].toUpperCase();
  const truncated = (text, max = 120) => text?.length > max ? text.slice(0, max) + '…' : text || '';

  useEffect(() => {
    if (isExpanded && panelRef.current) {
      panelRef.current.focus();
    }
  }, [isExpanded]);

  useEffect(() => {
    if (!isExpanded) return;
    const handleEsc = (e) => { if (e.key === 'Escape') onToggle(); };
    document.addEventListener('keydown', handleEsc);
    return () => document.removeEventListener('keydown', handleEsc);
  }, [isExpanded, onToggle]);

  const total = sources.length;
  const displaySources = [...webSources, ...fileSources];
  const maxAvatars = 8;

  return (
    <>
      <div className="sources-bar">
        <button className="sources-bar-btn" onClick={onToggle}>
          <span className="sources-count">{total} source{total !== 1 ? 's' : ''}</span>
          <span className="sources-avatars">
            {displaySources.slice(0, maxAvatars).map((source, i) => (
              source.store_id === 0 ? (
                <span key={source.id || i} className="source-avatar web" title={sourceDomain(source)}>
                  {faviconUrl(source) && (
                    <img
                      src={faviconUrl(source)}
                      alt=""
                      width="14"
                      height="14"
                      onError={e => { e.target.style.display = 'none'; e.target.nextSibling.style.display = 'flex'; }}
                    />
                  )}
                  <span className="source-avatar-fallback" style={{ display: faviconUrl(source) ? 'none' : 'flex' }}>{sourceInitial(source)}</span>
                </span>
              ) : (
                <span key={source.id || i} className="source-avatar file" title={source.name}>
                  <FileText size={10} />
                </span>
              )
            ))}
            {total > maxAvatars && <span className="source-avatar overflow">+{total - maxAvatars}</span>}
          </span>
          <ArrowRight size={14} className="sources-arrow" />
        </button>
      </div>

      {isExpanded && (
        <>
          <div className="sources-panel-overlay" onClick={onToggle} />
          <div className="sources-panel" ref={panelRef} tabIndex={-1}>
            <div className="sources-panel-header">
              <div>
                <h3>References</h3>
                <p>View all references for this response</p>
              </div>
              <button className="sources-panel-close" onClick={onToggle} aria-label="Close references">
                <X size={18} />
              </button>
            </div>

            <div className="sources-panel-body">
              {model && provider && (
                <div className="sources-panel-section">
                  <div className="sources-panel-section-head">
                    <BrainCircuit size={13} />
                    <span>LLM ({llmHits} hit{llmHits === 1 ? '' : 's'})</span>
                  </div>
                  <div className="sources-panel-card llm">
                    <span className="sources-panel-favicon llm"><BrainCircuit size={14} /></span>
                    <div className="sources-panel-card-body">
                      <span className="sources-panel-card-domain">{PROVIDER_LABELS[provider] || provider}</span>
                      <span className="sources-panel-card-title">{model}</span>
                    </div>
                  </div>
                </div>
              )}

              {webSources.length > 0 && (
                <div className="sources-panel-section">
                  <div className="sources-panel-section-head">
                    <Globe size={13} />
                    <span>Web ({webQueries || webSources.length})</span>
                  </div>
                  {webSources.map((source, i) => {
                    const href = sourceHref(source);
                    const CardTag = href ? 'a' : 'div';
                    return (
                      <CardTag key={source.id || i} className="sources-panel-card web" href={href || undefined} target={href ? '_blank' : undefined} rel={href ? 'noopener noreferrer' : undefined}>
                        <span className="sources-panel-favicon web">
                          {faviconUrl(source) && (
                            <img
                              src={faviconUrl(source)}
                              alt=""
                              width="16"
                              height="16"
                              onError={e => { e.target.style.display = 'none'; e.target.nextSibling.style.display = 'flex'; }}
                            />
                          )}
                          <span className="sources-panel-favicon-fallback" style={{ display: faviconUrl(source) ? 'none' : 'flex' }}>{sourceInitial(source)}</span>
                        </span>
                        <div className="sources-panel-card-body">
                          <span className="sources-panel-card-domain">{sourceDomain(source) || 'Web source'}</span>
                          <span className="sources-panel-card-title">{source.name}</span>
                          {source.excerpt && <span className="sources-panel-card-excerpt">{truncated(source.excerpt, 160)}</span>}
                        </div>
                      </CardTag>
                    );
                  })}
                </div>
              )}

              {fileSources.length > 0 && (
                <div className="sources-panel-section">
                  <div className="sources-panel-section-head">
                    <FileText size={13} />
                    <span>Files ({fileSources.length})</span>
                  </div>
                  {fileSources.map((source, i) => (
                    <button key={source.id || i} className="sources-panel-card file" onClick={() => onOpenStore(source.store_id)}>
                      <span className="sources-panel-favicon file"><FileText size={13} /></span>
                      <div className="sources-panel-card-body">
                        <span className="sources-panel-card-domain">Local file</span>
                        <span className="sources-panel-card-title">{source.name}</span>
                        {source.excerpt && <span className="sources-panel-card-excerpt">{truncated(source.excerpt, 160)}</span>}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </>
  );
}

const SLASH_COMMANDS = [
  { id: 'light', label: '/light', desc: 'Fast direct chat — default mode', icon: Radio, color: '#7c6cff' },
  { id: 'unrestricted', label: '/unrestricted', desc: 'Expert mode — direct, low-fluff answers', icon: Zap, color: '#ff6b6b' },
  { id: 'thinking', label: '/thinking', desc: 'Deep analysis — inspects all selected content', icon: Sparkles, color: '#a78bfa' },
  { id: 'deep_summary', label: '/deepsummary', desc: 'Complete section-by-section doc coverage', icon: BookOpen, color: '#60a5fa' },
  { id: 'ticket_analysis', label: '/ticketanalysis', desc: 'Group incidents by problem pattern', icon: Database, color: '#34d399' },
];

const AUTO_WEB_SEARCH_PATTERNS = [
  /\b(search|browse|look\s*up|google|find\s+(?:me\s+)?(?:latest|current|recent|news|online|web|internet))\b/i,
  /\b(latest|current|recent|today|yesterday|this\s+week|this\s+month|news|breaking|updates?)\b/i,
  /\b(youtube|video|videos)\b/i,
  /\b(source|sources|citation|citations|link|links|url|website|webpage)\b/i,
  // Sports
  /\b(cricket|football|soccer|tennis|basketball|match|score|live\s+score|result|ipl|epl|nba|nfl)\b/i,
  // Stock/Finance
  /\b(stock|share|shares|nse|bse|sensex|nifty|mutual\s+fund|ipo|dividend|trading|portfolio)\b/i,
  // Currency
  /\b(currency|exchange\s+rate|forex|dollar|euro|pound|rupee|usd|eur|gbp|inr)\b/i,
  // Flight
  /\b(flight|airline|airport|pnr|boarding|departure|arrival|delayed)\b/i,
  // Food
  /\b(recipe|recipes|cook|cooking|restaurant|cafe|menu|ingredients)\b/i,
  // Health
  /\b(symptom|symptoms|treatment|medicine|diagnosis|disease|doctor|hospital)\b/i,
  // Entertainment
  /\b(movie|movies|film|cinema|series|netflix|concert|album|song|music)\b/i,
  // Mixed-language current-query keywords
  /\b(barish|barsaat|mausam|tapman|garmi|thand|sardi|toofan|aandhi|kohra|dhund)\b/i,
  /\b(aaj|kal|abhi|taza|samachar|khabar|score|natija|result|bhav|kimat|dam)\b/i,
  /\b(cricket|football|match|khel|maukka)\b/i,
  /\b(stock|share|bazaar|bhav|nivesh|munafa)\b/i,
  /\b(dollar|rupaye|exchange|currency|kitna)\b/i,
  /\b(flight|hawai|pnr)\b/i,
  /\b(recipe|pakwan|khaana|restaurant)\b/i,
  /\b(bimari|dawa|ilaj|doctor|hospital|bukhar)\b/i,
  /\b(movie|film|cinema|gaana|concert)\b/i,
  /\b(hoga|hogi|hoga\s+kya|batao|dikhao|btao|konsa|kaunsa|kaisa|kaise)\b/i,
  /\b(sasta|mehnga|kharid|accha|badhiya|sabse)\b/i,
  /\b(comp(?:are|aire?)|vs\.?|versus|difference\s+between|contras?t)\b/i,
  /\b(better|worse|best|worst|which\s+(?:one|is|should|do)|recommend(?:ed|ation)?|suggestion|pros?\s+and\s+cons?)\b/i,
];

const shouldAutoWebSearch = (text, mode = 'light') => {
  if (['ticket_analysis', 'deep_summary'].includes(mode)) return false;
  const normalized = String(text || '').replace(/\s+/g, ' ').trim();
  return Boolean(normalized) && AUTO_WEB_SEARCH_PATTERNS.some(pattern => pattern.test(normalized));
};

function ExplorePage({
  files, stores, chats, jobs, createChatJob, markJobSeen, initialChatId, clearInitialChat, onOpenStore, toast, requestDeleteChat,
  requestDeleteAllChats, hasActiveJobs, refreshChats, refreshJobs, openMenu, newChatSignal,
}) {
  const savedAiPreference = readSavedAiPreference();
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState([]);
  const [activeChat, setActiveChat] = useState(null);
  const [model, setModel] = useState(savedAiPreference.model || DEFAULT_PROVIDER_MODELS[savedAiPreference.provider] || DEFAULT_PROVIDER_MODELS.ollama);
  const [provider, setProvider] = useState(savedAiPreference.provider || 'ollama');
  const [llmConfig, setLlmConfig] = useState(null);
  const [allowGeneralKnowledge, setAllowGeneralKnowledge] = useState(true);
  const [reasoningMode, setReasoningMode] = useState(savedAiPreference.reasoning_mode === 'web_research' ? 'light' : (savedAiPreference.reasoning_mode || 'light'));
  const [webSourceLimit] = useState(savedAiPreference.web_source_limit || 200);
  const [selectedFileIds, setSelectedFileIds] = useState([]);
  const [selectFilesOpen, setSelectFilesOpen] = useState(false);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState(null);
  const [copiedConvId, setCopiedConvId] = useState(false);
  const [expandedSources, setExpandedSources] = useState({});
  const [slashOpen, setSlashOpen] = useState(false);
  const [slashIndex, setSlashIndex] = useState(-1);
  const [slashFilter, setSlashFilter] = useState('');
  const [directStreaming, setDirectStreaming] = useState(false);
  const [modePickerOpen, setModePickerOpen] = useState(false);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [railOpen, setRailOpen] = useState(false);
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);
  const [followups, setFollowups] = useState({ key: null, items: [], loading: false });
  const threadRef = useRef(null);
  const composerRef = useRef(null);
  const loadedCompletedJob = useRef(null);
  const aiPreferenceReady = useRef(false);
  const revealTimerRef = useRef(null);
  const directAbortRef = useRef(null);
  const stopRequestedRef = useRef(false);
  const modePickerRef = useRef(null);
  const optionsPopoverRef = useRef(null);

  useEffect(() => {
    if (!modePickerOpen) return undefined;
    const onPointerDown = event => {
      if (modePickerRef.current && !modePickerRef.current.contains(event.target)) setModePickerOpen(false);
    };
    window.addEventListener('mousedown', onPointerDown);
    return () => window.removeEventListener('mousedown', onPointerDown);
  }, [modePickerOpen]);

  useEffect(() => {
    if (!optionsOpen) return undefined;
    const onPointerDown = event => {
      if (optionsPopoverRef.current && !optionsPopoverRef.current.contains(event.target)) setOptionsOpen(false);
    };
    window.addEventListener('mousedown', onPointerDown);
    return () => window.removeEventListener('mousedown', onPointerDown);
  }, [optionsOpen]);

  const toggleSources = (messageIndex) => {
    setExpandedSources(prev => ({ ...prev, [messageIndex]: !prev[messageIndex] }));
  };
  const selectedCount = selectedFileIds === null ? files.length : selectedFileIds.length;
  const activeJob = jobs.find(job => job.conversation_id === activeChat && ['queued', 'running'].includes(job.status));
  const thinking = Boolean(activeJob) || directStreaming;
  const readyCount = jobs.filter(job => job.status === 'completed' && !job.seen).length;
  const runningCount = jobs.filter(job => ['queued', 'running'].includes(job.status)).length;
  const failedCount = jobs.filter(job => job.status === 'failed').length;
  const sessionTokens = messages.reduce((sum, message) => sum + (message.totalTokens || 0), 0);
  const sessionLlmHits = messages.reduce((sum, message) => sum + (message.llmHits || 0), 0);

  const formatChatTime = ts => {
    const d = new Date(ts.replace(' ', 'T') + 'Z');
    const now = new Date();
    const diffMs = now - d;
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'now';
    if (diffMins < 60) return `${diffMins}m`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h`;
    return `${Math.floor(diffHours / 24)}d`;
  };

  const getReasoningMode = (text) => {
    for (const cmd of SLASH_COMMANDS) {
      const prefix = cmd.label + ' ';
      const label = cmd.label;
      if (text.startsWith(prefix) || text === label) return cmd.id;
    }
    return reasoningMode;
  };

  const previewReasoningMode = getReasoningMode(question.trim());
  const autoWebSearchPreview = shouldAutoWebSearch(question.trim().replace(/^\/\w+\s*/, ''), previewReasoningMode);
  const activeModeLabel = previewReasoningMode === 'light' ? 'Light'
    : previewReasoningMode === 'unrestricted' ? 'Unrestricted'
    : previewReasoningMode === 'thinking' ? 'Thinking'
    : previewReasoningMode === 'deep_summary' ? 'Deep Summary'
    : previewReasoningMode === 'ticket_analysis' ? 'Ticket Analysis'
    : previewReasoningMode === 'web_research' ? 'Web Research'
    : previewReasoningMode;
  const displayedModeLabel = autoWebSearchPreview
    ? `${activeModeLabel} + Auto Web`
    : activeModeLabel;

  useEffect(() => {
    if (activeChat) {
      window.localStorage.setItem(ACTIVE_CHAT_STORAGE_KEY, String(activeChat));
    }
  }, [activeChat]);

  useEffect(() => {
    Promise.all([
      api.llmConfig(),
      api.preference('explore_ai').catch(() => ({ value: {} })),
    ]).then(([config, preference]) => {
      setLlmConfig(config);
      const saved = { ...readSavedAiPreference(), ...(preference.value || {}) };
      const nextProvider = saved.provider || config.provider || 'ollama';
      const nextModel = saved.model || (nextProvider === config.provider ? config.model : DEFAULT_PROVIDER_MODELS[nextProvider]);
      setProvider(nextProvider);
      setModel(nextModel);
      setReasoningMode(saved.reasoning_mode === 'web_research' ? 'light' : (saved.reasoning_mode || 'light'));
      aiPreferenceReady.current = true;
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!aiPreferenceReady.current) return undefined;
    const payload = {
      provider,
      model,
      reasoning_mode: reasoningMode,
      web_source_limit: webSourceLimit,
    };
    window.localStorage.setItem(AI_PREFERENCE_STORAGE_KEY, JSON.stringify(payload));
    const timer = window.setTimeout(() => {
      api.updatePreference('explore_ai', payload).catch(() => {});
    }, 300);
    return () => window.clearTimeout(timer);
  }, [provider, model, reasoningMode, webSourceLimit]);

  useEffect(() => {
    setSelectedFileIds(current => current === null ? null : current.filter(id => files.some(file => file.id === id)));
  }, [files]);

  const toggleFile = id => {
    setSelectedFileIds(current => {
      const selected = current === null ? files.map(file => file.id) : current;
      return selected.includes(id) ? selected.filter(fileId => fileId !== id) : [...selected, id];
    });
  };

  const messageFromSaved = message => {
    const rawSources = message.sources || [];
    const meta = rawSources.find(s => s.meta);
    return {
      id: message.id,
      role: message.role,
      text: message.content,
      sources: rawSources.filter(s => !s.meta),
      llmHits: meta?.llm_hits || message.llm_hits || 0,
      webQueries: meta?.web_queries || message.web_queries || 0,
      promptTokens: meta?.prompt_tokens || message.prompt_tokens || 0,
      completionTokens: meta?.completion_tokens || message.completion_tokens || 0,
      totalTokens: meta?.total_tokens || message.total_tokens || 0,
      model: message.model,
      provider: message.provider,
      createdAt: message.created_at,
    };
  };

  const stopReveal = () => {
    if (revealTimerRef.current) {
      window.clearInterval(revealTimerRef.current);
      revealTimerRef.current = null;
    }
  };

  const revealAssistantMessage = saved => {
    const restored = saved.map(messageFromSaved);
    const assistantIndex = restored.findLastIndex(message => message.role === 'assistant' && message.text);
    if (assistantIndex === -1) {
      setMessages(restored);
      return;
    }
    stopReveal();
    const fullText = restored[assistantIndex].text;
    const chunkSize = Math.max(6, Math.ceil(fullText.length / 220));
    let visibleChars = 0;
    setMessages(restored.map((message, index) => index === assistantIndex
      ? { ...message, text: '', sources: [], streaming: true }
      : message));
    revealTimerRef.current = window.setInterval(() => {
      visibleChars = Math.min(fullText.length, visibleChars + chunkSize);
      setMessages(current => current.map((message, index) => index === assistantIndex
        ? {
            ...restored[assistantIndex],
            text: fullText.slice(0, visibleChars),
            sources: visibleChars >= fullText.length ? restored[assistantIndex].sources : [],
            streaming: visibleChars < fullText.length,
          }
        : message));
      if (visibleChars >= fullText.length) {
        window.clearInterval(revealTimerRef.current);
        revealTimerRef.current = null;
      }
    }, 16);
  };

  const openChat = async chat => {
    setRailOpen(false);
    stopReveal();
    const saved = await api.chatMessages(chat.id);
    const latestJob = jobs.find(job => job.conversation_id === chat.id);
    setSelectedFileIds(latestJob?.file_ids ?? []);
    setActiveChat(chat.id);
    const restored = saved.map(messageFromSaved);
    if (latestJob && !restored.some(message => message.role === 'user' && message.text === latestJob.question)) {
      restored.push({ id: 'temp-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6), role: 'user', text: latestJob.question });
    }
    if (latestJob?.status === 'failed') {
      restored.push({ role: 'assistant', text: jobFailureMessage(latestJob), sources: [], error: true, jobId: latestJob.id });
    }
    loadedCompletedJob.current = latestJob?.id || null;
    setMessages(restored);
    jobs.filter(job => job.conversation_id === chat.id && job.status === 'completed' && !job.seen).forEach(job => markJobSeen(job.id));
  };

  useEffect(() => {
    if (!initialChatId || !chats.length) return;
    const chat = chats.find(item => item.id === initialChatId);
    if (chat) openChat(chat);
    clearInitialChat();
  }, [initialChatId, chats]);

  useEffect(() => {
    if (initialChatId || activeChat || !chats.length) return;
    const savedChatId = Number(readStorage('explore-active-chat'));
    if (!savedChatId) return;
    const chat = chats.find(item => item.id === savedChatId);
    if (chat) openChat(chat);
  }, [initialChatId, activeChat, chats]);

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, thinking, activeJob?.detail, directStreaming]);

  useEffect(() => {
    const el = threadRef.current;
    if (!el) return undefined;
    const onScroll = () => {
      const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      setShowScrollToBottom(distanceFromBottom > 240);
    };
    el.addEventListener('scroll', onScroll);
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  const scrollToBottom = () => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight, behavior: 'smooth' });
  };

  useEffect(() => () => {
    stopReveal();
  }, []);

  useEffect(() => {
    const finished = jobs.find(job => job.conversation_id === activeChat && ['completed', 'failed'].includes(job.status));
    if (!finished || loadedCompletedJob.current === finished.id) return;
    loadedCompletedJob.current = finished.id;
    if (finished.status === 'failed') {
      const reason = jobFailureMessage(finished);
      setMessages(current => current.some(message => message.jobId === finished.id)
        ? current
        : [...current, { role: 'assistant', text: reason, sources: [], error: true, jobId: finished.id }]);
      toast(reason, 'error');
      return;
    }
    api.chatMessages(activeChat).then(saved => {
      revealAssistantMessage(saved);
      if (!finished.seen) markJobSeen(finished.id);
    });
  }, [jobs, activeChat, markJobSeen]);

  useEffect(() => {
    const last = messages[messages.length - 1];
    if (!last || last.role !== 'assistant' || last.streaming || last.error || !last.text) {
      setFollowups(current => (current.key === null ? current : { key: null, items: [], loading: false }));
      return;
    }
    const key = last.id ?? last.streamId ?? messages.length - 1;
    if (followups.key === key) return;
    const priorUser = [...messages.slice(0, messages.length - 1)].reverse().find(item => item.role === 'user');
    if (!priorUser) {
      setFollowups({ key, items: [], loading: false });
      return;
    }
    setFollowups({ key, items: [], loading: true });
    api.chatSuggestions(priorUser.text, last.text, provider, model)
      .then(result => setFollowups(current => (current.key === key ? { key, items: result.suggestions || [], loading: false } : current)))
      .catch(() => setFollowups(current => (current.key === key ? { key, items: [], loading: false } : current)));
  }, [messages]);

  const askSuggestion = (text) => {
    setFollowups({ key: null, items: [], loading: false });
    ask(text);
  };

  const newChat = () => {
    setRailOpen(false);
    stopReveal();
    setActiveChat(null);
    window.localStorage.removeItem(ACTIVE_CHAT_STORAGE_KEY);
    setMessages([]);
    setQuestion('');
    setSelectedFileIds([]);
  };

  useEffect(() => {
    if (newChatSignal) newChat();
  }, [newChatSignal]);

  const stripSlashPrefix = (text) => {
    for (const cmd of SLASH_COMMANDS) {
      const prefix = cmd.label;
      if (text === prefix) return '';
      if (text.startsWith(prefix + ' ')) return text.slice(prefix.length + 1);
    }
    return text;
  };

  const ask = async (text) => {
    stopReveal();
    const value = text.trim();
    if (!value) return;
    const mode = getReasoningMode(value);
    const cleanText = stripSlashPrefix(value);
    if (!cleanText) { toast('Ask a question', 'error'); return; }
    const effectiveWebSearch = shouldAutoWebSearch(cleanText, mode);
    if (mode === 'ticket_analysis' && (selectedFileIds === null || selectedFileIds.length !== 1)) {
      toast('Ticket Analysis requires exactly one selected ticket file', 'error');
      setSelectFilesOpen(true);
      return;
    }
    setQuestion('');
    resizeTextarea(composerRef.current);
    const canDirectStream = false;
    if (canDirectStream) {
      const streamId = crypto.randomUUID();
      const controller = new AbortController();
      let streamedChars = 0;
      let sawFirstToken = false;
      stopRequestedRef.current = false;
      directAbortRef.current = controller;
      const baseActivity = [
        { id: 'request', label: 'Sending request', detail: `${PROVIDER_LABELS[provider] || provider} · ${model}`, state: 'live' },
        { id: 'connect', label: 'Connecting model', detail: 'Waiting for first token', state: 'pending' },
        { id: 'stream', label: 'Streaming answer', detail: 'Preparing response', state: 'pending' },
        { id: 'save', label: 'Saving chat', detail: 'History will update after completion', state: 'pending' },
      ];
      setDirectStreaming(true);
      setMessages(current => [
        ...current,
        { id: 'temp-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6), role: 'user', text: cleanText },
        { role: 'assistant', text: '', sources: [], model, provider, streaming: true, streamId, activity: baseActivity },
      ]);
      try {
        const result = await api.directChatStream(cleanText, activeChat, provider, model, allowGeneralKnowledge, mode, event => {
          if (event.type === 'start') {
            setActiveChat(event.conversation_id);
            setMessages(current => current.map(message => message.streamId === streamId
              ? {
                  ...message,
                  activity: baseActivity.map(item => item.id === 'request'
                    ? { ...item, state: 'done', detail: 'Request accepted' }
                    : item.id === 'connect'
                      ? { ...item, state: 'live', detail: `Connected to ${PROVIDER_LABELS[event.provider] || event.provider || provider}` }
                      : item),
                }
              : message));
          }
          if (event.type === 'token') {
            streamedChars += event.text.length;
            sawFirstToken = true;
            setMessages(current => current.map(message => message.streamId === streamId
              ? {
                  ...message,
                  text: `${message.text || ''}${event.text}`,
                  streaming: true,
                  activity: baseActivity.map(item => {
                    if (item.id === 'request') return { ...item, state: 'done', detail: 'Request accepted' };
                    if (item.id === 'connect') return { ...item, state: 'done', detail: 'First token received' };
                    if (item.id === 'stream') return { ...item, state: 'live', detail: `${streamedChars.toLocaleString()} characters received` };
                    return item;
                  }),
                }
              : message));
          }
          if (event.type === 'result') {
            setMessages(current => current.map(message => message.streamId === streamId
              ? {
                  ...message,
                  text: event.data.answer,
                  sources: (event.data.sources || []).filter(s => !s.meta),
                  llmHits: event.data.llm_hits || 1,
                  webQueries: event.data.web_queries || 0,
                  promptTokens: event.data.prompt_tokens || 0,
                  completionTokens: event.data.completion_tokens || 0,
                  totalTokens: event.data.total_tokens || 0,
                  model: event.data.model,
                  provider,
                  streaming: false,
                  activity: [
                    { id: 'request', label: 'Request sent', detail: 'Accepted by backend', state: 'done' },
                    { id: 'connect', label: 'Model connected', detail: sawFirstToken ? 'Tokens streamed live' : 'Response completed', state: 'done' },
                    { id: 'stream', label: 'Answer received', detail: `${event.data.answer.length.toLocaleString()} characters`, state: 'done' },
                    { id: 'save', label: 'Saved to chat', detail: 'History is up to date', state: 'done' },
                    ...(message.activity || []).filter(item => item.id.startsWith('diagnostic-')),
                  ],
                }
              : message));
          }
          if (event.type === 'diagnostic') {
            setMessages(current => current.map(message => message.streamId === streamId
              ? {
                  ...message,
                  activity: [
                    ...(message.activity || []),
                    { id: `diagnostic-${Date.now()}`, label: 'Model constraint', detail: event.detail, state: 'failed' },
                  ],
                }
              : message));
          }
        }, { signal: controller.signal });
        setActiveChat(result.conversation_id);
        const saved = await api.chatMessages(result.conversation_id);
        setMessages(saved.map(messageFromSaved));
        await refreshChats?.();
      } catch (error) {
        if (stopRequestedRef.current || error.name === 'AbortError') {
          setMessages(current => current.map(message => message.streamId === streamId
            ? {
                ...message,
                text: message.text || 'Stopped.',
                streaming: false,
                activity: [
                  ...(message.activity || []).filter(item => item.state === 'done'),
                  { id: 'stopped', label: 'Stopped', detail: 'Answer stopped by user', state: 'failed' },
                ],
              }
            : message));
          return;
        }
        setMessages(current => current.map(message => message.streamId === streamId
          ? {
              ...message,
              text: message.text || error.message,
              sources: [],
              error: true,
              streaming: false,
              activity: [
                { id: 'request', label: 'Stream stopped', detail: error.message, state: 'failed' },
              ],
            }
          : message));
        toast(error.message, 'error');
      } finally {
        setDirectStreaming(false);
        directAbortRef.current = null;
      }
      return;
    }
      const tempId = 'temp-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6);
      setMessages(current => [...current, { id: tempId, role: 'user', text: cleanText }]);
      try {
        const job = await createChatJob(cleanText, activeChat, provider, model, allowGeneralKnowledge, mode, selectedFileIds, webSourceLimit, effectiveWebSearch);
        setActiveChat(job.conversation_id);
      } catch (error) {
        setMessages(current => [...current, { role: 'assistant', text: error.message, sources: [] }]);
        toast(error.message, 'error');
      }
  };

  const stopAnswer = async () => {
    stopRequestedRef.current = true;
    directAbortRef.current?.abort();
    setDirectStreaming(false);
    try {
      if (activeJob) {
        await api.cancelChatJob(activeJob.id);
      } else if (activeChat) {
        await api.stopChat(activeChat);
      }
      if (activeChat) {
        const saved = await api.chatMessages(activeChat).catch(() => null);
        if (saved) setMessages(saved.map(messageFromSaved));
      }
      await refreshJobs?.();
      await refreshChats?.();
    } catch (error) {
      toast(error.message, 'error');
      return;
    }
    setMessages(current => current.map(message => message.streaming
      ? { ...message, text: message.text || 'Stopped.', streaming: false }
      : message));
    toast('Stopped. You can switch model and ask again.', 'success');
  };

  const truncateFromMessage = async (message) => {
    if (!activeChat || !message.id) return null;
    stopReveal();
    const saved = await api.truncateChatFromMessage(activeChat, message.id);
    setMessages(saved.map(messageFromSaved));
    await Promise.all([refreshChats?.(), refreshJobs?.()]);
    loadedCompletedJob.current = null;
    return saved;
  };

  const editMessage = async (message) => {
    if (thinking || message.role !== 'user') return;
    try {
      if (message.id && !String(message.id).startsWith('temp-')) {
        await truncateFromMessage(message);
      }
      setQuestion(message.text);
      window.setTimeout(() => {
        composerRef.current?.focus();
        resizeTextarea(composerRef.current);
      }, 0);
    } catch (error) {
      toast(error.message, 'error');
    }
  };

  const askAgain = async (message, index) => {
    if (thinking) return;
    let promptMessage = message;
    let promptIndex = index;
    if (message.role !== 'user') {
      const userEntry = [...messages.slice(0, index).entries()].reverse().find(([, item]) => item.role === 'user');
      if (!userEntry) return;
      [promptIndex, promptMessage] = userEntry;
    }
    try {
      if (promptMessage.id && !String(promptMessage.id).startsWith('temp-')) {
        await truncateFromMessage(promptMessage);
      } else {
        setMessages(current => current.slice(0, promptIndex));
      }
      await ask(promptMessage.text);
    } catch (error) {
      toast(error.message, 'error');
    }
  };

  const applySlashCommand = (cmd) => {
    setQuestion(cmd.label + ' ');
    setReasoningMode(cmd.id);
    setSlashOpen(false);
    setSlashIndex(-1);
    composerRef.current?.focus();
  };

  const handleComposerInput = (event) => {
    const val = event.target.value;
    setQuestion(val);
    resizeTextarea(event.target);
    if (val.match(/^\/(\w*)$/) && val.length > 0) {
      const partial = val.slice(1).toLowerCase();
      const matches = SLASH_COMMANDS.filter(c => c.label.slice(1).toLowerCase().startsWith(partial));
      if (matches.length > 0) {
        setSlashFilter(partial);
        setSlashOpen(true);
        setSlashIndex(0);
        return;
      }
    }
    setSlashOpen(false);
    setSlashIndex(-1);
  };

  const handleComposerKeyDown = (event) => {
    if (slashOpen) {
      const matches = SLASH_COMMANDS.filter(c => c.label.slice(1).toLowerCase().startsWith(slashFilter));
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setSlashIndex(i => Math.min(i + 1, matches.length - 1));
        return;
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        setSlashIndex(i => Math.max(i - 1, 0));
        return;
      }
      if (event.key === 'Enter' || event.key === 'Tab') {
        event.preventDefault();
        if (matches[slashIndex]) { applySlashCommand(matches[slashIndex]); }
        return;
      }
      if (event.key === 'Escape') {
        setSlashOpen(false);
        setSlashIndex(-1);
        return;
      }
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      ask(question);
    }
  };

  const matchedCommands = slashOpen ? SLASH_COMMANDS.filter(c => c.label.slice(1).toLowerCase().startsWith(slashFilter)) : [];

  const openUpload = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.pdf,.csv,.xlsx,.xls,.md,.txt';
    input.multiple = true;
    input.onchange = async (e) => {
      const fileList = Array.from(e.target.files);
      if (!fileList.length) return;
      const storeId = stores[0]?.id;
      if (!storeId) { toast('Create a store in Library first', 'error'); return; }
      let count = 0;
      for (const file of fileList) {
        try {
          const uploaded = await api.uploadFile(storeId, file);
          const fid = uploaded?.id || uploaded?.file?.id;
          if (fid) {
            setSelectedFileIds(cur => cur ? [...cur, fid] : [fid]);
            count++;
          }
        } catch { /* skip failed */ }
      }
      if (count) toast(`Uploaded ${count} file${count > 1 ? 's' : ''}`, 'success');
      else toast('Upload failed', 'error');
    };
    input.click();
  };

  const copyAnswer = async (text, index) => {
    await navigator.clipboard.writeText(text);
    setCopiedIndex(index);
    toast('Answer copied', 'success');
    window.setTimeout(() => setCopiedIndex(null), 1500);
  };

  const copyConversationId = async () => {
    if (!activeChat) return;
    const chat = chats.find(item => item.id === activeChat);
    const title = chat?.title || 'Untitled conversation';
    const statsParts = [
      `${messages.length} message${messages.length === 1 ? '' : 's'}`,
      model ? `${PROVIDER_LABELS[provider] || provider}/${model}` : null,
      sessionTokens > 0 ? `${sessionTokens.toLocaleString()} tokens` : null,
    ].filter(Boolean);
    const recent = messages.filter(message => message.text).slice(-6);
    const omitted = messages.filter(message => message.text).length - recent.length;
    const transcript = recent
      .map(message => `${message.role === 'user' ? 'Q' : 'A'}: ${message.text.length > 600 ? `${message.text.slice(0, 600)}…` : message.text}`)
      .join('\n\n');
    const payload = [
      `Locus conversation #${activeChat} — "${title}"`,
      statsParts.join(' · '),
      omitted > 0 ? `(${omitted} earlier message${omitted === 1 ? '' : 's'} omitted)` : null,
      '',
      transcript,
    ].filter(line => line !== null).join('\n');
    await navigator.clipboard.writeText(payload);
    setCopiedConvId(true);
    toast('Conversation context copied', 'success');
    window.setTimeout(() => setCopiedConvId(false), 1500);
  };

  const detachFile = (id) => {
    setSelectedFileIds(cur => cur ? cur.filter(fid => fid !== id) : []);
  };

  return (
    <div className="explore-shell">
      <aside className={`chat-rail ${railOpen ? 'open' : ''}`}>
        <div className="chat-rail-head">
          <span className="kicker">Chats</span>
          <span className="chat-rail-count">{chats.length}</span>
          {runningCount > 0 && <span className="chat-rail-running">{runningCount} running</span>}
          <button type="button" className="chat-rail-new" onClick={newChat} aria-label="Start a new conversation">
            <Plus size={13} /> New
          </button>
          <button type="button" className="chat-rail-close icon-button" onClick={() => setRailOpen(false)} aria-label="Close chat history">
            <X size={18} />
          </button>
        </div>
        <div className="chat-rail-list">
          {chats.map(chat => {
            const latestJob = jobs.find(j => j.conversation_id === chat.id);
            const inProgress = ['queued', 'running'].includes(latestJob?.status);
            const ready = latestJob?.status === 'completed' && !latestJob.seen;
            const failed = latestJob?.status === 'failed';
            return (
              <div
                key={chat.id}
                role="button"
                tabIndex={0}
                className={`chat-rail-item ${activeChat === chat.id ? 'active' : ''} ${inProgress ? 'in-progress' : ''} ${ready ? 'ready' : ''} ${failed ? 'failed' : ''}`}
                onClick={() => openChat(chat)}
                onKeyDown={e => {
                  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openChat(chat); }
                }}
                title={chat.title}
              >
                <span className="chat-rail-name">
                  <span>{chat.title}</span>
                  {inProgress && <i className="chat-dot progress" />}
                  {ready && <i className="chat-dot ready" />}
                  {failed && <i className="chat-dot failed" />}
                </span>
                <span className="chat-rail-time">{formatChatTime(chat.updated_at)}</span>
                <button
                  type="button"
                  className="chat-rail-delete"
                  onClick={e => { e.stopPropagation(); requestDeleteChat?.(chat, () => { if (activeChat === chat.id) newChat(); }); }}
                  aria-label={`Delete ${chat.title}`}
                >
                  <Trash2 size={12} />
                </button>
              </div>
            );
          })}
          {!chats.length && <span className="chat-rail-empty">No chats yet</span>}
        </div>
        {!!chats.length && (
          <button
            type="button"
            className="chat-rail-delete-all"
            disabled={hasActiveJobs}
            title={hasActiveJobs ? 'Wait for active answers to finish' : 'Delete all chats'}
            onClick={() => requestDeleteAllChats?.(() => newChat())}
          >
            <Trash2 size={13} /> Delete all chats
          </button>
        )}
      </aside>
      {railOpen && <button type="button" className="chat-rail-scrim" aria-label="Close chat history" onClick={() => setRailOpen(false)} />}
      <div className="chat-page">
        <div className="chat-top">
          <div className="chat-top-left">
            <button className="menu-button icon-button" onClick={openMenu} aria-label="Open menu">
              <Menu size={20} />
            </button>
            <button
              type="button"
              className="rail-toggle icon-button"
              onClick={() => setRailOpen(true)}
              aria-label="Show chat history"
            >
              <History size={19} />
              {chats.length > 0 && <span className="rail-toggle-count">{chats.length}</span>}
            </button>
            <span className="workspace-label"><i /> ASK</span>
            <div className="chat-top-info">
              {activeChat && (
                <button
                  className="copy-conv-id-button"
                  onClick={copyConversationId}
                  aria-label="Copy conversation context"
                  title={`Copy conversation #${activeChat} with context`}
                  {...tip('Copy this conversation\'s title, stats, and recent messages so it makes sense wherever you paste it.')}
                >
                  {copiedConvId ? <Check size={14} /> : <Copy size={14} />}
                  <span>{activeChat}</span>
                </button>
              )}
              {sessionTokens > 0 && (
                <span className="chat-session-usage" {...tip('Total tokens and LLM calls used across this conversation')}>
                  <Cpu size={12} />
                  <span>{sessionTokens.toLocaleString()} tokens</span>
                  <span className="chat-session-usage-sep">·</span>
                  <span>{sessionLlmHits} LLM {sessionLlmHits === 1 ? 'hit' : 'hits'}</span>
                </span>
              )}
            </div>
          </div>
          <div className="chat-top-right">
            <button
              className="explore-header-new-chat mobile-only-new-chat"
              onClick={newChat}
              aria-label="New conversation"
            >
              <Plus size={20} />
            </button>
            <div className="desktop-controls">
              <ModelControl config={llmConfig} provider={provider} setProvider={setProvider} model={model} setModel={setModel} />
            </div>
            <div className="options-popover-wrap" ref={optionsPopoverRef}>
              <button
                type="button"
                className="options-toggle icon-button"
                onClick={() => setOptionsOpen(value => !value)}
                aria-label="Model options"
                aria-expanded={optionsOpen}
              >
                <SlidersHorizontal size={18} />
              </button>
              <div className={`options-popover desktop-controls ${optionsOpen ? 'open' : ''}`}>
                <ModelControl config={llmConfig} provider={provider} setProvider={setProvider} model={model} setModel={setModel} />
              </div>
            </div>
          </div>
        </div>

        <div
          ref={threadRef}
          className={`chat-thread ${messages.length ? 'has-messages' : ''}`}
          aria-live="polite"
          aria-relevant="additions"
        >
          {!messages.length && (
            <div className="chat-empty">
              <div className="chat-orb"><Sparkles size={29} /></div>
              <h2>What do you want to ask?</h2>
              <p>Ask directly, attach files, or switch modes when the question needs deeper work.</p>
              {stores.length > 0 && (
                <div className="quick-start-chips">
                  {stores.slice(0, 3).map(store => (
                    <button
                      key={store.id}
                      type="button"
                      className="quick-start-chip"
                      onClick={() => {
                        setQuestion(`What can you tell me about ${store.title}?`);
                        window.setTimeout(() => { composerRef.current?.focus(); resizeTextarea(composerRef.current); }, 0);
                      }}
                    >
                      <Folder size={12} /> Ask about {store.title}
                    </button>
                  ))}
                </div>
              )}
              <div className="slash-hints">
                {SLASH_COMMANDS.map(cmd => {
                  const Icon = cmd.icon;
                  return (
                    <button type="button" key={cmd.id} className="slash-hint" onClick={() => applySlashCommand(cmd)}>
                      <Icon size={13} style={{ color: cmd.color }} />
                      <span className="slash-hint-key">{cmd.label}</span>
                      <span className="slash-hint-desc">{cmd.desc}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          {messages.map((message, index) => (
            <div className={`chat-message ${message.role} ${message.error ? 'error' : ''}`} key={message.id || message.streamId || index}>
              {message.role === 'assistant' && <div className="assistant-avatar"><Sparkles size={15} /></div>}
              <div className="message-body">
                <div className="message-head">
                  <span className="message-head-label">
                    <span>{message.role === 'assistant' ? assistantLabel(message.model, message.provider, PROVIDER_LABELS) : 'You'}</span>
                    {message.role === 'assistant' && message.totalTokens > 0 && (
                      <span className="message-tokens" title={`${message.promptTokens.toLocaleString()} prompt + ${message.completionTokens.toLocaleString()} completion tokens`}>
                        {message.totalTokens.toLocaleString()} tokens
                      </span>
                    )}
                  </span>
                  <div className="message-actions">
                    {message.id && (
                      <>
                        {message.role === 'user' && (
                          <button className="message-action icon-button" type="button" disabled={thinking} onClick={() => editMessage(message)} aria-label="Edit question" title="Edit question">
                            <PenLine size={13} />
                          </button>
                        )}
                        {(message.role === 'user' || message.error) && (
                          <button className="message-action icon-button" type="button" disabled={thinking} onClick={() => askAgain(message, index)} aria-label="Ask again" title="Ask again with current model">
                            <RotateCcw size={13} />
                          </button>
                        )}
                        <button className="copy-button icon-button" type="button" onClick={() => copyAnswer(message.text, index)} aria-label="Copy query" title="Copy query">
                          {copiedIndex === index ? <Check size={14} /> : <Copy size={14} />}
                        </button>
                      </>
                    )}
                  </div>
                </div>
                {message.role === 'assistant' ? (
                  <>
                    <DirectStreamTrace activity={message.activity} model={message.model} provider={message.provider} text={message.text} streaming={message.streaming} />
                    <div className={`markdown-answer ${message.streaming ? 'streaming' : ''}`}><AssistantMarkdown text={message.text} streaming={message.streaming} messageKey={message.id || message.streamId || index} /></div>
                  </>
                ) : (
                  <p>{message.text}</p>
                )}
{message.sources?.length > 0 && (
                    <CollapsibleSources
                      sources={message.sources}
                      index={index}
                      isExpanded={expandedSources[index]}
                      onToggle={() => toggleSources(index)}
                      onOpenStore={onOpenStore}
                      model={message.model}
                      provider={message.provider}
                      llmHits={message.llmHits}
                      webQueries={message.webQueries}
                    />
                  )}
              </div>
            </div>
          ))}
          {!thinking && (followups.loading || followups.items.length > 0) && (
            <div className="chat-suggestions" aria-label="Suggested follow-up questions">
              {followups.loading
                ? Array.from({ length: 3 }).map((_, index) => <span className="chat-suggestion-skeleton" key={index} />)
                : followups.items.map((suggestion, index) => (
                    <button type="button" className="chat-suggestion-chip" key={index} onClick={() => askSuggestion(suggestion)}>
                      <Sparkles size={12} />
                      <span>{suggestion}</span>
                    </button>
                  ))}
            </div>
          )}
          {activeJob && (
            <PipelineActivity
              pipeline={{ stage: activeJob.stage, detail: activeJob.detail }}
              model={activeJob.model}
              provider={activeJob.provider}
              events={activeJob.events || []}
              startedAt={parseServerTime(activeJob.created_at)}
              reasoningMode={activeJob.reasoning_mode}
              webSearch={activeJob.web_search}
              fileCount={activeJob.file_ids === null ? files.length : (activeJob.file_ids?.length ?? selectedCount)}
              question={activeJob.question}
              liveLlmHits={activeJob.llm_hits}
              liveWebQueries={activeJob.web_queries}
              liveTotalTokens={activeJob.total_tokens}
            />
          )}
          {activeJob?.partial_answer && (
            <div className="chat-message assistant">
              <div className="assistant-avatar"><Sparkles size={15} /></div>
              <div className="message-body">
                <div className="markdown-answer streaming">
                  <AssistantMarkdown text={activeJob.partial_answer} streaming messageKey={`job-${activeJob.id}`} />
                </div>
              </div>
            </div>
          )}
        </div>

        {showScrollToBottom && (
          <button type="button" className="scroll-to-bottom-btn" onClick={scrollToBottom} aria-label="Scroll to latest message">
            <ChevronDown size={14} /> New messages
          </button>
        )}

        <form
          className="chat-composer"
          onSubmit={event => { event.preventDefault(); ask(question); }}
        >
          {slashOpen && matchedCommands.length > 0 && (
            <div className="slash-popup">
              {matchedCommands.map((cmd, i) => {
                const Icon = cmd.icon;
                return (
                  <button
                    type="button"
                    className={`slash-item ${i === slashIndex ? 'selected' : ''}`}
                    key={cmd.id}
                    onMouseDown={e => { e.preventDefault(); applySlashCommand(cmd); }}
                    onMouseEnter={() => setSlashIndex(i)}
                  >
                    <Icon size={14} style={{ color: cmd.color }} />
                    <div className="slash-info">
                      <span className="slash-name">{cmd.label}</span>
                      <span className="slash-desc">{cmd.desc}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
          <div className="composer-tools">
            <div className="composer-tools-group">
              <div className={`mode-picker ${modePickerOpen ? 'open' : ''}`} ref={modePickerRef}>
                <button
                  type="button"
                  className={`composer-tool-btn mode-picker-trigger mode-${previewReasoningMode}`}
                  onClick={() => setModePickerOpen(v => !v)}
                  aria-expanded={modePickerOpen}
                  aria-label="Choose reasoning mode"
                >
                  {(() => { const Icon = (SLASH_COMMANDS.find(c => c.id === previewReasoningMode)?.icon) || Radio; return <Icon size={13} />; })()}
                  <span>{displayedModeLabel}</span>
                  <ChevronDown size={11} />
                </button>
                {modePickerOpen && (
                  <div className="mode-picker-menu" role="listbox" aria-label="Reasoning mode menu">
                    {SLASH_COMMANDS.map(cmd => {
                      const Icon = cmd.icon;
                      const active = cmd.id === reasoningMode;
                      return (
                        <button
                          type="button"
                          key={cmd.id}
                          className={`mode-picker-option ${active ? 'active' : ''}`}
                          onClick={() => { setReasoningMode(cmd.id); setModePickerOpen(false); }}
                          role="option"
                          aria-selected={active}
                        >
                          <Icon size={14} style={{ color: cmd.color }} />
                          <span className="mode-picker-option-text">
                            <strong>{cmd.label.slice(1)}</strong>
                            <small>{cmd.desc}</small>
                          </span>
                          {active && <Check size={13} />}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
              <button type="button" className="composer-tool-btn" onClick={() => setSelectFilesOpen(true)}>
                <FileText size={13} />
                <span>{selectedCount > 0 ? `${selectedCount} file${selectedCount > 1 ? 's' : ''}` : 'Select files'}</span>
              </button>
              <button type="button" className="composer-tool-btn" onClick={openUpload}>
                <FilePlus2 size={13} />
                <span>Upload</span>
              </button>
            </div>
            <div className="composer-tools-divider" />
            <div className="composer-tools-group">
              <button
                type="button"
                className={`composer-tool-btn ${allowGeneralKnowledge ? 'active' : ''}`}
                onClick={() => setAllowGeneralKnowledge(v => !v)}
                {...tip('Allow the model to use general knowledge beyond your files')}
              >
                <span className={`tool-dot ${allowGeneralKnowledge ? 'on' : ''}`} />
                <span>LLM Knowledge</span>
              </button>
            </div>
          </div>
          <div className="composer-input-row">
            <div className="input-wrap">
              <textarea
                ref={composerRef}
                rows="1"
                value={question}
                onChange={handleComposerInput}
                onKeyDown={handleComposerKeyDown}
                placeholder="Ask or type / for commands..."
              />
            </div>
            {thinking ? (
              <button type="button" className="stop-answer-button" onClick={stopAnswer} aria-label="Stop answer" title="Stop answer">
                <Square size={15} />
              </button>
            ) : (
              <button type="submit" disabled={!question.trim()} aria-label="Send question" onMouseDown={e => e.preventDefault()}><Send size={17} /></button>
            )}
          </div>
          <div className="composer-meta">
            <div>
              {autoWebSearchPreview && (
                <span className="composer-meta-web"><Globe size={10} /> Will also search the web</span>
              )}
            </div>
            <small><kbd>Enter</kbd> to send · <kbd>Shift Enter</kbd> for a new line</small>
          </div>
        </form>
      </div>

      {/* Select Files Modal */}
      {selectFilesOpen && (
        <div className="modal-overlay" onMouseDown={e => e.target === e.currentTarget && setSelectFilesOpen(false)}>
          <div className="modal file-select-modal">
            <div className="modal-header">
              <h3>Select Files</h3>
              <button type="button" className="modal-close-btn" onClick={() => setSelectFilesOpen(false)}><X size={18} /></button>
            </div>
            <div className="file-select-list">
              {files.length === 0 && <p className="file-select-empty">No files uploaded yet. Upload files in Library first.</p>}
              {stores.map(store => {
                const storeFiles = files.filter(f => f.store_id === store.id);
                if (!storeFiles.length) return null;
                const allSelected = storeFiles.every(f => selectedFileIds?.includes(f.id));
                return (
                  <div className="file-select-store" key={store.id}>
                    <div className="file-select-store-head">
                      <Folder size={14} />
                      <strong>{store.title}</strong>
                      <button
                        type="button"
                        className="file-select-store-toggle"
                        onClick={() => {
                          const ids = storeFiles.map(f => f.id);
                          const current = selectedFileIds || [];
                          if (allSelected) setSelectedFileIds(current.filter(id => !ids.includes(id)));
                          else setSelectedFileIds([...new Set([...current, ...ids])]);
                        }}
                      >
                        {allSelected ? 'Deselect all' : 'Select all'}
                      </button>
                    </div>
                    {storeFiles.map(file => {
                      const checked = selectedFileIds?.includes(file.id) || false;
                      return (
                        <label key={file.id} className={`file-select-row ${checked ? 'checked' : ''}`}>
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleFile(file.id)}
                          />
                          <span className="file-select-check" />
                          <FileText size={13} />
                          <span className="file-select-name">
                            <strong>{file.name}</strong>
                            <small>{fileMetaLine(file)}</small>
                          </span>
                        </label>
                      );
                    })}
                  </div>
                );
              })}
            </div>
            <div className="modal-footer">
              <span className="file-select-count">{selectedFileIds?.length || 0} files selected</span>
              <button type="button" className="btn-primary" onClick={() => setSelectFilesOpen(false)}>Done</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const PROVIDER_META = {
  ollama: { icon: '🦙', blurb: 'Local models, no API key needed', envHint: 'Runs against OLLAMA_URL — start Ollama and pull a model.' },
  groq: { icon: '⚡', blurb: 'Fast cloud inference', envHint: 'Set GROQ_API_KEY in your .env file.' },
  openai: { icon: '🤖', blurb: 'OpenAI models', envHint: 'Set OPENAI_API_KEY in your .env file.' },
  gemini: { icon: '✨', blurb: 'Google Gemini models', envHint: 'Set GEMINI_API_KEY in your .env file.' },
};

const REASONING_MODE_META = [
  { id: 'light', label: 'Light', icon: Radio, desc: 'Fast direct chat — default mode' },
  { id: 'unrestricted', label: 'Unrestricted', icon: Zap, desc: 'Expert mode — direct, low-fluff answers' },
  { id: 'thinking', label: 'Thinking', icon: Sparkles, desc: 'Deep analysis — inspects all selected content' },
  { id: 'deep_summary', label: 'Deep Summary', icon: BookOpen, desc: 'Complete section-by-section doc coverage' },
  { id: 'ticket_analysis', label: 'Ticket Analysis', icon: Database, desc: 'Group incidents by problem pattern' },
];

function SettingsPage({ toast }) {
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState(null);
  const [customModel, setCustomModel] = useState('');
  const [freeOnly, setFreeOnly] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.llmConfig(), api.preference('explore_ai').catch(() => ({ value: {} }))])
      .then(([llmConfig, preference]) => {
        if (cancelled) return;
        setConfig(llmConfig);
        const saved = { ...readSavedAiPreference(), ...(preference.value || {}) };
        setDraft({
          provider: saved.provider || llmConfig.provider || 'ollama',
          model: saved.model || llmConfig.model || '',
          reasoning_mode: saved.reasoning_mode === 'web_research' ? 'light' : (saved.reasoning_mode || 'light'),
          web_source_limit: saved.web_source_limit || 200,
        });
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (loading || !draft) {
    return (
      <div className="page settings-page">
        <div className="loading-grid">
          {[1, 2].map(item => <div key={item} className="skeleton-card" />)}
        </div>
      </div>
    );
  }

  const providers = ['ollama', 'groq', 'openai', 'gemini'];
  const providerModels = provider => config?.providers?.[provider] || [];
  const providerReady = provider => provider === 'ollama' ? providerModels('ollama').length > 0 : providerModels(provider).length > 0;
  const modelMeta = config?.model_meta || {};
  const isFreeModel = item => !!modelMeta[item]?.free;
  const contextOf = item => modelMeta[item]?.context_length || 0;
  const visibleModels = (freeOnly ? providerModels(draft.provider).filter(isFreeModel) : providerModels(draft.provider))
    .slice()
    .sort((a, b) => contextOf(b) - contextOf(a));

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
            return (
              <button
                key={provider}
                type="button"
                className={`settings-provider-card ${active ? 'active' : ''}`}
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
            );
          })}
        </div>

        {!providerReady(draft.provider) && (
          <div className="settings-hint">
            <Info size={14} />
            <span>{PROVIDER_META[draft.provider].envHint}</span>
          </div>
        )}

        <div className="settings-model-header">
          <h3>Default model</h3>
          <button
            type="button"
            className={`settings-free-toggle ${freeOnly ? 'active' : ''}`}
            onClick={() => setFreeOnly(current => !current)}
            aria-pressed={freeOnly}
          >
            Free models only
          </button>
        </div>
        <div className="settings-model-list">
          {providerModels(draft.provider).length === 0 && (
            <p className="settings-empty-note">No models detected yet for {PROVIDER_LABELS[draft.provider]}. You can still set a model ID manually below.</p>
          )}
          {providerModels(draft.provider).length > 0 && visibleModels.length === 0 && (
            <p className="settings-empty-note">No free models available for {PROVIDER_LABELS[draft.provider]}.</p>
          )}
          {visibleModels.map(item => {
            const contextLabel = formatContextLength(contextOf(item));
            return (
              <button
                key={item}
                type="button"
                className={`settings-model-chip ${draft.model === item ? 'active' : ''}`}
                onClick={() => selectModel(item)}
                title={item}
              >
                <span className="settings-model-chip-name">{item}</span>
                {contextLabel && <small className="settings-model-chip-ctx">{contextLabel}</small>}
                {isFreeModel(item) && <span className="settings-model-chip-free">Free</span>}
                {draft.model === item && <Check size={12} />}
              </button>
            );
          })}
        </div>
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

      <div className="settings-save-bar">
        <button type="button" className="btn-primary" onClick={save} disabled={saving}>
          {saving ? 'Saving...' : 'Save defaults'}
        </button>
      </div>
    </div>
  );
}

function CreateStoreModal({ open, close, onCreate }) {
  const [form, setForm] = useState({ title: '', description: '', color: 'violet' });
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setForm({ title: '', description: '', color: 'violet' });
      setError('');
    }
  }, [open]);

  if (!open) return null;

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    try {
      await onCreate(form);
      close();
    } catch (exception) {
      setError(exception.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-wrap" onMouseDown={event => event.target === event.currentTarget && close()}>
      <div className="modal">
        <button className="modal-close icon-button" onClick={close} aria-label="Close">
          <X size={18} />
        </button>
        <div className="modal-symbol"><Folder /></div>
        <span className="kicker">NEW STORE</span>
        <h2>Create a home for your files</h2>
        <p>Group related files so your knowledge stays organized.</p>
        <form onSubmit={submit} className="capture-form">
          <input
            required
            autoFocus
            placeholder="Store name"
            value={form.title}
            onChange={event => setForm({ ...form, title: event.target.value })}
          />
          <textarea
            placeholder="Short description (optional)"
            value={form.description}
            onChange={event => setForm({ ...form, description: event.target.value })}
          />
          <div className="color-picker">
            {STORE_COLORS.map(color => (
              <button
                key={color}
                type="button"
                className={`color-option ${color} ${form.color === color ? 'selected' : ''}`}
                onClick={() => setForm({ ...form, color })}
                aria-label={`${color} color`}
              />
            ))}
          </div>
          {error && <p className="form-error">{error}</p>}
          <button className="save-button" disabled={saving}>
            {saving ? 'Creating...' : 'Create store'} <ArrowRight size={16} />
          </button>
        </form>
      </div>
    </div>
  );
}

function App() {
  const [page, setPage] = useState('home');
  const [query, setQuery] = useState('');
  const [mobileOpen, setMobileOpen] = useState(false);
  const [sidebarCompact, setSidebarCompact] = useState(false);
  const [historyCollapsed, setHistoryCollapsed] = useState(false);
  const [filePanelCollapsed, setFilePanelCollapsed] = useState(false);
  const [preferencesLoaded, setPreferencesLoaded] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const { token: secretChatToken, isSharedLink, open: openSecretChatRoute, close: closeSecretChatRoute } = useSecretChatRoute();
  const setExploreShellEl = useVisualViewportShell();
  const [files, setFiles] = useState([]);
  const [collections, setCollections] = useState([]);
  const [chats, setChats] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState('');
  const [toasts, setToasts] = useState([]);
  const [confirm, setConfirm] = useState(null);
  const [hubFocusStoreId, setHubFocusStoreId] = useState(null);
  const [exploreChatId, setExploreChatId] = useState(null);
  const [newChatSignal, setNewChatSignal] = useState(0);
  const [theme, setTheme] = useState(() => readStorage('theme') || 'dark');

  const toast = (message, type = 'success') => {
    const id = crypto.randomUUID();
    setToasts(current => [...current, { id, message, type }]);
  };

  const dismissToast = id => setToasts(current => current.filter(item => item.id !== id));

  const refreshChats = async () => {
    const nextChats = await api.chats();
    setChats(nextChats);
  };

  const refreshJobs = async () => {
    const nextJobs = await api.chatJobs();
    setJobs(nextJobs);
    return nextJobs;
  };

  const loadData = async () => {
    setLoading(true);
    try {
      const [nextFiles, nextCollections, nextChats, nextJobs, layoutPreference] = await Promise.all([
        api.files(), api.collections(), api.chats(), api.chatJobs(), api.preference('layout'),
      ]);
      const savedLayout = layoutPreference.value || {};
      setFiles(nextFiles);
      setCollections(nextCollections);
      setChats(nextChats);
      setJobs(nextJobs);
      window.localStorage.setItem(APP_DATA_CACHE_KEY, JSON.stringify({
        files: nextFiles,
        collections: nextCollections,
        chats: nextChats,
        jobs: nextJobs,
      }));
      setSidebarCompact(Boolean(savedLayout.sidebar_compact));
      setHistoryCollapsed(Boolean(savedLayout.history_collapsed));
      setFilePanelCollapsed(Boolean(savedLayout.file_panel_collapsed));
      const savedPage = normalizePageId(savedLayout.page);
      if (APP_PAGES.includes(savedPage)) setPage(savedPage);
      setPreferencesLoaded(true);
      setApiError('');
    } catch {
      const cached = readCachedAppData();
      if (cached.files || cached.collections || cached.chats || cached.jobs) {
        setFiles(cached.files || []);
        setCollections(cached.collections || []);
        setChats(cached.chats || []);
        setJobs(cached.jobs || []);
      }
      setApiError('Backend is offline. Start it with npm run dev:api');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadData(); }, []);

  useEffect(() => {
    if (!preferencesLoaded) return undefined;
    const timer = window.setTimeout(() => {
      api.updatePreference('layout', {
        page,
        sidebar_compact: sidebarCompact,
        history_collapsed: historyCollapsed,
        file_panel_collapsed: filePanelCollapsed,
      }).catch(() => {
        // Layout saving is best-effort; the offline banner covers backend health.
      });
    }, 250);
    return () => window.clearTimeout(timer);
  }, [preferencesLoaded, page, sidebarCompact, historyCollapsed, filePanelCollapsed]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    writeStorage('theme', theme);
    const themeColor = theme === 'dark' ? '#0d1217' : '#f5f3ee';
    let meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) {
      meta = document.createElement('meta');
      meta.name = 'theme-color';
      document.head.appendChild(meta);
    }
    meta.setAttribute('content', themeColor);
  }, [theme]);

  useEffect(() => {
    const poll = async () => {
      try {
        const nextJobs = await refreshJobs();
        if (nextJobs.some(job => ['queued', 'running'].includes(job.status))) await refreshChats();
      } catch {
        // The main offline banner handles connectivity; polling resumes automatically.
      }
    };
    const timer = window.setInterval(poll, 1500);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const onKeyDown = (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setCommandOpen(true);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  useEffect(() => {
    if (secretChatToken) setPage('secret-chat');
  }, [secretChatToken]);

  useEffect(() => {
    if (secretChatToken) return;
    if (!preferencesLoaded) return;
    const path = window.location.pathname;
    const pageFromUrl = normalizePageId(path === '/' ? 'home' : path.replace(/^\//, ''));
    if (APP_PAGES.includes(pageFromUrl) && pageFromUrl !== 'secret-chat') {
      setPage(pageFromUrl);
    }
    const onPopState = () => {
      const p = window.location.pathname;
      const next = normalizePageId(p === '/' ? 'home' : p.replace(/^\//, ''));
      if (APP_PAGES.includes(next) && next !== 'secret-chat') setPage(next);
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, [secretChatToken, preferencesLoaded]);

  const navigate = (nextPage, options = {}) => {
    const resolvedPage = normalizePageId(nextPage);
    setPage(resolvedPage);
    if (options.storeId) setHubFocusStoreId(options.storeId);
    if (options.create) setCreateOpen(true);
    const path = resolvedPage === 'home' ? '/' : `/${resolvedPage}`;
    window.history.pushState({}, '', path);
  };

  const handleCommandSelect = (item) => {
    if (item.type === 'page') navigate(item.id);
    if (item.type === 'store') navigate('hub', { storeId: item.id });
    if (item.type === 'file') navigate('hub', { storeId: item.storeId });
    if (item.type === 'chat') {
      navigate('explore');
      setExploreChatId(item.id);
    }
  };

  const create = async payload => {
    await api.createCollection(payload);
    await loadData();
    toast('Store created');
  };

  const uploadFile = async (storeId, file) => {
    const uploaded = await api.uploadFile(storeId, file);
    await loadData();
    return uploaded;
  };

  const deleteFile = async id => {
    await api.deleteFile(id);
    await loadData();
    toast('File deleted');
  };

  const deleteStore = async id => {
    await api.deleteCollection(id);
    await loadData();
    toast('Store deleted');
  };

  const deleteChat = async id => {
    await api.deleteChat(id);
    await loadData();
    toast('Chat deleted');
  };

  const deleteAllChats = async () => {
    await api.deleteAllChats();
    setChats([]);
    setJobs([]);
    setExploreChatId(null);
    toast('All chats deleted');
  };

  const createChatJob = async (...args) => {
    const job = await api.createChatJob(...args);
    setJobs(current => [job, ...current.filter(item => item.id !== job.id)]);
    await refreshChats();
    return job;
  };

  const markJobSeen = async id => {
    setJobs(current => current.map(job => job.id === id ? { ...job, seen: true } : job));
    try {
      await api.markChatJobSeen(id);
    } catch {
      setJobs(current => current.map(job => job.id === id ? { ...job, seen: false } : job));
    }
  };

  const readyCount = jobs.filter(job => job.status === 'completed' && !job.seen).length;
  const hasActiveJobs = jobs.some(job => ['queued', 'running'].includes(job.status));

  const openSecretChat = async () => {
    try {
      await openSecretChatRoute(secretChatApi.create);
      setMobileOpen(false);
    } catch {}
  };

  const requestDeleteChat = (chat, onDeleted) => setConfirm({
    title: 'Delete chat?',
    message: `"${chat.title}" will be permanently removed.`,
    onConfirm: async () => {
      await deleteChat(chat.id);
      if (exploreChatId === chat.id) setExploreChatId(null);
      onDeleted?.();
    },
  });

  const requestDeleteAllChats = onDeleted => setConfirm({
    title: 'Delete all chats?',
    message: `All ${chats.length} conversations and their answers will be permanently removed.`,
    confirmLabel: 'Delete all',
    onConfirm: async () => {
      await deleteAllChats();
      onDeleted?.();
    },
  });

  if (isSharedLink && page === 'secret-chat' && secretChatToken) {
    return <SecretChatStandalone token={secretChatToken} />;
  }

  return (
    <div className={`app-shell ${sidebarCompact ? 'sidebar-compact' : ''} ${page === 'explore' ? 'explore-active' : ''} ${page === 'ticket-analysis' ? 'ticket-analysis-active' : ''}`}>
      <Sidebar
        page={page}
        setPage={(id) => navigate(id)}
        mobileOpen={mobileOpen}
        close={() => setMobileOpen(false)}
        fileCount={files.length}
        readyCount={readyCount}
        compact={sidebarCompact}
        toggleCompact={() => setSidebarCompact(value => !value)}
        files={files}
        historyCollapsed={historyCollapsed}
        setHistoryCollapsed={setHistoryCollapsed}
        onOpenFile={file => navigate('hub', { storeId: file.store_id })}
        onOpenSecretChat={openSecretChat}
        onNewChat={() => {
          setExploreChatId(null);
          setNewChatSignal(value => value + 1);
          navigate('explore');
        }}
        theme={theme}
        setTheme={setTheme}
      />
      <main ref={page === 'explore' ? setExploreShellEl : undefined}>
        {!['explore', 'ticket-analysis'].includes(page) && (
          <Header
            query={query}
            setQuery={setQuery}
            openMenu={() => setMobileOpen(true)}
            openCreate={() => setCreateOpen(true)}
            openCommand={() => setCommandOpen(true)}
            page={page}
          />
        )}
        {apiError && (
          <button className="api-banner" onClick={loadData}>{apiError} · Retry</button>
        )}
        {page === 'home' && (
          <HomePage
            stores={collections}
            files={files}
            chats={chats}
            loading={loading}
            onNavigate={navigate}
            onOpenChat={id => { navigate('explore'); setExploreChatId(id); }}
          />
        )}
        {page === 'hub' && (
          <HubPage
            query={query}
            files={files}
            stores={collections}
            focusStoreId={hubFocusStoreId}
            clearFocusStore={() => setHubFocusStoreId(null)}
            openCreate={() => setCreateOpen(true)}
            uploadFile={uploadFile}
            requestDeleteFile={file => setConfirm({
              title: 'Delete file?',
              message: `“${file.name}” will be removed from this store.`,
              onConfirm: () => deleteFile(file.id),
            })}
            requestDeleteStore={store => setConfirm({
              title: 'Delete store?',
              message: `“${store.title}” and all its files will be permanently removed.`,
              onConfirm: () => deleteStore(store.id),
            })}
            toast={toast}
          />
        )}
        {page === 'explore' && (
          <ExplorePage
            files={files}
            stores={collections}
            chats={chats}
            jobs={jobs}
            createChatJob={createChatJob}
            refreshChats={refreshChats}
            markJobSeen={markJobSeen}
            initialChatId={exploreChatId}
            clearInitialChat={() => setExploreChatId(null)}
            newChatSignal={newChatSignal}
            onOpenStore={storeId => navigate('hub', { storeId })}
            toast={toast}
            requestDeleteChat={requestDeleteChat}
            requestDeleteAllChats={requestDeleteAllChats}
            hasActiveJobs={hasActiveJobs}
            refreshJobs={refreshJobs}
            openMenu={() => setMobileOpen(true)}
          />
        )}
        {page === 'ticket-analysis' && (
          <TicketAnalysisPage files={files} openMenu={() => setMobileOpen(true)} />
        )}
        {page === 'secret-chat' && secretChatToken && (
          <SecretChatPage
            token={secretChatToken}
            onBack={() => {
              setPage('home');
              closeSecretChatRoute();
            }}
          />
        )}
        {page === 'settings' && <SettingsPage toast={toast} />}
      </main>

      <CreateStoreModal open={createOpen} close={() => setCreateOpen(false)} onCreate={create} />
      <ConfirmModal config={confirm} close={() => setConfirm(null)} />
      <CommandPalette
        open={commandOpen}
        close={() => { setCommandOpen(false); setQuery(''); }}
        query={query}
        setQuery={setQuery}
        stores={collections}
        files={files}
        chats={chats}
        onSelect={handleCommandSelect}
      />
      <ToastStack toasts={toasts} dismiss={dismissToast} />
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App />);
