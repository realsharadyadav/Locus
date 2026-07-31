import React, { useCallback, useEffect, useState } from 'react';
import { Loader2, Send, Unlink } from 'lucide-react';
import { useClickOutside } from '../../hooks/useClickOutside';
import { secretChatApi } from '../api';

/**
 * Host-only: point this room at a phone number instead of a share link.
 *
 * The button only exists when the deployment actually has a Telegram account connected
 * (`/bridge/status`), because everything behind it fails without one. Everything here is
 * authorised by the host key — a link guest never sees the number or that a bridge exists.
 */
export default function TelegramConnect({ token, hostKey, toast, onChanged }) {
  const [status, setStatus] = useState(null);
  const [bridge, setBridge] = useState(null);
  const [open, setOpen] = useState(false);
  const [phone, setPhone] = useState('');
  const [greeting, setGreeting] = useState('');
  const [busy, setBusy] = useState(false);
  const wrapRef = useClickOutside(open, () => setOpen(false));

  useEffect(() => {
    let live = true;
    secretChatApi.bridgeStatus()
      .then(value => { if (live) setStatus(value); })
      .catch(() => { if (live) setStatus({ configured: false }); });
    return () => { live = false; };
  }, []);

  const loadBridge = useCallback(() => {
    secretChatApi.getBridge(token, hostKey)
      .then(setBridge)
      .catch(() => setBridge(null));
  }, [token, hostKey]);

  useEffect(() => {
    if (status?.configured) loadBridge();
  }, [status, loadBridge]);

  if (!status?.configured) return null;

  const link = async () => {
    if (!phone.trim() || busy) return;
    setBusy(true);
    try {
      const linked = await secretChatApi.linkBridge(token, {
        host_key: hostKey,
        platform: 'telegram',
        phone: phone.trim(),
        greeting: greeting.trim(),
      });
      setBridge(linked);
      setPhone('');
      setGreeting('');
      setOpen(false);
      toast?.(`Connected to ${linked.peer_name || linked.phone} on Telegram`);
      onChanged?.();
    } catch (error) {
      toast?.(error.message, 'error');
    } finally {
      setBusy(false);
    }
  };

  const unlink = async () => {
    setBusy(true);
    try {
      await secretChatApi.unlinkBridge(token, hostKey);
      setBridge(null);
      setOpen(false);
      toast?.('Telegram disconnected');
      onChanged?.();
    } catch (error) {
      toast?.(error.message, 'error');
    } finally {
      setBusy(false);
    }
  };

  const connected = Boolean(bridge);
  const label = connected ? (bridge.peer_name || bridge.phone) : 'Telegram';

  return (
    <div className="room-options-wrap" ref={wrapRef}>
      <button
        type="button"
        className={`secret-chat-icon-btn${connected ? ' bridged' : ''}${open ? ' active' : ''}`}
        onClick={() => setOpen(value => !value)}
        aria-expanded={open}
        aria-label={connected ? `Connected to ${label} on Telegram` : 'Connect this chat to a phone number'}
        title={connected ? `Connected to ${label} on Telegram` : 'Connect this chat to a phone number'}
      >
        <Send size={13} />
      </button>
      {open && (
        <div className="room-options-menu bridge-menu" role="menu">
          {connected ? (
            <>
              <div className="room-options-group">
                <span className="room-options-label">Connected on Telegram</span>
                <p className="bridge-peer">{bridge.peer_name || bridge.phone}</p>
                <p className="bridge-note">
                  {bridge.phone}
                  {bridge.peer_username ? ` · @${bridge.peer_username}` : ''}
                </p>
              </div>
              <p className="bridge-note">
                Everything you send here goes to them as a normal Telegram message from your own
                account, and their replies land in this chat. Disappearing messages only clear
                Locus — what is on their phone stays there.
              </p>
              {bridge.last_error && <p className="bridge-error">{bridge.last_error}</p>}
              <div className="room-options-danger">
                <button type="button" className="danger" onClick={unlink} disabled={busy}>
                  <Unlink size={13} /> Disconnect
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="room-options-group">
                <span className="room-options-label">Guest's mobile number</span>
                <input
                  className="bridge-input"
                  value={phone}
                  onChange={event => setPhone(event.target.value)}
                  onKeyDown={event => { if (event.key === 'Enter') link(); }}
                  placeholder="+91 98765 43210"
                  inputMode="tel"
                  autoFocus
                />
                <p className="bridge-note">Include the country code. They need to be on Telegram.</p>
              </div>
              <div className="room-options-group">
                <span className="room-options-label">First message (optional)</span>
                <input
                  className="bridge-input"
                  value={greeting}
                  onChange={event => setGreeting(event.target.value)}
                  onKeyDown={event => { if (event.key === 'Enter') link(); }}
                  placeholder="hey, it's me"
                  maxLength={2000}
                />
              </div>
              <div className="room-options-danger">
                <button type="button" onClick={link} disabled={busy || !phone.trim()}>
                  {busy ? <Loader2 size={13} className="spin" /> : <Send size={13} />} Connect
                </button>
              </div>
              {status.account && (
                <p className="bridge-note">Messages will be sent from your Telegram account ({status.account}).</p>
              )}
              {status.error && <p className="bridge-error">{status.error}</p>}
            </>
          )}
        </div>
      )}
    </div>
  );
}
