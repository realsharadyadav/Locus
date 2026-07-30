import React, { useCallback, useEffect, useState } from 'react';
import { Clock, Fingerprint, Flame, Link2, Menu, Plus, Trash2, X } from 'lucide-react';
import { secretChatApi } from '../api';
import { clientId as readClientId, hostKey as readHostKey } from '../identity';
import { parseServerTime } from '../../utils';
import SecretChatPage from './SecretChatPage';

/**
 * Host view for Private chats, laid out like the Ask module: a rail of rooms on
 * the left, the selected room on the right.
 *
 * A room in the rail lights up when somebody else has posted in it since this
 * browser last read it — the count comes from the server-side read cursor, so it
 * is the same number the Private nav badge shows.
 *
 * Deleting a room here is what revokes its shared link — the backend drops the
 * messages and cuts any stream a guest is holding open, so the confirm copy
 * says so plainly.
 */

export const DISAPPEAR_OPTIONS = [
  { value: 0, label: 'Off' },
  { value: 60, label: '1 min' },
  { value: 300, label: '5 min' },
  { value: 3600, label: '1 hour' },
  { value: 86400, label: '24 hours' },
];

export const LINK_EXPIRY_OPTIONS = [
  { value: 0, label: 'Never' },
  { value: 5, label: '5 min' },
  { value: 30, label: '30 min' },
  { value: 120, label: '2 hours' },
  { value: 1440, label: '24 hours' },
];

export const ROOM_EXPIRY_OPTIONS = [
  { value: 0, label: 'Never' },
  { value: 60, label: '1 hour' },
  { value: 480, label: '8 hours' },
  { value: 1440, label: '24 hours' },
  { value: 10080, label: '7 days' },
];

export const ttlLabel = seconds => DISAPPEAR_OPTIONS.find(option => option.value === seconds)?.label || `${seconds}s`;

const relativeTime = value => {
  // parseServerTime returns a timestamp, not a Date.
  const minutes = Math.floor((Date.now() - parseServerTime(value)) / 60000);
  if (minutes < 1) return 'now';
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
};

const expiryLabel = value => {
  const minutes = Math.round((parseServerTime(value) - Date.now()) / 60000);
  if (minutes <= 0) return 'expired';
  if (minutes < 60) return `${minutes}m left`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours}h left` : `${Math.round(hours / 24)}d left`;
};

function OptionRow({ label, hint, options, value, onChange }) {
  return (
    <div className="room-option">
      <div className="room-option-copy">
        <strong>{label}</strong>
        <small>{hint}</small>
      </div>
      <div className="room-option-choices" role="group" aria-label={label}>
        {options.map(option => (
          <button
            type="button"
            key={option.value}
            className={value === option.value ? 'active' : ''}
            onClick={() => onChange(option.value)}
            aria-pressed={value === option.value}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function PrivateChatsPage({ token, onSelect, requestConfirm, toast, openMenu }) {
  const [rooms, setRooms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [railOpen, setRailOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [ttl, setTtl] = useState(0);
  const [linkExpiry, setLinkExpiry] = useState(0);
  const [roomExpiry, setRoomExpiry] = useState(0);

  const refresh = useCallback(async () => {
    try {
      setRooms(await secretChatApi.rooms(readHostKey(), readClientId()));
    } catch {
      // The app-wide offline banner already covers an unreachable backend.
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh, token]);

  // Keeps unread counts and who-is-online fresh while the rail is on screen.
  useEffect(() => {
    const timer = setInterval(refresh, 6000);
    return () => clearInterval(timer);
  }, [refresh]);

  const createRoom = async () => {
    if (creating) return;
    setCreating(true);
    try {
      const session = await secretChatApi.create({
        title: title.trim() || 'Private',
        host_key: readHostKey(),
        message_ttl_seconds: ttl,
        link_expiry_minutes: linkExpiry,
        room_expiry_minutes: roomExpiry,
      });
      setTitle('');
      await refresh();
      onSelect(session.token);
    } catch (error) {
      toast?.(error.message || 'Could not start a private chat', 'error');
    } finally {
      setCreating(false);
    }
  };

  const deleteRoom = room => requestConfirm?.({
    title: 'Delete this private chat?',
    message: `“${room.title}” and its ${room.message_count} message${room.message_count === 1 ? '' : 's'} will be permanently removed, and the shared link will stop working for everyone who has it.`,
    confirmLabel: 'Delete and revoke link',
    onConfirm: async () => {
      await secretChatApi.deleteRoom(room.token, readHostKey());
      if (room.token === token) onSelect(null);
      await refresh();
      toast?.('Private chat deleted · link revoked');
    },
  });

  const deleteAllRooms = () => requestConfirm?.({
    title: 'Delete all private chats?',
    message: `All ${rooms.length} private chat${rooms.length === 1 ? '' : 's'}, their messages and their links will be permanently removed. Everyone holding one of those links loses access immediately.`,
    confirmLabel: 'Delete all',
    onConfirm: async () => {
      await secretChatApi.deleteAllRooms(readHostKey());
      onSelect(null);
      await refresh();
      toast?.('All private chats deleted · links revoked');
    },
  });

  const selectRoom = nextToken => {
    onSelect(nextToken);
    setRailOpen(false);
  };

  return (
    <div className="private-shell">
      <aside className={`chat-rail ${railOpen ? 'open' : ''}`}>
        <div className="chat-rail-head">
          <span className="kicker">Private</span>
          <span className="chat-rail-count">{rooms.length}</span>
          <button type="button" className="chat-rail-new" onClick={() => selectRoom(null)} aria-label="Start a new private chat">
            <Plus size={13} /> New
          </button>
          <button type="button" className="chat-rail-close icon-button" onClick={() => setRailOpen(false)} aria-label="Close private chat list">
            <X size={18} />
          </button>
        </div>
        <div className="chat-rail-list">
          {rooms.map(room => (
            <div
              key={room.token}
              role="button"
              tabIndex={0}
              className={`chat-rail-item ${room.token === token ? 'active' : ''}${room.unread_count ? ' unread' : ''}`}
              onClick={() => selectRoom(room.token)}
              onKeyDown={event => {
                if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectRoom(room.token); }
              }}
              title={room.title}
            >
              <span className="chat-rail-name">
                {room.unread_count > 0 && <span className="chat-rail-dot" aria-hidden="true" />}
                <span>{room.title}</span>
                {room.unread_count > 0
                  ? <small className="private-rail-unread">{room.unread_count} new</small>
                  : room.message_count > 0 && <small className="private-rail-count">{room.message_count}</small>}
              </span>
              <span className="chat-rail-preview">
                {room.last_message_preview ? `${room.last_sender}: ${room.last_message_preview}` : 'No messages yet'}
              </span>
              <span className="chat-rail-facts">
                {room.online_count > 0 && (
                  <span className="chat-rail-online"><span className="live-dot" aria-hidden="true" />{room.online_count}</span>
                )}
                {room.message_ttl_seconds > 0 && <span><Flame size={10} /> {ttlLabel(room.message_ttl_seconds)}</span>}
                {room.link_expired
                  ? <span className="chat-rail-warn"><Link2 size={10} /> link expired</span>
                  : room.link_expires_at && <span><Link2 size={10} /> {expiryLabel(room.link_expires_at)}</span>}
                {room.expires_at && <span><Clock size={10} /> {expiryLabel(room.expires_at)}</span>}
              </span>
              <span className="chat-rail-time">{relativeTime(room.last_activity)}</span>
              <button
                type="button"
                className="chat-rail-delete"
                onClick={event => { event.stopPropagation(); deleteRoom(room); }}
                aria-label={`Delete ${room.title} and revoke its link`}
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
          {!loading && !rooms.length && <span className="chat-rail-empty">No private chats yet</span>}
        </div>
        {rooms.length > 0 && (
          <button type="button" className="chat-rail-delete-all" onClick={deleteAllRooms}>
            <Trash2 size={12} /> Delete all chats
          </button>
        )}
      </aside>
      {railOpen && <button type="button" className="chat-rail-scrim" aria-label="Close private chat list" onClick={() => setRailOpen(false)} />}

      {token ? (
        <SecretChatPage
          key={token}
          token={token}
          onBack={() => onSelect(null)}
          onChanged={refresh}
          onRevoked={() => { onSelect(null); refresh(); }}
          openRail={() => setRailOpen(true)}
          toast={toast}
          requestConfirm={requestConfirm}
        />
      ) : (
        <div className="private-empty">
          <div className="private-empty-bar">
            <button className="menu-button icon-button" onClick={openMenu} aria-label="Open menu">
              <Menu size={20} />
            </button>
            <button type="button" className="private-rail-toggle" onClick={() => setRailOpen(true)}>
              Private chats
            </button>
          </div>
          <div className="private-empty-body">
            <Fingerprint size={40} />
            <h2>Private chats</h2>
            <p>Each chat gets its own link. Share it with anyone — they see only that chat, never the rest of Locus.</p>

            <div className="private-new">
              <input
                className="private-new-title"
                value={title}
                onChange={event => setTitle(event.target.value)}
                placeholder="What is this chat about? (optional)"
                maxLength={160}
              />
              <OptionRow
                label="Disappearing messages"
                hint="Each message deletes itself this long after it is sent — for everyone."
                options={DISAPPEAR_OPTIONS}
                value={ttl}
                onChange={setTtl}
              />
              <OptionRow
                label="Invite link expires"
                hint="After this the link stops letting new people in. Anyone already in keeps chatting."
                options={LINK_EXPIRY_OPTIONS}
                value={linkExpiry}
                onChange={setLinkExpiry}
              />
              <OptionRow
                label="Delete the whole chat"
                hint="The chat, its messages and its link are destroyed at this point, no matter what."
                options={ROOM_EXPIRY_OPTIONS}
                value={roomExpiry}
                onChange={setRoomExpiry}
              />
            </div>

            <button type="button" className="btn-primary" onClick={createRoom} disabled={creating}>
              <Plus size={15} /> {creating ? 'Starting…' : 'Start chat and get the link'}
            </button>
            <small>Deleting a chat revokes its link immediately.</small>
          </div>
        </div>
      )}
    </div>
  );
}
