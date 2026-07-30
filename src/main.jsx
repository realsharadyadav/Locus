import React from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';
import { App } from './App';
import { SecretChatStandalone, resolveSecretChatEntry } from './secret-chat';

// Resolved before mount: a shared-link guest gets the standalone chat only, never the app
// shell, so no app data is requested from their browser.
const secretChatEntry = resolveSecretChatEntry();

createRoot(document.getElementById('root')).render(
  secretChatEntry.mode === 'guest'
    ? <SecretChatStandalone token={secretChatEntry.token} />
    : <App initialSecretChatToken={secretChatEntry.token} />,
);
