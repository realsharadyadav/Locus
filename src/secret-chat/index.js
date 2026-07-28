export { secretChatApi } from './api';
export { default as PrivateChatsPage } from './components/PrivateChatsPage';
export { default as SecretChatPage } from './components/SecretChatPage';
export { default as SecretChatStandalone } from './components/SecretChatStandalone';
export { default as ShareMenu } from './components/ShareMenu';
import './styles.css';

import { useEffect, useState } from 'react';
import { readSessionFlag, readStorage, writeSessionFlag, writeStorage } from '../brand';
import { guestChatPath as guestPath, matchChatPath } from './links';

export { chatShareUrl, guestChatPath } from './links';

// A browser that has opened the app itself (not just a shared link) is a host: it keeps
// full app access even after following one of its own share links.
const isHost = () => readStorage('secret-chat-host') === '1' || readSessionFlag('session') === '1';

export function markSecretChatHost() {
  writeStorage('secret-chat-host', '1');
  writeSessionFlag('session', '1');
}

/**
 * Decides, before anything mounts, whether this page load is a link guest or the app.
 *
 * Guests never mount the app shell: they get the standalone chat only, so no app data is
 * fetched in their browser and the surrounding product is never exposed to them. Trimming
 * the link back to the origin does not hand them the app either — a remembered guest is
 * sent back to their own chat.
 */
export function resolveSecretChatEntry() {
  const token = matchChatPath(window.location.pathname);
  const host = isHost();

  if (token && !host) {
    writeStorage('guest-chat', token);
    if (window.location.pathname !== guestPath(token)) {
      window.history.replaceState({}, '', guestPath(token));
    }
    return { mode: 'guest', token };
  }

  if (!host) {
    const guestToken = readStorage('guest-chat');
    if (guestToken) {
      window.history.replaceState({}, '', guestPath(guestToken));
      return { mode: 'guest', token: guestToken };
    }
  }

  return { mode: 'app', token };
}

export function useSecretChatRoute(initialToken = null) {
  const [token, setToken] = useState(initialToken);

  useEffect(() => {
    if (token) markSecretChatHost();
  }, [token]);

  /**
   * Point the route at one room, or at the room list when given null. The host
   * keeps the same /j/{token} URL a guest would use, so copying it out of the
   * address bar still produces a working invite.
   */
  const select = (nextToken) => {
    markSecretChatHost();
    setToken(nextToken);
    window.history.replaceState({}, '', nextToken ? guestPath(nextToken) : '/secret-chat');
  };

  const open = () => select(null);

  const close = () => {
    setToken(null);
    window.history.replaceState({}, '', '/');
  };

  return { token, select, open, close };
}
