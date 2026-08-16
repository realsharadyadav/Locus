import React, { useEffect, useState } from 'react';
import {
  Compass, Cpu, FileText, Folder, Globe, MessageSquare,
  RefreshCw, Sparkles, Upload, Zap,
} from 'lucide-react';
import { BRAND } from '../brand';
import { api } from '../api';
import { SLASH_COMMANDS } from '../lib/ask';
import { fileMetaLine, greetingForHour } from '../lib/format';
import { displayTime } from '../utils';

export function HomePage({ stores, files, chats, loading, onNavigate, onOpenChat }) {
  // Live capability data for the "What Locus can do" strip. Every number here comes from a
  // real backend response — the provider/model catalogue from /api/llm/config and the
  // model_health / auto_select_model preferences. Failures degrade to `null`/empty so the
  // strip shows what it can and never crashes the page.
  const [capabilities, setCapabilities] = useState(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.llmConfig().catch(() => null),
      api.preference('model_health').catch(() => ({ value: null })),
      api.preference('auto_select_model').catch(() => ({ value: null })),
    ]).then(([config, healthPref, autoSelectPref]) => {
      if (cancelled) return;
      setCapabilities({
        config,
        health: healthPref?.value || null,
        autoSelect: autoSelectPref?.value ?? null,
      });
    });
    return () => { cancelled = true; };
  }, []);

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
  const greeting = greetingForHour(new Date().getHours());
  const goToStat = target => () => onNavigate(target);
  const onStatKeyDown = target => event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onNavigate(target);
    }
  };

  // ── Capability chips ──────────────────────────────────────────────
  // The three user-facing reasoning modes, straight from the effort dial definition.
  const chips = SLASH_COMMANDS.map(mode => ({
    key: `mode-${mode.id}`,
    icon: mode.icon,
    accent: mode.color,
    title: mode.friendlyLabel,
    subtitle: mode.friendlyDesc,
    onClick: () => onNavigate('ask'),
  }));

  if (capabilities?.config) {
    // Providers only count when they actually list at least one reachable model — an empty
    // list means no key configured / not running, so it isn't a "ready" provider.
    const providerCount = Object.entries(capabilities.config.providers || {})
      .filter(([, models]) => Array.isArray(models) && models.length).length;
    const modelCount = Object.values(capabilities.config.providers || {})
      .reduce((total, models) => total + (Array.isArray(models) ? models.length : 0), 0);
    chips.push({
      key: 'models',
      icon: Cpu,
      title: `${providerCount} provider${providerCount === 1 ? '' : 's'} · ${modelCount} model${modelCount === 1 ? '' : 's'}`,
      subtitle: capabilities.config.model ? `Default: ${capabilities.config.model}` : 'Set a default in Settings',
      onClick: () => onNavigate('settings'),
    });
  }

  if (capabilities?.health) {
    // model_health is {provider: {model: {ok, latency_ms, checked_at}}}. Only show this chip
    // when a probe has actually run — an empty preference means "untested" and we don't fake it.
    let tested = 0;
    let responding = 0;
    for (const models of Object.values(capabilities.health)) {
      if (!models || typeof models !== 'object') continue;
      for (const entry of Object.values(models)) {
        if (!entry || typeof entry !== 'object') continue;
        tested += 1;
        if (entry.ok) responding += 1;
      }
    }
    if (tested > 0) {
      chips.push({
        key: 'health',
        icon: Zap,
        title: `${responding}/${tested} models responding`,
        subtitle: 'verified by live probes',
        onClick: () => onNavigate('settings'),
      });
    }
  }

  if (capabilities) {
    const autoOn = typeof capabilities.autoSelect === 'boolean'
      ? capabilities.autoSelect
      : Boolean(capabilities.autoSelect?.enabled);
    chips.push({
      key: 'auto-fallback',
      icon: RefreshCw,
      title: autoOn ? 'Auto-fallback on' : 'Auto-fallback off',
      subtitle: autoOn ? 'a failing default swaps itself mid-answer' : 'turn it on to never hit a dead model',
      onClick: () => onNavigate('settings'),
    });
  }

  chips.push(
    {
      key: 'web-research',
      icon: Globe,
      title: 'Web research',
      subtitle: 'multi-round search + synthesis',
      onClick: () => onNavigate('ask'),
    },
    {
      key: 'private-chats',
      icon: MessageSquare,
      title: 'Private Chats',
      subtitle: 'ephemeral, guest-shareable rooms',
      onClick: () => onNavigate('secret-chat'),
    },
  );

  return (
    <div className="page home-page">
      <section className="home-hero">
        <div className="welcome-mark"><Sparkles size={24} /></div>
        <span className="kicker">YOUR SECOND BRAIN</span>
        <h1>{empty ? `Welcome to ${BRAND.name}` : greeting}</h1>
        <p>{empty ? 'Upload files to a library, then ask a question.' : 'Your second brain is ready — ask it anything.'}</p>
      </section>

      <section className="capabilities-strip">
        <div className="capabilities-head">
          <h2>What Locus can do</h2>
          <p>Live from your setup — tap a card to jump in.</p>
        </div>
        <div className="capabilities-grid">
          {chips.map((chip, i) => {
            const CapIcon = chip.icon;
            return (
              <button
                key={chip.key}
                type="button"
                className={`cap-chip${chip.accent ? ' accent' : ''}`}
                style={{
                  '--cap-delay': `${0.03 + i * 0.045}s`,
                  ...(chip.accent ? { '--chip-accent': chip.accent } : {}),
                }}
                onClick={chip.onClick}
              >
                <span className="cap-chip-icon"><CapIcon size={16} /></span>
                <span className="cap-chip-title">{chip.title}</span>
                <span className="cap-chip-sub">{chip.subtitle}</span>
              </button>
            );
          })}
          {!capabilities && [1, 2, 3].map(i => <div key={`cap-skeleton-${i}`} className="cap-chip-skeleton" />)}
        </div>
      </section>

      <section className="stat-grid">
        <article role="button" tabIndex={0} onClick={goToStat('library')} onKeyDown={onStatKeyDown('library')}>
          <Folder size={16} className="stat-icon" />
          <strong>{stores.length}</strong><span>Libraries</span>
        </article>
        <article role="button" tabIndex={0} onClick={goToStat('library')} onKeyDown={onStatKeyDown('library')}>
          <FileText size={16} className="stat-icon" />
          <strong>{files.length}</strong><span>Files</span>
        </article>
        <article role="button" tabIndex={0} onClick={goToStat('ask')} onKeyDown={onStatKeyDown('ask')}>
          <Compass size={16} className="stat-icon" />
          <strong>{chats.length}</strong><span>Chats</span>
        </article>
      </section>

      <section className="quick-actions">
        <button onClick={() => onNavigate('library', { create: true })}><Folder size={16} /> Create library</button>
        <button onClick={() => onNavigate('library')}><Upload size={16} /> Upload files</button>
        <button onClick={() => onNavigate('ask')}><Compass size={16} /> Ask a question</button>
      </section>

      {empty ? (
        <section className="onboarding-card">
          <h2>Get started in two steps</h2>
          <ol>
            <li>Create a library and upload your documents.</li>
            <li>Open Ask and ask questions grounded in those files.</li>
          </ol>
        </section>
      ) : (
        <section className="home-panels">
          <div className="panel">
            <div className="panel-head">
              <h2>Recent files</h2>
              <button type="button" className="panel-view-all" onClick={() => onNavigate('library')}>View all</button>
            </div>
            {files.slice(0, 5).map(file => (
              <button key={file.id} className="panel-row" onClick={() => onNavigate('library', { storeId: file.store_id })}>
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
            <div className="panel-head">
              <h2>Recent chats</h2>
              <button type="button" className="panel-view-all" onClick={() => onNavigate('ask')}>View all</button>
            </div>
            {!chats.length && <p className="panel-empty">No chats yet. Start one in Ask.</p>}
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
