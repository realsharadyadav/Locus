import React, { useEffect, useRef, useState } from 'react';
import { ChevronDown, Link2, MessageCircle, Send, User, Users } from 'lucide-react';
import { secretChatApi } from '../api';
import { parseServerTime, resizeTextarea } from '../../utils';
import { useVisualViewportShell } from '../../hooks/useVisualViewportShell';

export default function SecretChatPage({ token, onBack }) {
  const [session, setSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [sender, setSender] = useState(() => window.localStorage.getItem('secret-chat-sender') || 'Anonymous');
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(true);
  const [copyMsg, setCopyMsg] = useState('');
  const [showJump, setShowJump] = useState(false);
  const bottomRef = useRef(null);
  const messagesRef = useRef(null);
  const inputRef = useRef(null);
  const eventSourceRef = useRef(null);
  const lastIdRef = useRef(0);
  const setShellEl = useVisualViewportShell();

  useEffect(() => {
    secretChatApi.get(token).then(data => {
      setSession(data);
      setMessages(data.messages || []);
      lastIdRef.current = (data.messages || []).reduce((m, msg) => Math.max(m, msg.id), 0);
      setLoading(false);
    }).catch(() => {
      setLoading(false);
    });
  }, [token]);

  useEffect(() => {
    if (loading) return;
    let cancelled = false;
    let retryDelay = 1000;
    let retryTimer = null;

    const connect = () => {
      if (cancelled) return;
      const es = new EventSource(secretChatApi.stream(token, lastIdRef.current));
      eventSourceRef.current = es;
      es.onopen = () => { retryDelay = 1000; };
      es.onmessage = (event) => {
        if (event.data === ': keepalive') return;
        try {
          const msg = JSON.parse(event.data);
          setMessages(prev => {
            if (prev.some(m => m.id === msg.id)) return prev;
            return [...prev, msg];
          });
          lastIdRef.current = Math.max(lastIdRef.current, msg.id);
        } catch {}
      };
      es.onerror = () => {
        es.close();
        if (cancelled) return;
        retryTimer = setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 15000);
      };
    };
    connect();

    // Safety net: poll for missed messages in case the stream silently stalls.
    const poll = setInterval(() => {
      secretChatApi.getMessages(token, lastIdRef.current).then(newMessages => {
        if (!newMessages || newMessages.length === 0) return;
        setMessages(prev => {
          const existingIds = new Set(prev.map(m => m.id));
          const additions = newMessages.filter(m => !existingIds.has(m.id));
          if (additions.length === 0) return prev;
          return [...prev, ...additions];
        });
        lastIdRef.current = newMessages.reduce((m, msg) => Math.max(m, msg.id), lastIdRef.current);
      }).catch(() => {});
    }, 8000);

    return () => {
      cancelled = true;
      clearTimeout(retryTimer);
      clearInterval(poll);
      eventSourceRef.current?.close();
    };
  }, [token, loading]);

  useEffect(() => {
    const el = messagesRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    if (nearBottom) bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    else setShowJump(true);
  }, [messages]);

  const handleMessagesScroll = () => {
    const el = messagesRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    if (nearBottom) setShowJump(false);
  };

  const jumpToBottom = () => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    setShowJump(false);
  };

  const send = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;
    const content = input.trim();
    setInput('');
    window.setTimeout(() => resizeTextarea(inputRef.current), 0);
    try {
      const msg = await secretChatApi.sendMessage(token, sender, content);
      setMessages(prev => prev.some(m => m.id === msg.id) ? prev : [...prev, msg]);
      lastIdRef.current = Math.max(lastIdRef.current, msg.id);
    } catch {}
  };

  const shareUrl = `${window.location.origin}/secret-chat/${token}`;

  const copyLink = () => {
    navigator.clipboard.writeText(shareUrl).then(() => {
      setCopyMsg('Copied!');
      setTimeout(() => setCopyMsg(''), 2000);
    });
  };

  const updateSender = (name) => {
    setSender(name);
    window.localStorage.setItem('secret-chat-sender', name);
  };

  if (loading) {
    return (
      <div className="secret-chat-loading">
        <MessageCircle size={32} style={{ opacity: 0.4 }} />
      </div>
    );
  }

  return (
    <div className="secret-chat-shell" ref={setShellEl}>
      <header className="secret-chat-header">
        <button className="secret-chat-back-btn" onClick={onBack}>← Back</button>
        <div className="secret-chat-meta">
          <div className="secret-chat-title-row">
            <Users size={16} />
            <strong>{session?.title || 'Private'}</strong>
          </div>
          <div className="secret-chat-sender-row">
            <User size={12} />
            <input
              className="secret-chat-sender-input"
              value={sender}
              onChange={e => updateSender(e.target.value)}
              maxLength={60}
              placeholder="Your name"
            />
          </div>
        </div>
        <div className="secret-chat-actions">
          <span className="secret-chat-url-preview">{shareUrl.slice(0, 40)}…</span>
          <button className={`secret-chat-copy-btn${copyMsg ? ' copied' : ''}`} onClick={copyLink}>
            {copyMsg ? <span>{copyMsg}</span> : <><Link2 size={14} /> Share link</>}
          </button>
        </div>
      </header>

      <div className="secret-chat-messages" ref={messagesRef} onScroll={handleMessagesScroll}>
        {messages.length === 0 && (
          <div className="secret-chat-empty">
            <MessageCircle size={40} />
            <p>No messages yet</p>
            <small>Share the link and start chatting</small>
          </div>
        )}
        {messages.map(msg => {
          const [displayName] = (msg.sender || '').split('|||');
          return (
            <div key={msg.id} className={`secret-chat-msg-wrap${msg.sender === sender ? ' self' : ' other'}`}>
              <div className="secret-chat-msg-sender">
                {displayName || msg.sender} · {new Date(parseServerTime(msg.created_at)).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </div>
              <div className={`secret-chat-msg-bubble${msg.sender === sender ? ' self' : ' other'}`}>
                {msg.content}
              </div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      {showJump && (
        <button type="button" className="secret-chat-jump-btn" onClick={jumpToBottom} aria-label="Jump to latest message">
          <ChevronDown size={16} /> New messages
        </button>
      )}

      <form className="secret-chat-composer" onSubmit={send}>
        <textarea
          ref={inputRef}
          className="secret-chat-input"
          value={input}
          onChange={e => { setInput(e.target.value); resizeTextarea(e.target); }}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(e); } }}
          placeholder="Type a message..."
          maxLength={2000}
          rows={1}
        />
        <button
          type="submit"
          disabled={!input.trim()}
          className={`secret-chat-send-btn${input.trim() ? ' active' : ' disabled'}`}
          onMouseDown={e => e.preventDefault()}
        >
          <Send size={18} />
        </button>
      </form>
    </div>
  );
}
