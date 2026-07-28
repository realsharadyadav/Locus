import React, { useState } from 'react';
import { useClickOutside } from '../../hooks/useClickOutside';
import { Check, Copy, Mail, MessageSquare, MoreHorizontal, Share2 } from 'lucide-react';

function WhatsAppIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12.04 2C6.58 2 2.13 6.45 2.13 11.91c0 1.75.46 3.45 1.32 4.95L2 22l5.28-1.38a9.9 9.9 0 0 0 4.76 1.21h.01c5.46 0 9.9-4.45 9.9-9.91 0-2.65-1.03-5.14-2.9-7.01A9.82 9.82 0 0 0 12.04 2Zm0 18.15h-.01a8.2 8.2 0 0 1-4.19-1.15l-.3-.18-3.12.82.83-3.05-.2-.31a8.2 8.2 0 0 1-1.26-4.37c0-4.54 3.7-8.23 8.25-8.23 2.2 0 4.27.86 5.83 2.42a8.18 8.18 0 0 1 2.41 5.82c0 4.54-3.7 8.23-8.24 8.23Zm4.52-6.16c-.25-.13-1.47-.72-1.69-.81-.23-.08-.39-.12-.56.13-.16.24-.64.8-.78.97-.14.16-.29.18-.54.06-.25-.13-1.05-.39-1.99-1.23-.74-.66-1.23-1.47-1.38-1.72-.14-.25-.01-.38.11-.5.11-.11.25-.29.37-.44.13-.14.17-.25.25-.41.09-.17.04-.31-.02-.44-.06-.12-.56-1.34-.76-1.84-.2-.48-.4-.42-.56-.43h-.47c-.17 0-.43.06-.66.31-.23.25-.87.85-.87 2.07s.89 2.4 1.02 2.56c.12.17 1.75 2.67 4.23 3.74.59.26 1.05.41 1.41.52.59.19 1.13.16 1.56.1.48-.07 1.47-.6 1.68-1.18.21-.58.21-1.08.14-1.18-.06-.11-.22-.17-.47-.29Z" />
    </svg>
  );
}

function TelegramIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M21.94 4.3 18.9 19.1c-.23 1.02-.84 1.27-1.7.79l-4.7-3.46-2.27 2.18c-.25.25-.46.46-.94.46l.33-4.78 8.7-7.86c.38-.34-.08-.53-.59-.19L6.98 13.02l-4.63-1.45c-1.01-.31-1.03-1 .21-1.49L20.63 2.8c.84-.31 1.57.19 1.31 1.5Z" />
    </svg>
  );
}

function XIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M18.24 2.25h3.31l-7.23 8.26 8.5 11.24h-6.65l-5.21-6.82-5.96 6.82H1.68l7.73-8.84L1.25 2.25h6.82l4.71 6.23 5.46-6.23Zm-1.16 17.52h1.83L7.01 4.13H5.05l12.03 15.64Z" />
    </svg>
  );
}

export default function ShareMenu({ url, title, variant = 'app' }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const wrapRef = useClickOutside(open, () => setOpen(false));

  const label = title?.trim() || 'Private';
  const message = `Join my private chat "${label}": ${url}`;
  const canNativeShare = typeof navigator !== 'undefined' && typeof navigator.share === 'function';

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      // Clipboard access is blocked outside a secure context; the visible link stays selectable.
      return;
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  // Targets that hand off to another app: opened in a new context so the chat keeps
  // streaming in this tab while the share app takes over.
  const handOff = href => {
    window.open(href, '_blank', 'noopener,noreferrer');
    setOpen(false);
  };

  const nativeShare = async () => {
    try {
      await navigator.share({ title: `${label} · private chat`, text: message, url });
    } catch {
      // A dismissed share sheet rejects; nothing to recover.
    }
    setOpen(false);
  };

  const targets = [
    {
      id: 'whatsapp',
      label: 'WhatsApp',
      Icon: WhatsAppIcon,
      onSelect: () => handOff(`https://wa.me/?text=${encodeURIComponent(message)}`),
    },
    {
      id: 'telegram',
      label: 'Telegram',
      Icon: TelegramIcon,
      onSelect: () => handOff(`https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(`Join my private chat "${label}"`)}`),
    },
    {
      id: 'sms',
      label: 'Messages',
      Icon: MessageSquare,
      // iOS wants sms:&body=, Android wants sms:?body= — "?&" satisfies both.
      onSelect: () => { window.location.href = `sms:?&body=${encodeURIComponent(message)}`; setOpen(false); },
    },
    {
      id: 'email',
      label: 'Email',
      Icon: Mail,
      onSelect: () => { window.location.href = `mailto:?subject=${encodeURIComponent(`Private chat: ${label}`)}&body=${encodeURIComponent(message)}`; setOpen(false); },
    },
    {
      id: 'x',
      label: 'X',
      Icon: XIcon,
      onSelect: () => handOff(`https://twitter.com/intent/tweet?text=${encodeURIComponent(message)}`),
    },
  ];

  if (canNativeShare) {
    targets.push({ id: 'more', label: 'More…', Icon: MoreHorizontal, onSelect: nativeShare });
  }

  return (
    <div className={`share-menu-wrap ${variant}`} ref={wrapRef}>
      <button
        type="button"
        className={`share-menu-trigger${open ? ' open' : ''}`}
        onClick={() => setOpen(value => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <Share2 size={14} /> Share
      </button>

      {open && (
        <div className="share-menu" role="menu" aria-label="Share this chat">
          <div className="share-menu-head">
            <strong>Invite to this chat</strong>
            <small>Anyone with the link can read and post here.</small>
          </div>

          <div className="share-menu-link">
            <input readOnly value={url} onFocus={event => event.target.select()} aria-label="Chat link" />
            <button type="button" className={copied ? 'copied' : ''} onClick={copyLink}>
              {copied ? <><Check size={13} /> Copied</> : <><Copy size={13} /> Copy</>}
            </button>
          </div>

          <div className="share-menu-targets">
            {targets.map(({ id, label: targetLabel, Icon, onSelect }) => (
              <button type="button" key={id} className={`share-target share-target-${id}`} onClick={onSelect} role="menuitem">
                <span className="share-target-icon"><Icon size={16} /></span>
                <span>{targetLabel}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
