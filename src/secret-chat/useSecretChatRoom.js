import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { secretChatApi } from './api';
import { clientId as readClientId, clientProfile } from './identity';
import { parseServerTime } from '../utils';

const PRESENCE_INTERVAL_MS = 8000;
const POLL_INTERVAL_MS = 8000;
const TYPING_HOLD_MS = 3000;

const mergeParticipants = (current, incoming) => {
  const byId = new Map(current.map(item => [item.client_id, item]));
  return incoming.map(item => ({ ...(byId.get(item.client_id) || {}), ...item }));
};

/**
 * Everything a private chat room needs at runtime: history, the live stream, presence
 * heartbeats, typing, read cursors and auto-disappear pruning.
 *
 * Both the in-app host view and the standalone guest view run on this hook, so the two
 * screens cannot drift apart in behaviour — they only differ in what they render.
 */
export function useSecretChatRoom({ token, hostKey = '', isHost = false }) {
  const clientId = useMemo(() => readClientId(), []);
  const [session, setSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [participants, setParticipants] = useState([]);
  const [sender, setSender] = useState(() => window.localStorage.getItem('secret-chat-sender') || 'Anonymous');
  const [status, setStatus] = useState('loading');
  const [error, setError] = useState('');
  const [lastReadId, setLastReadId] = useState(0);
  // Where the "New messages" line sits. Frozen when the room opens, so it stays put while
  // you read instead of vanishing the instant the newest message is on screen.
  const [unreadMarkFrom, setUnreadMarkFrom] = useState(0);
  const [tick, setTick] = useState(0);

  const lastIdRef = useRef(0);
  const typingUntilRef = useRef(0);
  const readRef = useRef(0);
  const senderRef = useRef(sender);
  senderRef.current = sender;

  const roomOver = useCallback((nextStatus, message) => {
    setStatus(nextStatus);
    setError(message);
  }, []);

  const applyMessages = useCallback(additions => {
    if (!additions.length) return;
    setMessages(current => {
      const existing = new Set(current.map(message => message.id));
      const fresh = additions.filter(message => !existing.has(message.id));
      if (!fresh.length) return current;
      return [...current, ...fresh].sort((a, b) => a.id - b.id);
    });
    lastIdRef.current = additions.reduce((max, message) => Math.max(max, message.id), lastIdRef.current);
  }, []);

  // ─── initial load ───
  useEffect(() => {
    let cancelled = false;
    setStatus('loading');
    secretChatApi.get(token, { clientId, hostKey })
      .then(data => {
        if (cancelled) return;
        const history = data.messages || [];
        setSession(data);
        setMessages(history);
        setParticipants(data.participants || []);
        lastIdRef.current = history.reduce((max, message) => Math.max(max, message.id), 0);
        // Pick up where this browser left off, as the server recorded it.
        const cursor = (data.participants || []).find(item => item.client_id === clientId)?.last_read_id || 0;
        readRef.current = cursor;
        setLastReadId(cursor);
        // Only a returning reader gets a divider; for a first visit the whole room is new.
        const firstUnread = cursor
          ? history.find(message => message.id > cursor && (message.sender || '').split('|||')[1] !== clientId)
          : null;
        setUnreadMarkFrom(firstUnread?.id || 0);
        setStatus('ready');
      })
      .catch(failure => {
        if (cancelled) return;
        if (failure.status === 410) roomOver('ended', 'This private chat has ended.');
        else if (failure.status === 403) roomOver('expired', failure.message || 'This invite link has expired.');
        else roomOver('missing', failure.message || 'Chat not found.');
      });
    return () => { cancelled = true; };
  }, [token, clientId, hostKey, roomOver]);

  // ─── live stream ───
  useEffect(() => {
    if (status !== 'ready') return undefined;
    let cancelled = false;
    let retryDelay = 1000;
    let retryTimer = null;

    const handle = payload => {
      if (payload.type === 'purge') {
        const ids = new Set(payload.ids || []);
        setMessages(current => current.filter(message => !ids.has(message.id)));
        return;
      }
      if (payload.type === 'presence') {
        if (payload.participants) setParticipants(current => mergeParticipants(current, payload.participants));
        return;
      }
      if (payload.type === 'room') {
        if (payload.state === 'ended') roomOver('ended', 'This private chat has ended.');
        else refreshPresence();
        return;
      }
      applyMessages([payload]);
    };

    const connect = () => {
      if (cancelled) return;
      const source = new EventSource(secretChatApi.stream(token, lastIdRef.current));
      source.onopen = () => { retryDelay = 1000; };
      source.onmessage = event => {
        if (event.data === ': keepalive') return;
        try {
          handle(JSON.parse(event.data));
        } catch {
          // A malformed frame is dropped; the poll below reconciles anything missed.
        }
      };
      // The server sends a named `revoked` event when the room is deleted, then closes the
      // stream — without this the client would reconnect forever against a 404.
      source.addEventListener('revoked', () => {
        cancelled = true;
        source.close();
        roomOver('ended', 'This private chat has ended.');
      });
      source.onerror = () => {
        source.close();
        if (cancelled) return;
        retryTimer = setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 15000);
      };
      return source;
    };
    const source = connect();

    // Safety net: poll for missed messages in case the stream silently stalls.
    const poll = setInterval(() => {
      secretChatApi.getMessages(token, lastIdRef.current)
        .then(applyMessages)
        .catch(failure => {
          if (failure.status === 410) roomOver('ended', 'This private chat has ended.');
        });
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearTimeout(retryTimer);
      clearInterval(poll);
      source?.close();
    };
    // refreshPresence is intentionally not a dependency: it changes with every presence
    // response and would tear the stream down and rebuild it each time.
  }, [token, status, applyMessages, roomOver]);

  // ─── presence heartbeat ───
  const refreshPresence = useCallback(() => {
    if (status !== 'ready') return;
    const typing = Date.now() < typingUntilRef.current;
    secretChatApi.presence(token, {
      client_id: clientId,
      name: senderRef.current || 'Anonymous',
      role: isHost ? 'host' : 'guest',
      host_key: hostKey,
      typing,
      last_read_id: readRef.current,
      ...clientProfile(),
    })
      .then(data => {
        setParticipants(data.participants || []);
        if (data.room) setSession(current => (current ? { ...current, ...data.room } : current));
      })
      .catch(failure => {
        if (failure.status === 410) roomOver('ended', 'This private chat has ended.');
      });
  }, [token, clientId, hostKey, isHost, status, roomOver]);

  useEffect(() => {
    if (status !== 'ready') return undefined;
    refreshPresence();
    const timer = setInterval(refreshPresence, PRESENCE_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [status, refreshPresence]);

  // Re-announce immediately when the tab comes back, so "online" is accurate on return.
  useEffect(() => {
    const onVisible = () => { if (document.visibilityState === 'visible') refreshPresence(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [refreshPresence]);

  // ─── auto-disappear ───
  // A one-second tick lets the UI count messages down and drop them the moment they
  // expire, instead of waiting for the server's next purge broadcast.
  const ttlSeconds = session?.message_ttl_seconds || 0;
  useEffect(() => {
    if (!ttlSeconds) return undefined;
    const timer = setInterval(() => setTick(value => value + 1), 1000);
    return () => clearInterval(timer);
  }, [ttlSeconds]);

  const visibleMessages = useMemo(() => {
    if (!ttlSeconds) return messages;
    const now = Date.now();
    return messages.filter(message => !message.expires_at || parseServerTime(message.expires_at) > now);
    // `tick` is the point: it re-runs the filter every second so expired messages leave.
  }, [messages, ttlSeconds, tick]);

  // ─── actions ───
  const updateSender = useCallback(name => {
    setSender(name);
    window.localStorage.setItem('secret-chat-sender', name);
  }, []);

  const signalTyping = useCallback(() => {
    const wasTyping = Date.now() < typingUntilRef.current;
    typingUntilRef.current = Date.now() + TYPING_HOLD_MS;
    if (!wasTyping) refreshPresence();
  }, [refreshPresence]);

  const send = useCallback(async (content, { viaAi = false } = {}) => {
    const text = content.trim();
    if (!text) return null;
    typingUntilRef.current = 0;
    const message = await secretChatApi.sendMessage(token, `${senderRef.current || 'Anonymous'}|||${clientId}`, text, viaAi);
    applyMessages([message]);
    readRef.current = Math.max(readRef.current, message.id);
    setLastReadId(readRef.current);
    return message;
  }, [token, clientId, applyMessages]);

  const markRead = useCallback(() => {
    const newest = messages.reduce((max, message) => Math.max(max, message.id), 0);
    if (newest <= readRef.current) return;
    readRef.current = newest;
    setLastReadId(newest);
  }, [messages]);

  // Push the cursor as soon as it moves: the roster's unread badges and everyone else's
  // read receipts are driven by it, so waiting for the next heartbeat is too slow.
  useEffect(() => {
    if (status !== 'ready' || !lastReadId) return;
    refreshPresence();
  }, [lastReadId, status, refreshPresence]);

  // A room being left still owes the server its final read position.
  useEffect(() => () => {
    if (!readRef.current) return;
    secretChatApi.presence(token, {
      client_id: clientId,
      name: senderRef.current || 'Anonymous',
      role: isHost ? 'host' : 'guest',
      host_key: hostKey,
      typing: false,
      last_read_id: readRef.current,
      ...clientProfile(),
    }).catch(() => {
      // Best effort on the way out; the next visit re-syncs the cursor anyway.
    });
  }, [token, clientId, hostKey, isHost]);

  const me = participants.find(item => item.client_id === clientId) || null;
  const others = participants.filter(item => item.client_id !== clientId);
  const typingNames = others.filter(item => item.typing).map(item => item.name);
  const onlineCount = participants.filter(item => item.online).length;
  const unreadFromOthers = visibleMessages.filter(
    message => message.id > lastReadId && (message.sender || '').split('|||')[1] !== clientId,
  );

  return {
    clientId,
    session,
    setSession,
    messages: visibleMessages,
    participants,
    me,
    others,
    typingNames,
    onlineCount,
    sender,
    updateSender,
    status,
    error,
    send,
    signalTyping,
    markRead,
    lastReadId,
    unreadCount: unreadFromOthers.length,
    firstUnreadId: unreadMarkFrom,
    refreshPresence,
    ttlSeconds,
  };
}
