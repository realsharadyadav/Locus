import React, { useEffect, useRef } from 'react';
import {
  ArrowRight, BrainCircuit, FileText, X, Globe,
} from 'lucide-react';
import { PROVIDER_LABELS } from '../lib/appState';

export function CollapsibleSources({ sources, index, isExpanded, onToggle, onOpenStore, model, provider, llmHits = 0, webQueries = 0 }) {
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
