import React from 'react';
import { MessageCircle, Sparkles, Timer } from 'lucide-react';
import { parseServerTime } from '../../utils';
import { timeLabel, withMessageGrouping } from '../messageGroups';

const countdown = (expiresAt, now) => {
  const remaining = Math.max(0, Math.round((parseServerTime(expiresAt) - now) / 1000));
  const minutes = Math.floor(remaining / 60);
  return minutes ? `${minutes}m ${String(remaining % 60).padStart(2, '0')}s` : `${remaining}s`;
};

/**
 * The message list, shared by the in-app and standalone views. `prefix` selects the class
 * namespace so each view keeps its own layout while the behaviour stays in one place.
 */
export default function ChatThread({
  prefix,
  messages,
  clientId,
  participants = [],
  typingNames = [],
  firstUnreadId = 0,
  ttlSeconds = 0,
  emptyTitle = 'No messages yet',
  emptyHint = 'Share the link and start chatting',
  innerRef,
}) {
  const now = Date.now();
  const myLastMessage = [...messages].reverse().find(message => (message.sender || '').split('|||')[1] === clientId);

  const seenBy = message => participants
    .filter(item => item.client_id !== clientId && item.last_read_id >= message.id)
    .map(item => item.name);

  return (
    <div className={`${prefix}-messages-inner`} ref={innerRef}>
      {messages.length === 0 && typingNames.length === 0 && (
        <div className={`${prefix}-empty`}>
          <MessageCircle size={38} />
          <p>{emptyTitle}</p>
          <small>{emptyHint}</small>
        </div>
      )}

      {withMessageGrouping(messages).map(({ msg: message, at, newDay, startsRun, day }) => {
        const [displayName, messageClientId] = (message.sender || '').split('|||');
        const isSelf = messageClientId === clientId;
        const readers = isSelf && message.id === myLastMessage?.id ? seenBy(message) : [];
        const side = isSelf ? 'self' : 'other';
        return (
          <React.Fragment key={message.id}>
            {newDay && <div className={`${prefix}-day`}><span>{day}</span></div>}
            {firstUnreadId === message.id && (
              <div className="chat-unread-divider" role="separator"><span>New messages</span></div>
            )}
            <div className={`${prefix}-msg-wrap ${side} ${startsRun ? 'run-start' : 'run-cont'}${message.id >= firstUnreadId && firstUnreadId ? ' unread' : ''}`}>
              {/* A sender who says three things in a row is labelled once, not three times. */}
              {startsRun && (
                <div className={`${prefix}-msg-sender`}>
                  {displayName || message.sender} · {timeLabel(at)}
                  {message.via_ai && <span className="msg-ai-tag" title="Drafted by the AI copilot"><Sparkles size={10} /> AI</span>}
                </div>
              )}
              <div className={`${prefix}-msg-bubble ${side}`} title={`${displayName || message.sender} · ${timeLabel(at)}`}>
                {message.content}
              </div>
              <div className="msg-footnotes">
                {ttlSeconds > 0 && message.expires_at && (
                  <span className="msg-countdown" title="This message disappears for everyone">
                    <Timer size={10} /> {countdown(message.expires_at, now)}
                  </span>
                )}
                {readers.length > 0 && <span className="msg-seen">Seen by {readers.join(', ')}</span>}
                {!startsRun && message.via_ai && (
                  <span className="msg-ai-tag" title="Drafted by the AI copilot"><Sparkles size={10} /> AI</span>
                )}
              </div>
            </div>
          </React.Fragment>
        );
      })}

      {typingNames.length > 0 && (
        <div className={`${prefix}-msg-wrap other typing-row`}>
          <div className={`${prefix}-msg-sender`}>
            {typingNames.length === 1 ? `${typingNames[0]} is typing` : `${typingNames.join(', ')} are typing`}
          </div>
          <div className={`${prefix}-msg-bubble other typing-bubble`} aria-live="polite">
            <span className="typing-dot" /><span className="typing-dot" /><span className="typing-dot" />
          </div>
        </div>
      )}
    </div>
  );
}
