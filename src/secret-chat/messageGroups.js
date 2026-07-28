import { parseServerTime } from '../utils';

// A run continues while the same sender keeps talking within this window.
const RUN_GAP_MS = 15 * 60 * 1000;

const startOfDay = ts => {
  const date = new Date(ts);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
};

export function dayLabel(ts) {
  const today = startOfDay(Date.now());
  const day = startOfDay(ts);
  if (day === today) return 'Today';
  if (day === today - 86400000) return 'Yesterday';
  const date = new Date(ts);
  const sameYear = date.getFullYear() === new Date().getFullYear();
  return date.toLocaleDateString([], {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    ...(sameYear ? {} : { year: 'numeric' }),
  });
}

export function timeLabel(ts) {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/**
 * Annotate messages with the day divider and run-start flags the chat views
 * need, so a sender who says three things in a row is labelled once rather
 * than three times.
 */
export function withMessageGrouping(messages = []) {
  let previous = null;
  return messages.map(msg => {
    const at = parseServerTime(msg.created_at);
    const newDay = !previous || startOfDay(previous.at) !== startOfDay(at);
    const startsRun = newDay
      || previous.msg.sender !== msg.sender
      || at - previous.at > RUN_GAP_MS;
    const entry = { msg, at, newDay, startsRun, day: newDay ? dayLabel(at) : null };
    previous = entry;
    return entry;
  });
}
