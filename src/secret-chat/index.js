export { secretChatApi } from './api';
export { default as SecretChatPage } from './components/SecretChatPage';
export { default as SecretChatStandalone } from './components/SecretChatStandalone';
import './styles.css';

import React, { useEffect, useState } from 'react';
import { readSessionFlag, writeSessionFlag } from '../brand';

const SECRET_CHAT_PATH_RE = /^\/secret-chat\/([a-f0-9]+)/;

export function useSecretChatRoute() {
  const [token, setToken] = useState(null);
  const [isSharedLink, setIsSharedLink] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const match = window.location.pathname.match(SECRET_CHAT_PATH_RE);
    if (match) {
      setToken(match[1]);
      const fromApp = readSessionFlag('session');
      setIsSharedLink(!fromApp);
    }
    setReady(true);
  }, []);

  const open = async (createFn) => {
    writeSessionFlag('session', '1');
    const session = await createFn();
    setToken(session.token);
    setIsSharedLink(false);
    window.history.replaceState({}, '', `/secret-chat/${session.token}`);
    return session.token;
  };

  const close = () => {
    setToken(null);
    setIsSharedLink(false);
    window.history.replaceState({}, '', '/');
  };

  return { token, isSharedLink, ready, open, close };
}
