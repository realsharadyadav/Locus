import React from 'react';
import {
  Compass, FileText, Folder, Sparkles, Upload,
} from 'lucide-react';
import { BRAND } from '../brand';
import { fileMetaLine, greetingForHour } from '../lib/format';
import { displayTime } from '../utils';

export function HomePage({ stores, files, chats, loading, onNavigate, onOpenChat }) {
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

  return (
    <div className="page home-page">
      <section className="home-hero">
        <div className="welcome-mark"><Sparkles size={24} /></div>
        <span className="kicker">YOUR SECOND BRAIN</span>
        <h1>{empty ? `Welcome to ${BRAND.name}` : greeting}</h1>
        <p>{empty ? 'Upload files to a library, then ask a question.' : 'Your second brain is ready — ask it anything.'}</p>
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
