import React, { useEffect, useRef, useState } from 'react';
import { api } from './api';
import { clearAuthToken, getAuthToken, onUnauthorized } from './auth';
import { readStorage, writeStorage } from './brand';
import { CommandPalette } from './components/CommandPalette';
import { ConfirmModal } from './components/ConfirmModal';
import { CreateStoreModal } from './components/CreateStoreModal';
import { Header } from './components/Header';
import { LoginPage } from './components/LoginPage';
import { Sidebar } from './components/Sidebar';
import { SplashScreen } from './components/SplashScreen';
import { ToastStack } from './components/Toast';
import { AI_PREFERENCE_STORAGE_KEY, APP_DATA_CACHE_KEY, APP_PAGES, normalizePageId, readCachedAppData } from './lib/appState';
import { ExplorePage } from './pages/ExplorePage';
import { HubPage } from './pages/HubPage';
import { SettingsPage } from './pages/SettingsPage';
import { clearSecretChatHost, PrivateChatsPage, useSecretChatRoute, useSecretChatUnread } from './secret-chat';
import { secretImagesApi, SecretImagesPage } from './secret-images';

export function App({ initialSecretChatToken = null }) {
  // 'checking' until the backend says whether a password is configured, then
  // 'required' (show the gate) or 'ready' (workspace may load its data).
  const [authState, setAuthState] = useState('checking');
  // Whether this deployment has a password at all — Settings only offers a sign
  // out when there is a session to end.
  const [authRequired, setAuthRequired] = useState(false);
  const [page, setPage] = useState('ask');
  const [query, setQuery] = useState('');
  const [mobileOpen, setMobileOpen] = useState(false);
  const [sidebarCompact, setSidebarCompact] = useState(false);
  const [historyCollapsed, setHistoryCollapsed] = useState(false);
  const [filePanelCollapsed, setFilePanelCollapsed] = useState(false);
  const [preferencesLoaded, setPreferencesLoaded] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const { token: secretChatToken, select: selectSecretChat, open: openSecretChatRoute } = useSecretChatRoute(initialSecretChatToken);
  const [files, setFiles] = useState([]);
  const [collections, setCollections] = useState([]);
  const [chats, setChats] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [booted, setBooted] = useState(false);
  const [bootProgress, setBootProgress] = useState(0);
  const [apiError, setApiError] = useState('');
  const [toasts, setToasts] = useState([]);
  const [confirm, setConfirm] = useState(null);
  const [hubFocusStoreId, setHubFocusStoreId] = useState(null);
  const [exploreChatId, setExploreChatId] = useState(null);
  const [newChatSignal, setNewChatSignal] = useState(0);
  const [theme, setTheme] = useState(() => readStorage('theme') || 'dark');
  const [secretImagesConfigured, setSecretImagesConfigured] = useState(false);
  // Bumped when a chat action changes the default model, so Ask re-reads the preference it
  // displays in its header instead of showing a stale model for the rest of the session.
  const [settingsVersion, setSettingsVersion] = useState(0);
  // Job ids whose platform-action side effects have already been applied. Jobs that are
  // already completed when the app boots are pre-marked in loadData — their actions were
  // applied by the preferences boot just read, so they must not toast again.
  const appliedActionJobs = useRef(new Set());

  const toast = (message, type = 'success') => {
    const id = crypto.randomUUID();
    setToasts(current => [...current, { id, message, type }]);
  };

  const dismissToast = id => setToasts(current => current.filter(item => item.id !== id));

  const refreshChats = async () => {
    const nextChats = await api.chats();
    setChats(nextChats);
  };

  const refreshJobs = async () => {
    const nextJobs = await api.chatJobs();
    setJobs(nextJobs);
    return nextJobs;
  };

  const loadData = async () => {
    setLoading(true);
    try {
      // Track the boot requests individually so the splash bar reflects real
      // progress rather than an animated guess.
      const bootRequests = [api.files(), api.collections(), api.chats(), api.chatJobs(), api.preference('layout'), api.preference('theme')];
      let settled = 0;
      const countSettled = () => setBootProgress(Math.round((++settled / bootRequests.length) * 100));
      bootRequests.forEach(request => request.then(countSettled, countSettled));

      const [nextFiles, nextCollections, nextChats, nextJobs, layoutPreference, themePreference] = await Promise.all(bootRequests);
      const savedLayout = layoutPreference.value || {};
      setFiles(nextFiles);
      setCollections(nextCollections);
      setChats(nextChats);
      setJobs(nextJobs);
      // A theme saved server-side (by a chat "switch to dark mode", or this tab) wins over the
      // local cache; localStorage stays as the offline fast path. Existing completed action jobs
      // have already taken effect through this preference, so they must not toast on boot.
      const savedTheme = themePreference?.value?.theme;
      if (savedTheme === 'light' || savedTheme === 'dark') {
        setTheme(savedTheme);
        writeStorage('theme', savedTheme);
      }
      nextJobs.forEach(job => { if (job.status === 'completed') appliedActionJobs.current.add(job.id); });
      window.localStorage.setItem(APP_DATA_CACHE_KEY, JSON.stringify({
        files: nextFiles,
        collections: nextCollections,
        chats: nextChats,
        jobs: nextJobs,
      }));
      setSidebarCompact(Boolean(savedLayout.sidebar_compact));
      setHistoryCollapsed(Boolean(savedLayout.history_collapsed));
      setFilePanelCollapsed(Boolean(savedLayout.file_panel_collapsed));
      const savedPage = normalizePageId(savedLayout.page);
      if (APP_PAGES.includes(savedPage)) setPage(savedPage);
      setPreferencesLoaded(true);
      setApiError('');
    } catch {
      const cached = readCachedAppData();
      if (cached.files || cached.collections || cached.chats || cached.jobs) {
        setFiles(cached.files || []);
        setCollections(cached.collections || []);
        setChats(cached.chats || []);
        setJobs(cached.jobs || []);
        (cached.jobs || []).forEach(job => { if (job.status === 'completed') appliedActionJobs.current.add(job.id); });
      }
      setApiError('Backend is offline. Start it with npm run dev:api');
    } finally {
      setLoading(false);
      setBootProgress(100);
      setBooted(true);
    }
  };

  useEffect(() => {
    // Any 401 from anywhere in the app lands here — the token is already gone
    // by this point, so all that is left is to show the gate again.
    onUnauthorized(() => setAuthState('required'));
    return () => onUnauthorized(null);
  }, []);

  useEffect(() => {
    const resolveAuth = async () => {
      try {
        const { auth_required: required } = await api.authStatus();
        setAuthRequired(required);
        if (!required) return setAuthState('ready');
        if (!getAuthToken()) return setAuthState('required');
        try {
          await api.authMe();
          setAuthState('ready');
        } catch {
          clearAuthToken();
          setAuthState('required');
        }
      } catch {
        // Backend unreachable: fall through to the workspace so the existing
        // offline banner explains it, rather than a login screen nobody can
        // get past.
        setAuthState('ready');
      }
    };
    resolveAuth();
  }, []);

  useEffect(() => {
    if (authState === 'ready') loadData();
  }, [authState]);

  useEffect(() => {
    if (authState !== 'ready') return;
    secretImagesApi.status()
      .then(status => setSecretImagesConfigured(status.configured))
      .catch(() => setSecretImagesConfigured(false));
  }, [authState]);

  useEffect(() => {
    if (!preferencesLoaded) return undefined;
    const timer = window.setTimeout(() => {
      api.updatePreference('layout', {
        page,
        sidebar_compact: sidebarCompact,
        history_collapsed: historyCollapsed,
        file_panel_collapsed: filePanelCollapsed,
      }).catch(() => {
        // Layout saving is best-effort; the offline banner covers backend health.
      });
    }, 250);
    return () => window.clearTimeout(timer);
  }, [preferencesLoaded, page, sidebarCompact, historyCollapsed, filePanelCollapsed]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    writeStorage('theme', theme);
    const themeColor = theme === 'dark' ? '#0d1217' : '#f5f3ee';
    let meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) {
      meta = document.createElement('meta');
      meta.name = 'theme-color';
      document.head.appendChild(meta);
    }
    meta.setAttribute('content', themeColor);
    // The server copy is what a chat "switch to dark mode" writes and what a second device
    // reads; keep it in sync. Skipped until boot has loaded the saved value so the initial
    // effect run (which may set the server's own theme) does not write it straight back.
    if (preferencesLoaded) {
      api.updatePreference('theme', { theme }).catch(() => {});
    }
  }, [theme, preferencesLoaded]);

  useEffect(() => {
    // Polling before sign-in would just 401 twice a second.
    if (authState !== 'ready') return undefined;
    const poll = async () => {
      try {
        const nextJobs = await refreshJobs();
        if (nextJobs.some(job => ['queued', 'running'].includes(job.status))) await refreshChats();
        nextJobs.forEach(job => {
          if (job.status === 'completed' && !appliedActionJobs.current.has(job.id) && (job.result?.actions_taken || []).length) {
            appliedActionJobs.current.add(job.id);
            applyJobActions(job);
          }
        });
      } catch {
        // The main offline banner handles connectivity; polling resumes automatically.
      }
    };
    const timer = window.setInterval(poll, 1500);
    return () => window.clearInterval(timer);
  }, [authState]);

  useEffect(() => {
    const onKeyDown = (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setCommandOpen(true);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  useEffect(() => {
    if (secretChatToken) setPage('secret-chat');
  }, [secretChatToken]);

  useEffect(() => {
    if (secretChatToken) return;
    if (!preferencesLoaded) return;
    const path = window.location.pathname;
    const pageFromUrl = normalizePageId(path === '/' ? 'ask' : path.replace(/^\//, ''));
    if (APP_PAGES.includes(pageFromUrl)) {
      setPage(pageFromUrl);
      const canonicalPath = pageFromUrl === 'ask' ? '/' : `/${pageFromUrl}`;
      if (path !== canonicalPath) window.history.replaceState({}, '', canonicalPath);
    }
    const onPopState = () => {
      const p = window.location.pathname;
      const next = normalizePageId(p === '/' ? 'ask' : p.replace(/^\//, ''));
      if (APP_PAGES.includes(next)) setPage(next);
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, [secretChatToken, preferencesLoaded]);

  const navigate = (nextPage, options = {}) => {
    const resolvedPage = normalizePageId(nextPage);
    setPage(resolvedPage);
    if (options.storeId) setHubFocusStoreId(options.storeId);
    if (options.create) setCreateOpen(true);
    const path = resolvedPage === 'ask' ? '/' : `/${resolvedPage}`;
    window.history.pushState({}, '', path);
  };

  const handleCommandSelect = (item) => {
    if (item.type === 'page') navigate(item.id);
    if (item.type === 'store') navigate('library', { storeId: item.id });
    if (item.type === 'file') navigate('library', { storeId: item.storeId });
    if (item.type === 'chat') {
      navigate('ask');
      setExploreChatId(item.id);
    }
  };

  const create = async payload => {
    await api.createCollection(payload);
    await loadData();
    toast('Library created');
  };

  const uploadFile = async (storeId, file) => {
    const uploaded = await api.uploadFile(storeId, file);
    await loadData();
    return uploaded;
  };

  const deleteFile = async id => {
    await api.deleteFile(id);
    await loadData();
    toast('File deleted');
  };

  const deleteStore = async id => {
    await api.deleteCollection(id);
    await loadData();
    toast('Library deleted');
  };

  const deleteChat = async id => {
    await api.deleteChat(id);
    await loadData();
    toast('Chat deleted');
  };

  const deleteAllChats = async () => {
    await api.deleteAllChats();
    setChats([]);
    setJobs([]);
    setExploreChatId(null);
    toast('All chats deleted');
  };

  const createChatJob = async (...args) => {
    const job = await api.createChatJob(...args);
    setJobs(current => [job, ...current.filter(item => item.id !== job.id)]);
    await refreshChats();
    return job;
  };

  const markJobSeen = async id => {
    setJobs(current => current.map(job => job.id === id ? { ...job, seen: true } : job));
    try {
      await api.markChatJobSeen(id);
    } catch {
      setJobs(current => current.map(job => job.id === id ? { ...job, seen: false } : job));
    }
  };

  // A completed job that executed platform actions (Ask's "switch to dark mode", "make gpt-4o
  // the default model", ...) applies those side effects here. The server already persisted
  // them; this is the live half — flip the theme, refresh Ask's model display, toast what
  // happened. Run once per job id (see appliedActionJobs).
  const applyJobActions = job => {
    (job.result?.actions_taken || []).forEach(action => {
      const result = action.result || {};
      if (action.tool === 'set_theme' && (result.theme === 'light' || result.theme === 'dark')) {
        setTheme(result.theme);
        toast(`Theme set to ${result.theme === 'dark' ? 'Dark' : 'Light'}`);
      } else if (action.tool === 'set_default_model' && result.provider && result.model) {
        try {
          const saved = JSON.parse(window.localStorage.getItem(AI_PREFERENCE_STORAGE_KEY) || '{}');
          window.localStorage.setItem(AI_PREFERENCE_STORAGE_KEY, JSON.stringify({ ...saved, provider: result.provider, model: result.model }));
        } catch { /* localStorage is best-effort; the server copy is authoritative */ }
        setSettingsVersion(value => value + 1);
        toast(`Default model set to ${result.model}`);
      } else if (action.tool === 'run_model_health_test') {
        toast((action.summary || 'Model health test finished').replace(/\*\*/g, ''));
      }
    });
  };

  const secretChatUnread = useSecretChatUnread();
  const readyCount = jobs.filter(job => job.status === 'completed' && !job.seen).length;
  const hasActiveJobs = jobs.some(job => ['queued', 'running'].includes(job.status));

  // Opens the Private list, not a room — rooms are created from the page now, so
  // clicking the nav item no longer leaves an empty chat behind every time.
  const openSecretChat = () => {
    openSecretChatRoute();
    setPage('secret-chat');
    setMobileOpen(false);
  };

  const requestDeleteChat = (chat, onDeleted) => setConfirm({
    title: 'Delete chat?',
    message: `"${chat.title}" will be permanently removed.`,
    onConfirm: async () => {
      await deleteChat(chat.id);
      if (exploreChatId === chat.id) setExploreChatId(null);
      onDeleted?.();
    },
  });

  const requestDeleteAllChats = onDeleted => setConfirm({
    title: 'Delete all chats?',
    message: `All ${chats.length} conversations and their answers will be permanently removed.`,
    confirmLabel: 'Delete all',
    onConfirm: async () => {
      await deleteAllChats();
      onDeleted?.();
    },
  });

  if (authState === 'checking') return <SplashScreen progress={8} status="Checking session" />;
  // Signing in flips authState to 'ready', which is what kicks off loadData —
  // the splash below then covers that first load as it would on an open app.
  if (authState === 'required') return <LoginPage onSignedIn={() => setAuthState('ready')} />;
  if (!booted) return <SplashScreen progress={bootProgress} />;

  return (
    <div className={`app-shell ${sidebarCompact ? 'sidebar-compact' : ''} ${page === 'ask' ? 'explore-active' : ''} ${page === 'secret-chat' ? 'secretchat-active' : ''}`}>
      <Sidebar
        page={page}
        setPage={(id) => navigate(id)}
        mobileOpen={mobileOpen}
        close={() => setMobileOpen(false)}
        fileCount={files.length}
        readyCount={readyCount}
        secretUnread={secretChatUnread}
        compact={sidebarCompact}
        toggleCompact={() => setSidebarCompact(value => !value)}
        files={files}
        historyCollapsed={historyCollapsed}
        setHistoryCollapsed={setHistoryCollapsed}
        onOpenFile={file => navigate('library', { storeId: file.store_id })}
        onOpenSecretChat={openSecretChat}
        onNewChat={() => {
          setExploreChatId(null);
          setNewChatSignal(value => value + 1);
          navigate('ask');
        }}
        theme={theme}
        setTheme={setTheme}
        secretImagesConfigured={secretImagesConfigured}
      />
      <main>
        {!['ask', 'secret-chat', 'secret-images'].includes(page) && (
          <Header
            query={query}
            openMenu={() => setMobileOpen(true)}
            openCommand={() => setCommandOpen(true)}
          />
        )}
        {apiError && (
          <button className="api-banner" onClick={loadData}>{apiError} · Retry</button>
        )}
        {page === 'library' && (
          <HubPage
            query={query}
            files={files}
            stores={collections}
            focusStoreId={hubFocusStoreId}
            clearFocusStore={() => setHubFocusStoreId(null)}
            openCreate={() => setCreateOpen(true)}
            uploadFile={uploadFile}
            requestDeleteFile={file => setConfirm({
              title: 'Delete file?',
              message: `“${file.name}” will be removed from this library.`,
              onConfirm: () => deleteFile(file.id),
            })}
            requestDeleteStore={store => setConfirm({
              title: 'Delete library?',
              message: `“${store.title}” and all its files will be permanently removed.`,
              onConfirm: () => deleteStore(store.id),
            })}
            toast={toast}
          />
        )}
        {page === 'ask' && (
          <ExplorePage
            files={files}
            stores={collections}
            chats={chats}
            jobs={jobs}
            createChatJob={createChatJob}
            refreshChats={refreshChats}
            markJobSeen={markJobSeen}
            initialChatId={exploreChatId}
            clearInitialChat={() => setExploreChatId(null)}
            newChatSignal={newChatSignal}
            onOpenStore={storeId => navigate('library', { storeId })}
            toast={toast}
            requestDeleteChat={requestDeleteChat}
            requestDeleteAllChats={requestDeleteAllChats}
            hasActiveJobs={hasActiveJobs}
            refreshJobs={refreshJobs}
            openMenu={() => setMobileOpen(true)}
            historyCollapsed={historyCollapsed}
            setHistoryCollapsed={setHistoryCollapsed}
            settingsVersion={settingsVersion}
          />
        )}
        {page === 'secret-chat' && (
          <PrivateChatsPage
            token={secretChatToken}
            onSelect={selectSecretChat}
            requestConfirm={setConfirm}
            toast={toast}
            openMenu={() => setMobileOpen(true)}
          />
        )}
        {page === 'secret-images' && (
          <SecretImagesPage
            toast={toast}
            requestConfirm={setConfirm}
            openMenu={() => setMobileOpen(true)}
          />
        )}
        {page === 'settings' && (
          <SettingsPage
            toast={toast}
            authRequired={authRequired}
            onSignOut={() => {
              clearAuthToken();
              clearSecretChatHost();
              setAuthState('required');
            }}
          />
        )}
      </main>

      <CreateStoreModal open={createOpen} close={() => setCreateOpen(false)} onCreate={create} />
      <ConfirmModal config={confirm} close={() => setConfirm(null)} />
      <CommandPalette
        open={commandOpen}
        close={() => { setCommandOpen(false); setQuery(''); }}
        query={query}
        setQuery={setQuery}
        stores={collections}
        files={files}
        chats={chats}
        onSelect={handleCommandSelect}
      />
      <ToastStack toasts={toasts} dismiss={dismissToast} />
    </div>
  );
}
