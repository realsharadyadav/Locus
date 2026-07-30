import React, { useEffect, useRef, useState } from 'react';
import { Bot, Loader2, PenLine, Settings2, Sparkles, WandSparkles, X } from 'lucide-react';
import { secretChatApi } from '../api';

export const TONES = [
  { value: 'friendly', label: 'Friendly' },
  { value: 'playful', label: 'Playful' },
  { value: 'flirty', label: 'Flirty' },
  { value: 'funny', label: 'Funny' },
  { value: 'formal', label: 'Formal' },
  { value: 'blunt', label: 'Blunt' },
  { value: 'supportive', label: 'Supportive' },
  { value: 'short', label: 'Very short' },
];

/**
 * The host's reply copilot. Two modes:
 *
 * * **Suggest** — drafts three replies; the host picks one, edits it in the composer and
 *   sends it themselves. Nothing reaches the room without a click.
 * * **Autopilot** — the same draft is sent automatically when somebody else writes, so the
 *   AI can hold the conversation. It only ever fires for messages that arrived after it
 *   was switched on, and it stops the moment the toggle goes off.
 *
 * "Talk like me" feeds the host's own previous messages in this room to the model as style
 * samples, so the drafts read like them rather than like an assistant.
 */
export default function AiCopilot({
  token,
  hostKey,
  clientId,
  sender,
  session,
  messages,
  onInsert,
  onSend,
  onOptionsChange,
  toast,
  composerText = '',
}) {
  const [busy, setBusy] = useState(false);
  const [suggestions, setSuggestions] = useState([]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [styleSamples, setStyleSamples] = useState(0);
  const [personaDraft, setPersonaDraft] = useState(session?.ai_persona || '');
  const autopilotHandledRef = useRef(0);

  const tone = session?.ai_tone || 'friendly';
  const persona = session?.ai_persona || '';
  const autopilot = Boolean(session?.ai_autopilot);
  const mimicMe = session?.ai_mimic_me !== false;

  useEffect(() => { setPersonaDraft(session?.ai_persona || ''); }, [session?.ai_persona]);

  const saveOptions = async patch => {
    try {
      const updated = await secretChatApi.updateOptions(token, { host_key: hostKey, ...patch });
      onOptionsChange?.(updated);
      return updated;
    } catch (error) {
      toast?.(error.message || 'Could not save the copilot settings', 'error');
      return null;
    }
  };

  const draft = async ({ instruction = '', mode = 'suggest' } = {}) => {
    setBusy(true);
    try {
      const result = await secretChatApi.assist(token, {
        host_key: hostKey,
        client_id: clientId,
        sender,
        mode,
        tone,
        persona,
        mimic_me: mimicMe,
        instruction,
      });
      setStyleSamples(result.style_samples || 0);
      return result.suggestions || [];
    } catch (error) {
      toast?.(error.message || 'The AI could not draft a reply', 'error');
      return [];
    } finally {
      setBusy(false);
    }
  };

  const suggest = async () => {
    const replies = await draft({ instruction: composerText.trim() });
    setSuggestions(replies);
  };

  // ─── autopilot ───
  const lastMessage = messages[messages.length - 1];
  const lastFromOther = lastMessage && (lastMessage.sender || '').split('|||')[1] !== clientId;

  useEffect(() => {
    // Everything already in the room when autopilot came on is treated as handled, so
    // switching it on never triggers a reply to an old message.
    if (!autopilot) {
      autopilotHandledRef.current = 0;
      return;
    }
    if (!autopilotHandledRef.current) {
      autopilotHandledRef.current = lastMessage?.id || 0;
    }
  }, [autopilot, lastMessage?.id]);

  useEffect(() => {
    if (!autopilot || !lastFromOther || busy) return;
    if (!lastMessage || lastMessage.id <= autopilotHandledRef.current) return;
    autopilotHandledRef.current = lastMessage.id;
    let cancelled = false;
    (async () => {
      const replies = await draft({ mode: 'autopilot' });
      if (cancelled || !replies.length) return;
      try {
        await onSend(replies[0], { viaAi: true });
      } catch (error) {
        toast?.(error.message || 'Autopilot could not send the reply', 'error');
      }
    })();
    return () => { cancelled = true; };
    // Deliberately keyed on the newest message only: adding draft/onSend here would
    // re-fire the effect mid-draft and answer the same message twice.
  }, [autopilot, lastFromOther, lastMessage?.id]);

  return (
    <div className={`ai-copilot${autopilot ? ' autopilot' : ''}`}>
      <div className="ai-copilot-bar">
        <button type="button" className="ai-action" onClick={suggest} disabled={busy}>
          {busy ? <Loader2 size={13} className="spin" /> : <WandSparkles size={13} />}
          {busy ? 'Thinking…' : composerText.trim() ? 'Rewrite my draft' : 'Suggest a reply'}
        </button>

        <label className={`ai-autopilot-toggle${autopilot ? ' on' : ''}`}>
          <input
            type="checkbox"
            checked={autopilot}
            onChange={event => saveOptions({ ai_autopilot: event.target.checked })}
          />
          <Bot size={13} />
          <span>Autopilot</span>
        </label>

        <select
          className="ai-tone-select"
          value={tone}
          onChange={event => saveOptions({ ai_tone: event.target.value })}
          aria-label="Reply tone"
        >
          {TONES.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>

        <button
          type="button"
          className={`ai-action subtle${settingsOpen ? ' active' : ''}`}
          onClick={() => setSettingsOpen(value => !value)}
          aria-expanded={settingsOpen}
        >
          <Settings2 size={13} /> Voice
        </button>

        {autopilot && <span className="ai-autopilot-note">AI is answering for you</span>}
      </div>

      {settingsOpen && (
        <div className="ai-copilot-settings">
          <label className="ai-mimic">
            <input
              type="checkbox"
              checked={mimicMe}
              onChange={event => saveOptions({ ai_mimic_me: event.target.checked })}
            />
            <span>
              <strong>Talk like me</strong>
              <small>
                Uses your own past messages in this chat as style samples
                {styleSamples > 0 ? ` (${styleSamples} used last time)` : ''}.
              </small>
            </span>
          </label>
          <label className="ai-persona">
            <span>How you sound</span>
            <textarea
              value={personaDraft}
              onChange={event => setPersonaDraft(event.target.value)}
              onBlur={() => personaDraft !== persona && saveOptions({ ai_persona: personaDraft })}
              placeholder="e.g. lowercase, Hinglish, dry humour, never more than two lines, calls people 'boss'"
              maxLength={2000}
              rows={3}
            />
          </label>
        </div>
      )}

      {suggestions.length > 0 && (
        <div className="ai-suggestions">
          <div className="ai-suggestions-head">
            <span><Sparkles size={12} /> Pick one to edit and send</span>
            <button type="button" onClick={() => setSuggestions([])} aria-label="Dismiss suggestions">
              <X size={13} />
            </button>
          </div>
          {suggestions.map((suggestion, index) => (
            <div className="ai-suggestion" key={`${index}-${suggestion.slice(0, 24)}`}>
              <button type="button" className="ai-suggestion-use" onClick={() => { onInsert(suggestion); setSuggestions([]); }}>
                <PenLine size={12} /> {suggestion}
              </button>
              <button
                type="button"
                className="ai-suggestion-send"
                onClick={async () => {
                  setSuggestions([]);
                  try {
                    await onSend(suggestion, { viaAi: true });
                  } catch (error) {
                    toast?.(error.message || 'Could not send that reply', 'error');
                  }
                }}
                title="Send as is"
              >
                Send
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
