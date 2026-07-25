import React, { useEffect, useRef, useState } from 'react';
import { Link2, MessageCircle, Send, User, Users } from 'lucide-react';
import { secretChatApi } from '../api';
import { parseServerTime } from '../../utils';

export default function SecretChatPage({ token, onBack }) {
  const [session, setSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [sender, setSender] = useState(() => window.localStorage.getItem('secret-chat-sender') || 'Anonymous');
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(true);
  const [copyMsg, setCopyMsg] = useState('');
  const bottomRef = useRef(null);
  const eventSourceRef = useRef(null);
  const [lastId, setLastId] = useState(0);

  useEffect(() => {
    secretChatApi.get(token).then(data => {
      setSession(data);
      setMessages(data.messages || []);
      const maxId = (data.messages || []).reduce((m, msg) => Math.max(m, msg.id), 0);
      setLastId(maxId);
      setLoading(false);
    }).catch(() => {
      setLoading(false);
    });
  }, [token]);

  useEffect(() => {
    if (loading) return;
    const es = new EventSource(secretChatApi.stream(token, 0));
    eventSourceRef.current = es;
    es.onmessage = (event) => {
      if (event.data === ': keepalive') return;
      try {
        const msg = JSON.parse(event.data);
        setMessages(prev => {
          if (prev.some(m => m.id === msg.id)) return prev;
          return [...prev, msg];
        });
        setLastId(msg.id);
      } catch {}
    };
    es.onerror = () => {};
    return () => { es.close(); };
  }, [token, loading]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const send = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;
    const content = input.trim();
    setInput('');
    try {
      const msg = await secretChatApi.sendMessage(token, sender, content);
      setMessages(prev => prev.some(m => m.id === msg.id) ? prev : [...prev, msg]);
      setLastId(msg.id);
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
    <div className="secret-chat-shell">
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

      <div className="secret-chat-messages">
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

      <form className="secret-chat-composer" onSubmit={send}>
        <input
          className="secret-chat-input"
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Type a message..."
          maxLength={2000}
        />
        <button type="submit" disabled={!input.trim()} className={`secret-chat-send-btn${input.trim() ? ' active' : ' disabled'}`}>
          <Send size={18} />
        </button>
      </form>
    </div>
  );
}
