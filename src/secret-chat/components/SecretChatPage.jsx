import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Ban, ChevronDown, Eraser, Flame, Menu, MessageCircle, Send, SlidersHorizontal, Trash2, Users } from 'lucide-react';
import TextareaAutosize from 'react-textarea-autosize';
import { useStickToBottom } from 'use-stick-to-bottom';
import { secretChatApi } from '../api';
import { chatShareUrl } from '../links';
import { hostKey as readHostKey } from '../identity';
import { useSecretChatRoom } from '../useSecretChatRoom';
import ShareMenu from './ShareMenu';
import ChatThread from './ChatThread';
import GuestsPanel from './GuestsPanel';
import AiCopilot from './AiCopilot';
import TelegramConnect from './TelegramConnect';
import { DISAPPEAR_OPTIONS, LINK_EXPIRY_OPTIONS, ROOM_EXPIRY_OPTIONS, ttlLabel } from './PrivateChatsPage';
import { useChatViewportLock, useCompactViewport, useRepinOnResize } from '../../hooks/useChatViewport';

function RoomOptionsMenu({
  session, title, onTitleChange, onTitleCommit, sender, onSenderChange, onSave, onClear, onDelete, close,
}) {
  const ttl = session?.message_ttl_seconds || 0;
  return (
    <div className="room-options-menu" role="menu">
      <div className="room-options-group">
        <span className="room-options-label">Chat name</span>
        <input
          className="room-options-input"
          value={title}
          onChange={event => onTitleChange(event.target.value)}
          onBlur={onTitleCommit}
          onKeyDown={event => { if (event.key === 'Enter') event.target.blur(); }}
          maxLength={160}
          aria-label="Chat name"
        />
      </div>
      <div className="room-options-group">
        <span className="room-options-label">Your name</span>
        <input
          className="room-options-input"
          value={sender}
          onChange={event => onSenderChange(event.target.value)}
          maxLength={60}
          placeholder="Your name"
          aria-label="Your name"
        />
      </div>
      <div className="room-options-group">
        <span className="room-options-label"><Flame size={12} /> Disappearing messages</span>
        <div className="room-option-choices">
          {DISAPPEAR_OPTIONS.map(option => (
            <button
              type="button"
              key={option.value}
              className={ttl === option.value ? 'active' : ''}
              onClick={() => onSave({ message_ttl_seconds: option.value })}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>
      <div className="room-options-group">
        <span className="room-options-label">Invite link expires in</span>
        <div className="room-option-choices">
          {LINK_EXPIRY_OPTIONS.map(option => (
            <button type="button" key={option.value} onClick={() => onSave({ link_expiry_minutes: option.value })}>
              {option.label}
            </button>
          ))}
        </div>
      </div>
      <div className="room-options-group">
        <span className="room-options-label">Delete the whole chat in</span>
        <div className="room-option-choices">
          {ROOM_EXPIRY_OPTIONS.map(option => (
            <button type="button" key={option.value} onClick={() => onSave({ room_expiry_minutes: option.value })}>
              {option.label}
            </button>
          ))}
        </div>
      </div>
      <div className="room-options-danger">
        <button type="button" onClick={() => { close(); onClear(); }}><Eraser size={13} /> Clear all messages</button>
        <button type="button" className="danger" onClick={() => { close(); onDelete(); }}><Trash2 size={13} /> Delete this chat</button>
      </div>
    </div>
  );
}

export default function SecretChatPage({ token, onBack, onChanged, onRevoked, openRail, toast, requestConfirm }) {
  const confirm = requestConfirm;
  const hostKey = readHostKey();
  const room = useSecretChatRoom({ token, hostKey, isHost: true });
  const [input, setInput] = useState('');
  const [showGuests, setShowGuests] = useState(false);
  const [showOptions, setShowOptions] = useState(false);
  const [title, setTitle] = useState('');
  const inputRef = useRef(null);
  const optionsRef = useRef(null);

  useChatViewportLock();
  const compactViewport = useCompactViewport();
  const { scrollRef, contentRef, isAtBottom, scrollToBottom } = useStickToBottom({
    initial: 'instant',
    resize: 'smooth',
  });

  // Keyboard, rotation and a resizing composer all change the list container's height
  // rather than its content; see useRepinOnResize.
  const setMessagesResizeTarget = useRepinOnResize(scrollToBottom);
  const messagesScrollRef = useCallback(node => {
    scrollRef(node);
    setMessagesResizeTarget(node);
  }, [scrollRef, setMessagesResizeTarget]);

  // Keep the editable title in step with the room, including renames from another tab.
  useEffect(() => {
    setTitle(room.session?.title || 'Private');
  }, [room.session?.title]);

  // Reading only counts while the newest messages are actually on screen.
  useEffect(() => {
    if (isAtBottom && document.visibilityState === 'visible') room.markRead();
  }, [isAtBottom, room.messages.length, room]);

  useEffect(() => {
    if (!showOptions) return undefined;
    const onPointerDown = event => {
      if (optionsRef.current && !optionsRef.current.contains(event.target)) setShowOptions(false);
    };
    window.addEventListener('mousedown', onPointerDown);
    return () => window.removeEventListener('mousedown', onPointerDown);
  }, [showOptions]);

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
    } catch (error) {
      toast?.(error.message || 'Message not sent', 'error');
    }
  };

  const sendText = async (text, options) => {
    scrollToBottom({ ignoreEscapes: true });
    return room.send(text, options);
  };

  const saveOptions = async (patch, { announce = true } = {}) => {
    try {
      const updated = await secretChatApi.updateOptions(token, { host_key: hostKey, ...patch });
      room.setSession(updated);
      onChanged?.();
      if (announce) toast?.('Chat settings updated');
      return updated;
    } catch (error) {
      toast?.(error.message || 'Could not update the chat', 'error');
      return null;
    }
  };

  const commitTitle = async () => {
    const next = title.trim() || 'Private';
    setTitle(next);
    if (next === room.session?.title) return;
    const updated = await saveOptions({ title: next }, { announce: false });
    if (!updated) setTitle(room.session?.title || 'Private');
  };

  const clearMessages = () => confirm({
    title: 'Clear all messages?',
    message: 'Every message in this chat is deleted for everyone. The chat and its link stay alive.',
    confirmLabel: 'Clear messages',
    onConfirm: async () => {
      await secretChatApi.clearMessages(token, hostKey);
      onChanged?.();
      toast?.('Messages cleared');
    },
  });

  const deleteRoom = () => confirm({
    title: 'Delete this chat?',
    message: 'Every message will be permanently deleted and the shared link will stop working for everyone who has it.',
    confirmLabel: 'Delete and revoke link',
    onConfirm: async () => {
      await secretChatApi.deleteRoom(token, hostKey);
      toast?.('Private chat deleted · link revoked');
      onRevoked?.();
    },
  });

  if (room.status === 'loading') {
    return (
      <div className="secret-chat-loading">
        <MessageCircle size={32} style={{ opacity: 0.4 }} />
      </div>
    );
  }

  if (room.status !== 'ready') {
    return (
      <div className="secret-chat-shell">
        <div className="secret-chat-revoked">
          <Ban size={40} />
          <h2>This chat is no longer available</h2>
          <p>{room.error || 'The chat was deleted, so its link no longer works.'}</p>
          {onBack && <button type="button" className="btn-primary" onClick={onBack}>Back</button>}
        </div>
      </div>
    );
  }

  const shareUrl = chatShareUrl(token);
  const ttl = room.ttlSeconds;

  return (
    <div className={`secret-chat-shell${showGuests ? ' with-guests' : ''}`}>
      <header className="secret-chat-header">
        {openRail && (
          <button type="button" className="secret-chat-rail-btn icon-button" onClick={openRail} aria-label="Open private chat list">
            <Menu size={18} />
          </button>
        )}
        <button className="secret-chat-back-btn" onClick={onBack}>← Back</button>
        <div className="secret-chat-meta">
          <div className="secret-chat-title-row">
            <Users size={16} />
            <span className="secret-chat-title-text" title={title}>{title}</span>
            <span className="live-badge" title={`${room.onlineCount} online right now`}>
              <span className="live-dot" aria-hidden="true" />
              {room.onlineCount} online
            </span>
            {ttl > 0 && (
              <span className="ttl-badge" title="Messages delete themselves">
                <Flame size={11} /> {ttlLabel(ttl)}
              </span>
            )}
          </div>
          {room.typingNames.length > 0 && (
            <div className="secret-chat-sender-row">
              <span className="header-typing">{room.typingNames.join(', ')} typing…</span>
            </div>
          )}
        </div>
        <div className="secret-chat-actions">
          <button
            type="button"
            className={`secret-chat-icon-btn${showGuests ? ' active' : ''}`}
            onClick={() => setShowGuests(value => !value)}
            aria-pressed={showGuests}
            title="Who is in this chat"
          >
            <Users size={14} /> {room.participants.length}
          </button>
          <div className="room-options-wrap" ref={optionsRef}>
            <button
              type="button"
              className={`secret-chat-icon-btn${showOptions ? ' active' : ''}`}
              onClick={() => setShowOptions(value => !value)}
              aria-expanded={showOptions}
              title="Chat settings"
            >
              <SlidersHorizontal size={14} />
            </button>
            {showOptions && (
              <RoomOptionsMenu
                session={room.session}
                title={title}
                onTitleChange={setTitle}
                onTitleCommit={commitTitle}
                sender={room.sender}
                onSenderChange={room.updateSender}
                onSave={saveOptions}
                onClear={clearMessages}
                onDelete={deleteRoom}
                close={() => setShowOptions(false)}
              />
            )}
          </div>
          <TelegramConnect token={token} hostKey={hostKey} toast={toast} onChanged={onChanged} />
          <ShareMenu url={shareUrl} title={room.session?.title} />
        </div>
      </header>

      <div className="secret-chat-body">
        <div className="secret-chat-messages" ref={messagesScrollRef}>
          <ChatThread
            prefix="secret-chat"
            messages={room.messages}
            clientId={room.clientId}
            participants={room.participants}
            typingNames={room.typingNames}
            firstUnreadId={room.firstUnreadId}
            ttlSeconds={ttl}
            innerRef={contentRef}
          />
        </div>
        {showGuests && (
          <GuestsPanel
            participants={room.participants}
            clientId={room.clientId}
            onClose={() => setShowGuests(false)}
          />
        )}
      </div>

      <div className="secret-chat-composer-stack">
        <AiCopilot
          token={token}
          hostKey={hostKey}
          clientId={room.clientId}
          sender={room.sender}
          session={room.session}
          composerText={input}
          onInsert={text => { setInput(text); inputRef.current?.focus(); }}
          onSend={sendText}
          onOptionsChange={room.setSession}
          toast={toast}
        />
        <form className="secret-chat-composer" onSubmit={send}>
          {!isAtBottom && room.messages.length > 0 && (
            <button
              type="button"
              className="secret-chat-jump-btn"
              onPointerDown={event => event.preventDefault()}
              onClick={() => scrollToBottom()}
              aria-label="Jump to latest message"
            >
              <ChevronDown size={16} /> {room.unreadCount > 0 ? `${room.unreadCount} new` : 'Latest'}
            </button>
          )}
          <TextareaAutosize
            ref={inputRef}
            className="secret-chat-input"
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
            className={`secret-chat-send-btn${input.trim() ? ' active' : ' disabled'}`}
            // Swallow the focus change on press: without this the textarea blurs and the
            // on-screen keyboard slams shut the moment the message is sent.
            onPointerDown={event => event.preventDefault()}
            onMouseDown={event => event.preventDefault()}
          >
            <Send size={18} />
          </button>
        </form>
      </div>
    </div>
  );
}
