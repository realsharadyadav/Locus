import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronDown, Eraser, Flame, MessageCircle, Send, User, Users } from 'lucide-react';
import TextareaAutosize from 'react-textarea-autosize';
import { useStickToBottom } from 'use-stick-to-bottom';
import { chatShareUrl } from '../links';
import { useSecretChatRoom } from '../useSecretChatRoom';
import ShareMenu from './ShareMenu';
import ChatThread from './ChatThread';
import { readStorage } from '../../brand';
import { useChatViewportLock, useCompactViewport, useRepinOnResize } from '../../hooks/useChatViewport';

const ttlLabel = seconds => {
  if (!seconds) return '';
  if (seconds % 3600 === 0) return `${seconds / 3600}h`;
  if (seconds % 60 === 0) return `${seconds / 60}m`;
  return `${seconds}s`;
};

export default function SecretChatStandalone({ token }) {
  const room = useSecretChatRoom({ token });
  const [input, setInput] = useState('');
  const inputRef = useRef(null);

  useChatViewportLock();
  const compactViewport = useCompactViewport();
  const { scrollRef, contentRef, isAtBottom, scrollToBottom } = useStickToBottom({
    initial: 'instant',
    resize: 'smooth',
  });

  // Guests never mount the app shell, so the theme attribute and the tab title it normally
  // sets have to be applied here. The title stays about the chat, not the product.
  useEffect(() => {
    document.documentElement.dataset.theme = readStorage('theme') || 'dark';
  }, []);

  useEffect(() => {
    const title = room.session?.title?.trim();
    document.title = title && title !== 'Private' ? `${title} · Private chat` : 'Private chat';
  }, [room.session?.title]);

  // Keyboard, rotation and a resizing composer all change the list container's height
  // rather than its content; see useRepinOnResize.
  const setMessagesResizeTarget = useRepinOnResize(scrollToBottom);
  const messagesScrollRef = useCallback(node => {
    scrollRef(node);
    setMessagesResizeTarget(node);
  }, [scrollRef, setMessagesResizeTarget]);

  useEffect(() => {
    if (isAtBottom && document.visibilityState === 'visible') room.markRead();
  }, [isAtBottom, room.messages.length, room]);

  const send = async event => {
    event?.preventDefault();
    const content = input.trim();
    if (!content) return;
    setInput('');
    // Stay focused so the on-screen keyboard does not collapse between messages.
    inputRef.current?.focus();
    scrollToBottom({ ignoreEscapes: true });
    try {
      await room.send(content);
    } catch {
      // A failed send leaves the room state untouched; the stream reconciles on retry.
    }
  };

  if (room.status === 'loading') {
    return (
      <div className="scs-loading">
        <div className="scs-spinner" />
      </div>
    );
  }

  if (room.status !== 'ready') {
    return (
      <div className="scs-loading">
        <div className="scs-error">
          <MessageCircle size={32} />
          <p>{room.error || 'Chat not found or expired'}</p>
        </div>
      </div>
    );
  }

  const ttl = room.ttlSeconds;

  return (
    <div className="scs">
      <header className="scs-header">
        <div className="scs-header-left">
          <Users size={16} className="scs-header-icon" />
          <strong>{room.session?.title || 'Private'}</strong>
          <span className="live-badge" title={`${room.onlineCount} online right now`}>
            <span className="live-dot" aria-hidden="true" />
            {room.onlineCount}
          </span>
          {ttl > 0 && (
            <span className="ttl-badge" title="Messages delete themselves in this chat">
              <Flame size={11} /> {ttlLabel(ttl)}
            </span>
          )}
        </div>
        <div className="scs-header-right">
          <User size={12} />
          <input
            className="scs-name-edit"
            value={room.sender}
            onChange={event => room.updateSender(event.target.value)}
            maxLength={60}
            placeholder="Your name"
          />
          <button
            type="button"
            className="scs-clear-btn"
            onClick={room.clearOnThisDevice}
            aria-label="Clear this chat on my device"
            title="Clear this chat on my device"
            disabled={room.messages.length === 0}
          >
            <Eraser size={14} />
          </button>
          <ShareMenu url={chatShareUrl(token)} title={room.session?.title} variant="standalone" />
        </div>
      </header>

      <div className="scs-messages" ref={messagesScrollRef}>
        <ChatThread
          prefix="scs"
          messages={room.messages}
          clientId={room.clientId}
          participants={room.participants}
          typingNames={room.typingNames}
          firstUnreadId={room.firstUnreadId}
          ttlSeconds={ttl}
          emptyHint="Send the first message to start the conversation"
          innerRef={contentRef}
        />
      </div>

      <form className="scs-composer" onSubmit={send}>
        {!isAtBottom && room.messages.length > 0 && (
          <button
            type="button"
            className="scs-jump-btn"
            onPointerDown={event => event.preventDefault()}
            onClick={() => scrollToBottom()}
            aria-label="Jump to latest message"
          >
            <ChevronDown size={16} /> {room.unreadCount > 0 ? `${room.unreadCount} new` : 'Latest'}
          </button>
        )}
        <TextareaAutosize
          ref={inputRef}
          className="scs-input"
          value={input}
          onChange={event => { setInput(event.target.value); room.signalTyping(); }}
          onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(event); } }}
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
          onPointerDown={event => event.preventDefault()}
          onMouseDown={event => event.preventDefault()}
        >
          <Send size={18} />
        </button>
      </form>
    </div>
  );
}
