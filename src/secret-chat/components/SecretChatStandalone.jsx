import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronDown, MessageCircle, Send, User, Users } from 'lucide-react';
import TextareaAutosize from 'react-textarea-autosize';
import { useStickToBottom } from 'use-stick-to-bottom';
import { secretChatApi } from '../api';
import { parseServerTime } from '../../utils';
import { timeLabel, withMessageGrouping } from '../messageGroups';
import { useChatViewportLock, useCompactViewport, useRepinOnResize } from '../../hooks/useChatViewport';

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
  const inputRef = useRef(null);
  const eventSourceRef = useRef(null);
  const lastIdRef = useRef(0);

  useChatViewportLock();
  const compactViewport = useCompactViewport();
  const { scrollRef, contentRef, isAtBottom, scrollToBottom } = useStickToBottom({
    initial: 'instant',
    resize: 'smooth',
  });

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

  // Keyboard, rotation and a resizing composer all change the list container's height
  // rather than its content; see useRepinOnResize.
  const setMessagesResizeTarget = useRepinOnResize(scrollToBottom);
  const messagesScrollRef = useCallback(node => {
    scrollRef(node);
    setMessagesResizeTarget(node);
  }, [scrollRef, setMessagesResizeTarget]);

  const send = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;
    const content = input.trim();
    setInput('');
    // Stay focused so the on-screen keyboard does not collapse between messages.
    inputRef.current?.focus();
    scrollToBottom({ ignoreEscapes: true });
    try {
      const msg = await secretChatApi.sendMessage(token, `${sender}|||${clientId}`, content);
      setMessages(prev => prev.some(m => m.id === msg.id) ? prev : [...prev, msg]);
      lastIdRef.current = Math.max(lastIdRef.current, msg.id);
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

      <div className="scs-messages" ref={messagesScrollRef}>
        <div className="scs-messages-inner" ref={contentRef}>
          {messages.length === 0 && (
            <div className="scs-empty">
              <MessageCircle size={36} />
              <p>No messages yet</p>
              <small>Send the first message to start the conversation</small>
            </div>
          )}
          {withMessageGrouping(messages).map(({ msg, at, newDay, startsRun, day }) => {
            const [displayName, msgClientId] = (msg.sender || '').split('|||');
            const isSelf = msgClientId === clientId;
            const side = isSelf ? 'self' : 'other';
            return (
              <React.Fragment key={msg.id}>
                {newDay && (
                  <div className="scs-day"><span>{day}</span></div>
                )}
                <div className={`scs-msg ${side} ${startsRun ? 'run-start' : 'run-cont'}`}>
                  {startsRun && (
                    <div className="scs-msg-meta">
                      {displayName || msg.sender} · {timeLabel(at)}
                    </div>
                  )}
                  <div
                    className={`scs-msg-bubble ${side}`}
                    title={`${displayName || msg.sender} · ${timeLabel(at)}`}
                  >
                    {msg.content}
                  </div>
                </div>
              </React.Fragment>
            );
          })}
        </div>
      </div>

      <form className="scs-composer" onSubmit={send}>
        {!isAtBottom && messages.length > 0 && (
          <button
            type="button"
            className="scs-jump-btn"
            onPointerDown={e => e.preventDefault()}
            onClick={() => scrollToBottom()}
            aria-label="Jump to latest message"
          >
            <ChevronDown size={16} /> Latest
          </button>
        )}
        <TextareaAutosize
          ref={inputRef}
          className="scs-input"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(e); } }}
          placeholder="Type a message..."
          maxLength={2000}
          minRows={1}
          maxRows={compactViewport ? 3 : 5}
          enterKeyHint="send"
        />
        <button
          type="submit"
          disabled={!input.trim()}
          className={`scs-send ${input.trim() ? 'active' : ''}`}
          // Swallow the focus change on press: without this the textarea blurs and the
          // on-screen keyboard slams shut the moment the message is sent.
          onPointerDown={e => e.preventDefault()}
          onMouseDown={e => e.preventDefault()}
        >
          <Send size={18} />
        </button>
      </form>
    </div>
  );
}
