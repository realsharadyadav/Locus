import React, { useCallback, useEffect, useState } from 'react';
import { Fingerprint, Menu, Plus, Trash2, X } from 'lucide-react';
import { secretChatApi } from '../api';
import { parseServerTime } from '../../utils';
import SecretChatPage from './SecretChatPage';

/**
 * Host view for Private chats, laid out like the Ask module: a rail of rooms on
 * the left, the selected room on the right.
 *
 * Deleting a room here is what revokes its shared link — the backend drops the
 * messages and cuts any stream a guest is holding open, so the confirm copy
 * says so plainly.
 */

const relativeTime = value => {
  // parseServerTime returns a timestamp, not a Date.
  const minutes = Math.floor((Date.now() - parseServerTime(value)) / 60000);
  if (minutes < 1) return 'now';
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
};

export default function PrivateChatsPage({ token, onSelect, requestConfirm, toast, openMenu }) {
  const [rooms, setRooms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [railOpen, setRailOpen] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setRooms(await secretChatApi.list());
    } catch {
      // The app-wide offline banner already covers an unreachable backend.
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh, token]);

  const createRoom = async () => {
    if (creating) return;
    setCreating(true);
    try {
      const session = await secretChatApi.create();
      await refresh();
      onSelect(session.token);
    } catch {
      toast?.('Could not start a private chat', 'error');
    } finally {
      setCreating(false);
    }
  };

  const deleteRoom = room => requestConfirm?.({
    title: 'Delete this private chat?',
    message: `“${room.title}” and its ${room.message_count} message${room.message_count === 1 ? '' : 's'} will be permanently removed, and the shared link will stop working for everyone who has it.`,
    confirmLabel: 'Delete and revoke link',
    onConfirm: async () => {
      await secretChatApi.remove(room.token);
      if (room.token === token) onSelect(null);
      await refresh();
      toast?.('Private chat deleted · link revoked');
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
          <button type="button" className="chat-rail-new" onClick={createRoom} disabled={creating} aria-label="Start a new private chat">
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
              className={`chat-rail-item ${room.token === token ? 'active' : ''}`}
              onClick={() => selectRoom(room.token)}
              onKeyDown={event => {
                if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectRoom(room.token); }
              }}
              title={room.title}
            >
              <span className="chat-rail-name">
                <span>{room.title}</span>
                {room.message_count > 0 && <small className="private-rail-count">{room.message_count}</small>}
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
            <button type="button" className="btn-primary" onClick={createRoom} disabled={creating}>
              <Plus size={15} /> {creating ? 'Starting…' : 'Start a private chat'}
            </button>
            <small>Deleting a chat revokes its link immediately.</small>
          </div>
        </div>
      )}
    </div>
  );
}
