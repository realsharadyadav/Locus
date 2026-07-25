import React, { useEffect, useRef, useState } from 'react';
import { MessageCircle, Send, User, Users } from 'lucide-react';
import { secretChatApi } from '../api';
import { parseServerTime } from '../../utils';

export default function SecretChatStandalone({ token }) {
  const [session, setSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [sender, setSender] = useState(() => window.localStorage.getItem('secret-chat-sender') || 'Anonymous');
  const [clientId] = useState(() => window.localStorage.getItem('secret-chat-client-id') || (() => {
    const id = Math.random().toString(36).slice(2, 10);
    window.localStorage.setItem('secret-chat-client-id', id);
    return id;
  })());
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(true);
  const bottomRef = useRef(null);
  const eventSourceRef = useRef(null);

  useEffect(() => {
    secretChatApi.get(token).then(data => {
      setSession(data);
      setMessages(data.messages || []);
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
      const msg = await secretChatApi.sendMessage(token, `${sender}|||${clientId}`, content);
      setMessages(prev => prev.some(m => m.id === msg.id) ? prev : [...prev, msg]);
    } catch {}
  };

  const updateSender = (name) => {
    setSender(name);
    window.localStorage.setItem('secret-chat-sender', name);
  };

  if (loading) {
    return (
      <div className="scs-loading">
        <div className="scs-spinner" />
      </div>
    );
  }

  if (!session) {
    return (
      <div className="scs-loading">
        <div className="scs-error">
          <MessageCircle size={32} />
          <p>Chat not found or expired</p>
        </div>
      </div>
    );
  }

  return (
    <div className="scs">
      <header className="scs-header">
        <div className="scs-header-left">
          <Users size={16} className="scs-header-icon" />
          <strong>{session.title || 'Private'}</strong>
        </div>
        <div className="scs-header-right">
          <User size={12} />
          <input
            className="scs-name-edit"
            value={sender}
            onChange={e => updateSender(e.target.value)}
            maxLength={60}
            placeholder="Your name"
          />
        </div>
      </header>

      <div className="scs-messages">
        {messages.length === 0 && (
          <div className="scs-empty">
            <MessageCircle size={36} />
            <p>No messages yet</p>
            <small>Send the first message to start the conversation</small>
          </div>
        )}
        {messages.map(msg => {
          const [displayName, msgClientId] = (msg.sender || '').split('|||');
          const isSelf = msgClientId === clientId;
          return (
            <div key={msg.id} className={`scs-msg ${isSelf ? 'self' : 'other'}`}>
              <div className="scs-msg-meta">
                {displayName || msg.sender} · {new Date(parseServerTime(msg.created_at)).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </div>
              <div className={`scs-msg-bubble ${isSelf ? 'self' : 'other'}`}>
                {msg.content}
              </div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      <form className="scs-composer" onSubmit={send}>
        <input
          className="scs-input"
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Type a message..."
          maxLength={2000}
        />
        <button type="submit" disabled={!input.trim()} className={`scs-send ${input.trim() ? 'active' : ''}`}>
          <Send size={18} />
        </button>
      </form>
    </div>
  );
}
