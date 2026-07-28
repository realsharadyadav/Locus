import React, { useState } from 'react';
import {
  Check, Terminal, X,
} from 'lucide-react';
import { PROVIDER_LABELS } from '../lib/appState';
import { modelProvider } from '../lib/format';
import { directActivityToNote } from '../lib/pipelineNotes';

export function DirectStreamTrace({ activity = [], model, provider, text = '', streaming = false }) {
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
