import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Bot, Send, X } from 'lucide-react';
import { secretChatApi } from '../api';

const POLL_MS = 800;
const TICK_MS = 80;
// Fast enough to finish well inside the shortest review window, slow enough to read as typing.
const REVEAL_MS_PER_CHAR = 18;
const LEAVE_MS = 420;

/**
 * The card that shows what autopilot is about to say, while it is still stoppable.
 *
 * The server drafts the reply, marks the host as typing, then holds it for a few seconds
 * before posting it (`_run_autopilot`). That hold used to be dead time — a synthetic delay
 * so the reply did not arrive suspiciously fast. It now doubles as the host's review window:
 * this polls for the held draft, reveals it a character at a time with the countdown running,
 * and offers the two decisions that end the wait early — **Stop** (nothing is sent) and
 * **Send now**.
 *
 * Host-only by construction: the draft never goes out over the room's stream, it is fetched
 * with the host key, so the guest being answered sees nothing but a typing indicator.
 */
export default function AutopilotDraft({ token, hostKey, active, toast }) {
  const [draft, setDraft] = useState(null);
  const [remaining, setRemaining] = useState(0);
  const [revealed, setRevealed] = useState(0);
  const [leaving, setLeaving] = useState('');
  // Ids the host has already decided on. The next poll can still return the draft for a
  // moment, and re-showing a card the host just dismissed would be worse than a late clear.
  const decidedRef = useRef(new Set());
  const deadlineRef = useRef(0);
  const draftIdRef = useRef('');

  // ─── poll for a held draft ───
  useEffect(() => {
    if (!active) {
      draftIdRef.current = '';
      setDraft(null);
      return undefined;
    }
    let cancelled = false;
    const load = () => {
      if (document.visibilityState === 'hidden') return;
      secretChatApi.autopilotDraft(token, hostKey)
        .then(data => {
          if (cancelled) return;
          const pending = data?.pending || null;
          if (!pending) {
            // The draft was sent, superseded or stopped elsewhere. A card the host has
            // already decided on is left alone until its leaving animation finishes.
            if (draftIdRef.current && !decidedRef.current.has(draftIdRef.current)) {
              draftIdRef.current = '';
              setDraft(null);
            }
            return;
          }
          if (decidedRef.current.has(pending.id) || draftIdRef.current === pending.id) return;
          draftIdRef.current = pending.id;
          deadlineRef.current = Date.now() + pending.remaining_seconds * 1000;
          setRemaining(pending.remaining_seconds);
          setRevealed(0);
          setLeaving('');
          setDraft(pending);
        })
        .catch(() => {
          // A room that ended or a dropped request: the next tick reconciles.
        });
    };
    load();
    const timer = setInterval(load, POLL_MS);
    return () => { cancelled = true; clearInterval(timer); };
  }, [token, hostKey, active]);

  // ─── countdown ───
  useEffect(() => {
    if (!draft || leaving) return undefined;
    const timer = setInterval(() => {
      setRemaining(Math.max(0, (deadlineRef.current - Date.now()) / 1000));
    }, TICK_MS);
    return () => clearInterval(timer);
  }, [draft, leaving]);

  // ─── typewriter reveal ───
  useEffect(() => {
    if (!draft) return undefined;
    const total = draft.content.length;
    if (revealed >= total) return undefined;
    const timer = setTimeout(() => setRevealed(count => Math.min(total, count + 1)), REVEAL_MS_PER_CHAR);
    return () => clearTimeout(timer);
  }, [draft, revealed]);

  const decide = useCallback(async action => {
    if (!draft || leaving) return;
    decidedRef.current.add(draft.id);
    setLeaving(action === 'cancel' ? 'stopped' : 'sent');
    try {
      await secretChatApi.autopilotDecide(token, { host_key: hostKey, draft_id: draft.id, action });
      if (action === 'cancel') toast?.('Autopilot reply stopped — nothing was sent');
    } catch (error) {
      toast?.(error.message || 'Could not reach autopilot in time', 'error');
    }
    setTimeout(() => {
      draftIdRef.current = '';
      setDraft(null);
      setLeaving('');
    }, LEAVE_MS);
  }, [draft, leaving, token, hostKey, toast]);

  // Stopping is the urgent action, so give it a keyboard route: Escape while a draft is up.
  useEffect(() => {
    if (!draft || leaving) return undefined;
    const onKey = event => { if (event.key === 'Escape') decide('cancel'); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [draft, leaving, decide]);

  if (!draft) return null;

  const hold = draft.hold_seconds || 1;
  const progress = leaving ? 0 : Math.max(0, Math.min(100, (remaining / hold) * 100));
  const seconds = Math.ceil(remaining);
  const typing = revealed < draft.content.length;
  const status = leaving === 'stopped' ? 'Stopped' : leaving === 'sent' || seconds <= 0 ? 'Sending…' : `Sending in ${seconds}s`;

  return (
    <div className={`autopilot-draft${leaving ? ` ${leaving}` : ''}`} role="status" aria-live="polite">
      <div className="autopilot-draft-head">
        <span className="autopilot-draft-badge">
          <span className="autopilot-draft-orb" aria-hidden="true"><Bot size={12} /></span>
          Autopilot is about to reply
        </span>
        <span className="autopilot-draft-countdown">{status}</span>
      </div>

      <p className={`autopilot-draft-text${typing && !leaving ? ' typing' : ''}`}>
        {draft.content.slice(0, leaving ? draft.content.length : revealed)}
      </p>

      <div className="autopilot-draft-progress" aria-hidden="true">
        <i style={{ width: `${progress}%` }} />
      </div>

      <div className="autopilot-draft-actions">
        <button type="button" className="autopilot-draft-stop" onClick={() => decide('cancel')} disabled={Boolean(leaving)}>
          <X size={13} /> Stop
        </button>
        <button type="button" className="autopilot-draft-send" onClick={() => decide('send')} disabled={Boolean(leaving)}>
          <Send size={12} /> Send now
        </button>
      </div>
    </div>
  );
}
