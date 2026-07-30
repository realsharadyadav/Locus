import React from 'react';
import { Clock, Globe, Languages, MessageSquare, Monitor, Network, Smartphone, Tablet, X } from 'lucide-react';
import { displayTime } from '../../utils';

const DeviceIcon = ({ device, size = 13 }) => {
  if (device === 'Phone') return <Smartphone size={size} />;
  if (device === 'Tablet') return <Tablet size={size} />;
  return <Monitor size={size} />;
};

/**
 * Host-only view of who is in the room. Everything here is collected from the guest's own
 * browser and connection when they check in — the guest view says so in plain words, so
 * nobody is surprised by it.
 */
export default function GuestsPanel({ participants, clientId, onClose }) {
  const sorted = [...participants].sort((a, b) => {
    if (a.online !== b.online) return a.online ? -1 : 1;
    return new Date(a.joined_at) - new Date(b.joined_at);
  });

  return (
    <aside className="guests-panel" aria-label="People in this chat">
      <div className="guests-panel-head">
        <strong>People in this chat</strong>
        <button type="button" onClick={onClose} aria-label="Close people panel"><X size={15} /></button>
      </div>

      {sorted.length === 0 && <p className="guests-empty">Nobody has opened the link yet.</p>}

      {sorted.map(person => (
        <article className={`guest-card${person.online ? ' online' : ''}`} key={person.client_id}>
          {/* A plain div, not <header>: the app stylesheet styles bare `header` elements. */}
          <div className="guest-card-head">
            <span className={`guest-dot${person.online ? ' on' : ''}`} aria-hidden="true" />
            <strong>{person.name}</strong>
            {person.client_id === clientId && <span className="guest-tag you">you</span>}
            {person.role === 'host' && <span className="guest-tag host">host</span>}
            {person.typing && <span className="guest-tag typing">typing…</span>}
          </div>

          <div className="guest-facts">
            <span title="Device, browser and operating system">
              <DeviceIcon device={person.device} /> {[person.device, person.browser, person.os].filter(Boolean).join(' · ') || 'Unknown device'}
            </span>
            {person.screen && (
              <span title="Screen and window size">
                <Monitor size={13} /> {person.screen} screen{person.viewport ? ` · ${person.viewport} window` : ''}
              </span>
            )}
            {person.language && <span title="Browser language"><Languages size={13} /> {person.language}</span>}
            {person.timezone && (
              <span title="Time zone and their local clock">
                <Globe size={13} /> {person.timezone}{person.local_time ? ` · ${person.local_time} local` : ''}
              </span>
            )}
            {person.ip && <span title="Connecting IP address"><Network size={13} /> {person.ip}</span>}
            <span title="How long they have been in this room">
              <Clock size={13} /> joined {displayTime(person.joined_at)}
              {person.minutes_in_room > 0 ? ` · ${person.minutes_in_room} min in room` : ''}
            </span>
            <span title="Messages sent and how far they have read">
              <MessageSquare size={13} /> {person.message_count} sent · read up to #{person.last_read_id}
            </span>
            <span className="guest-lastseen">
              {person.online ? 'Online now' : `Last seen ${displayTime(person.last_seen)}`}
            </span>
          </div>

          {person.user_agent && <p className="guest-ua" title={person.user_agent}>{person.user_agent}</p>}
        </article>
      ))}
    </aside>
  );
}
