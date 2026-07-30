import React, { useCallback, useEffect, useState } from 'react';
import { Clock, Fingerprint, Flame, Link2, Loader2, Plus, Trash2, Users } from 'lucide-react';
import { secretChatApi } from '../api';
import { clientId as readClientId, hostKey as readHostKey } from '../identity';
import { displayTime, parseServerTime } from '../../utils';

export const DISAPPEAR_OPTIONS = [
  { value: 0, label: 'Off', hint: 'Messages stay until you delete them' },
  { value: 60, label: '1 min', hint: 'Each message vanishes a minute after it is sent' },
  { value: 300, label: '5 min', hint: 'Each message vanishes five minutes after it is sent' },
  { value: 3600, label: '1 hour', hint: 'Each message vanishes an hour after it is sent' },
  { value: 86400, label: '24 hours', hint: 'Each message vanishes a day after it is sent' },
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

const ttlLabel = seconds => DISAPPEAR_OPTIONS.find(option => option.value === seconds)?.label || `${seconds}s`;

const expiryLabel = value => {
  if (!value) return '';
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

/**
 * Landing screen for Private: start a room with its privacy options, and manage the rooms
 * this browser already owns. Unread counts come from the server-side read cursor, so a
 * room lights up here the moment somebody replies in it.
 */
export default function SecretChatRoster({ onOpen, onRoomsChanged, toast, confirm }) {
  const [rooms, setRooms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState('');
  const [ttl, setTtl] = useState(0);
  const [linkExpiry, setLinkExpiry] = useState(0);
  const [roomExpiry, setRoomExpiry] = useState(0);

  const refresh = useCallback(async () => {
    try {
      const next = await secretChatApi.rooms(readHostKey(), readClientId());
      setRooms(next);
      onRoomsChanged?.(next);
    } catch {
      // The offline banner covers connectivity; an empty roster is the safe fallback.
    } finally {
      setLoading(false);
    }
  }, [onRoomsChanged]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 6000);
    return () => clearInterval(timer);
  }, [refresh]);

  const create = async () => {
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
      onOpen(session.token);
    } catch (error) {
      toast?.(error.message || 'Could not start the chat', 'error');
    } finally {
      setCreating(false);
    }
  };

  const removeRoom = room => confirm({
    title: 'Delete this chat?',
    message: `"${room.title}" — every message and the invite link will be permanently deleted. Anyone holding the link will see that the chat has ended.`,
    confirmLabel: 'Delete chat',
    onConfirm: async () => {
      await secretChatApi.deleteRoom(room.token, readHostKey());
      await refresh();
      toast?.('Private chat deleted');
    },
  });

  const removeAll = () => confirm({
    title: 'Delete all private chats?',
    message: `All ${rooms.length} private chat${rooms.length === 1 ? '' : 's'}, their messages and their invite links will be permanently deleted.`,
    confirmLabel: 'Delete all',
    onConfirm: async () => {
      await secretChatApi.deleteAllRooms(readHostKey());
      await refresh();
      toast?.('All private chats deleted');
    },
  });

  const totalUnread = rooms.reduce((sum, room) => sum + room.unread_count, 0);

  return (
    <div className="secret-chat-roster">
      <header className="roster-head">
        <div className="roster-title">
          <Fingerprint size={18} />
          <div>
            <h1>Private</h1>
            <p>Invite-only rooms that live outside your workspace. Nothing here is indexed or searchable.</p>
          </div>
        </div>
      </header>

      <section className="roster-new">
        <h2>Start a private chat</h2>
        <input
          className="roster-title-input"
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
          hint="After this, the link stops letting new people in. Anyone already in keeps chatting."
          options={LINK_EXPIRY_OPTIONS}
          value={linkExpiry}
          onChange={setLinkExpiry}
        />
        <OptionRow
          label="Delete the whole chat"
          hint="The room, its messages and its link are destroyed at this point, no matter what."
          options={ROOM_EXPIRY_OPTIONS}
          value={roomExpiry}
          onChange={setRoomExpiry}
        />
        <button type="button" className="roster-create-btn" onClick={create} disabled={creating}>
          {creating ? <Loader2 size={16} className="spin" /> : <Plus size={16} />}
          {creating ? 'Starting…' : 'Start chat and get the link'}
        </button>
      </section>

      <section className="roster-list">
        <div className="roster-list-head">
          <h2>
            Your chats
            {totalUnread > 0 && <span className="roster-unread-total">{totalUnread} unread</span>}
          </h2>
          {rooms.length > 0 && (
            <button type="button" className="roster-delete-all" onClick={removeAll}>
              <Trash2 size={13} /> Delete all
            </button>
          )}
        </div>

        {loading && <p className="roster-empty">Loading…</p>}
        {!loading && rooms.length === 0 && <p className="roster-empty">No private chats yet. Start one above.</p>}

        {rooms.map(room => (
          <div className={`roster-row${room.unread_count ? ' unread' : ''}`} key={room.token}>
            <button type="button" className="roster-row-main" onClick={() => onOpen(room.token)}>
              <span className="roster-row-title">
                {room.unread_count > 0 && <span className="roster-row-dot" aria-hidden="true" />}
                <strong>{room.title}</strong>
                {room.unread_count > 0 && <span className="roster-row-badge">{room.unread_count} new</span>}
              </span>
              <span className="roster-row-preview">
                {room.last_message_preview
                  ? `${room.last_sender}: ${room.last_message_preview}`
                  : 'No messages yet'}
              </span>
              <span className="roster-row-meta">
                <span><Users size={11} /> {room.online_count} online · {room.participant_count} joined</span>
                <span>{room.message_count} message{room.message_count === 1 ? '' : 's'}</span>
                {room.message_ttl_seconds > 0 && <span><Flame size={11} /> {ttlLabel(room.message_ttl_seconds)}</span>}
                {room.link_expired
                  ? <span className="roster-row-warn"><Link2 size={11} /> link expired</span>
                  : room.link_expires_at && <span><Link2 size={11} /> {expiryLabel(room.link_expires_at)}</span>}
                {room.expires_at && <span><Clock size={11} /> chat {expiryLabel(room.expires_at)}</span>}
                <span>{displayTime(room.last_activity)}</span>
              </span>
            </button>
            <button
              type="button"
              className="roster-row-delete"
              onClick={() => removeRoom(room)}
              aria-label={`Delete ${room.title}`}
              title="Delete this chat"
            >
              <Trash2 size={15} />
            </button>
          </div>
        ))}
      </section>
    </div>
  );
}
