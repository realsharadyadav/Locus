import React, { useEffect, useRef, useState } from 'react';
import {
  Activity, ArrowRight, BrainCircuit, Check, CircleCheck, Code2, Cpu, Database, FileText, Layers3,
  PenLine, Radio, Search, ShieldCheck, Sparkles, Terminal, X, Zap,
} from 'lucide-react';
import { BRAND } from '../brand';
import { PROVIDER_LABELS } from '../lib/appState';
import { formatElapsedTime, modelProvider } from '../lib/format';
import { buildWorkingNotes } from '../lib/pipelineNotes';
import { parseServerTime } from '../utils';
import { GitBranchIcon } from './icons';

export function PipelineActivity({ pipeline, model, provider, events, startedAt, reasoningMode, webSearch, fileCount, question, liveLlmHits = 0, liveWebQueries = 0, liveTotalTokens = 0 }) {
  const directModelChat = !webSearch && reasoningMode === 'light' && fileCount === 0;
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
    ? 'Web Research'
    : directModelChat ? 'Direct chat' : reasoningMode === 'deep_summary' ? 'Max effort' : reasoningMode === 'thinking' ? 'High effort' : reasoningMode === 'web_research' ? 'Web Research' : 'Normal effort';
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
