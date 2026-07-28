export const parseServerTime = (value) => {
  if (!value) return Date.now();
  if (value instanceof Date) return value.getTime();
  const text = String(value);
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(text);
  const parsed = new Date(hasTimezone ? text : `${text}Z`).getTime();
  return Number.isFinite(parsed) ? parsed : Date.now();
};

export const displayTime = (value) => {
  const timestamp = parseServerTime(value);
  const date = new Date(timestamp);
  const seconds = Math.max(0, (Date.now() - timestamp) / 1000);
  if (seconds < 60) return 'Just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} hr ago`;
  if (seconds < 172800) return 'Yesterday';
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
};

export const STORE_COLORS = ['violet', 'peach', 'green'];

export const buildSuggestions = (files, stores) => {
  if (!files.length) {
    return [
      'What can Locus help me with?',
      'How do I organize my knowledge?',
      'What types of files can I upload?',
    ];
  }
  const names = files.slice(0, 3).map(file => file.name.replace(/\.[^.]+$/, ''));
  const suggestions = [
    `Summarize ${names[0]}`,
    names[1] ? `What are the key themes in ${names[1]}?` : 'What themes appear in my knowledge?',
    `What do my ${files.length} files have in common?`,
  ];
  if (stores.length) suggestions.push(`What do I know about ${stores[0].title.toLowerCase()}?`);
  return [...new Set(suggestions)].slice(0, 4);
};
