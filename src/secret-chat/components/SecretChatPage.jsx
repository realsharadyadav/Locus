import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronDown, MessageCircle, Send, User, Users } from 'lucide-react';
import TextareaAutosize from 'react-textarea-autosize';
import { useStickToBottom } from 'use-stick-to-bottom';
import { secretChatApi } from '../api';
import { chatShareUrl } from '../links';
import ShareMenu from './ShareMenu';
import { parseServerTime } from '../../utils';
import { timeLabel, withMessageGrouping } from '../messageGroups';
import { useChatViewportLock, useCompactViewport, useRepinOnResize } from '../../hooks/useChatViewport';

export default function SecretChatPage({ token, onBack }) {
  const [session, setSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [sender, setSender] = useState(() => window.localStorage.getItem('secret-chat-sender') || 'Anonymous');
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
      const msg = await secretChatApi.sendMessage(token, sender, content);
      setMessages(prev => prev.some(m => m.id === msg.id) ? prev : [...prev, msg]);
      lastIdRef.current = Math.max(lastIdRef.current, msg.id);
    } catch {}
  };

  const shareUrl = chatShareUrl(token);

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
          <span className="secret-chat-url-preview">{shareUrl.replace(/^https?:\/\//, '')}</span>
          <ShareMenu url={shareUrl} title={session?.title} />
        </div>
      </header>

      <div className="secret-chat-messages" ref={messagesScrollRef}>
        <div className="secret-chat-messages-inner" ref={contentRef}>
          {messages.length === 0 && (
            <div className="secret-chat-empty">
              <MessageCircle size={40} />
              <p>No messages yet</p>
              <small>Share the link and start chatting</small>
            </div>
          )}
          {withMessageGrouping(messages).map(({ msg, at, newDay, startsRun, day }) => {
            const [displayName] = (msg.sender || '').split('|||');
            const side = msg.sender === sender ? 'self' : 'other';
            return (
              <React.Fragment key={msg.id}>
                {newDay && (
                  <div className="secret-chat-day"><span>{day}</span></div>
                )}
                <div className={`secret-chat-msg-wrap ${side} ${startsRun ? 'run-start' : 'run-cont'}`}>
                  {startsRun && (
                    <div className="secret-chat-msg-sender">
                      {displayName || msg.sender} · {timeLabel(at)}
                    </div>
                  )}
                  <div
                    className={`secret-chat-msg-bubble ${side}`}
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

      <form className="secret-chat-composer" onSubmit={send}>
        {!isAtBottom && messages.length > 0 && (
          <button
            type="button"
            className="secret-chat-jump-btn"
            onPointerDown={e => e.preventDefault()}
            onClick={() => scrollToBottom()}
            aria-label="Jump to latest message"
          >
            <ChevronDown size={16} /> Latest
          </button>
        )}
        <TextareaAutosize
          ref={inputRef}
          className="secret-chat-input"
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
          className={`secret-chat-send-btn${input.trim() ? ' active' : ' disabled'}`}
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
