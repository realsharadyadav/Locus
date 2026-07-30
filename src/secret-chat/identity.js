import { readStorage, writeStorage } from '../brand';

// The client id has always lived under this exact key, so links opened before the roster
// existed keep their identity (and therefore their message history colours).
const CLIENT_ID_KEY = 'secret-chat-client-id';

const randomKey = () => {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID().replace(/-/g, '');
  return `${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
};

/** Stable per-browser id for a chat participant. */
export function clientId() {
  let id = window.localStorage.getItem(CLIENT_ID_KEY);
  if (!id) {
    id = randomKey().slice(0, 12);
    window.localStorage.setItem(CLIENT_ID_KEY, id);
  }
  return id;
}

/**
 * The host key proves room ownership to the backend. It is only ever created inside the
 * app — `peekHostKey` lets guest code check for one without minting it.
 */
export function hostKey() {
  let key = readStorage('secret-chat-host-key');
  if (!key) {
    key = randomKey();
    writeStorage('secret-chat-host-key', key);
  }
  return key;
}

export function peekHostKey() {
  return readStorage('secret-chat-host-key') || '';
}

/** Device and locale facts the host sees about who is in the room. */
export function clientProfile() {
  let timezone = '';
  try {
    timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
  } catch {
    timezone = '';
  }
  return {
    language: navigator.language || '',
    timezone,
    screen: window.screen ? `${window.screen.width}x${window.screen.height}` : '',
    viewport: `${window.innerWidth}x${window.innerHeight}`,
  };
}
