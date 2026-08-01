import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  BrainCircuit,
  Check,
  Copy,
  Cpu,
  FileText,
  Folder,
  History,
  MoreHorizontal,
  Menu,
  PenLine,
  Plus,
  Radio,
  Send,
  RotateCcw,
  SlidersHorizontal,
  Sparkles,
  Square,
  Trash2,
  X,
  ChevronDown,
  Globe,
  FilePlus2,
} from 'lucide-react';
import { api } from '../api';
import { assistantLabel, readStorage } from '../brand';
import { AssistantMarkdown } from '../components/AssistantMarkdown';
import { CollapsibleSources } from '../components/CollapsibleSources';
import { DirectStreamTrace } from '../components/DirectStreamTrace';
import { ModelControl } from '../components/ModelControl';
import { PipelineActivity } from '../components/PipelineActivity';
import { useChatViewportLock, useCompactViewport, useRepinOnResize } from '../hooks/useChatViewport';
import { useClickOutside } from '../hooks/useClickOutside';
import {
  ACTIVE_CHAT_STORAGE_KEY,
  AI_PREFERENCE_STORAGE_KEY,
  DEFAULT_PROVIDER_MODELS,
  PROVIDER_LABELS,
  readSavedAiPreference,
} from '../lib/appState';
import { SLASH_COMMANDS, shouldAutoWebSearch } from '../lib/ask';
import { fileMetaLine, jobFailureMessage } from '../lib/format';
import { tip } from '../lib/ui';
import { parseServerTime } from '../utils';
import TextareaAutosize from 'react-textarea-autosize';
import { useStickToBottom } from 'use-stick-to-bottom';

export function ExplorePage({
  files, stores, chats, jobs, createChatJob, markJobSeen, initialChatId, clearInitialChat, onOpenStore, toast, requestDeleteChat,
  requestDeleteAllChats, hasActiveJobs, refreshChats, refreshJobs, openMenu, newChatSignal,
}) {
  const savedAiPreference = readSavedAiPreference();
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState([]);
  const [activeChat, setActiveChat] = useState(null);
  const [model, setModel] = useState(savedAiPreference.model || DEFAULT_PROVIDER_MODELS[savedAiPreference.provider] || DEFAULT_PROVIDER_MODELS.ollama);
  const [provider, setProvider] = useState(savedAiPreference.provider || 'ollama');
  const [llmConfig, setLlmConfig] = useState(null);
  const [allowGeneralKnowledge, setAllowGeneralKnowledge] = useState(true);
  const [reasoningMode, setReasoningMode] = useState(savedAiPreference.reasoning_mode === 'web_research' ? 'light' : (savedAiPreference.reasoning_mode || 'light'));
  const [webSourceLimit] = useState(savedAiPreference.web_source_limit || 200);
  const [selectedFileIds, setSelectedFileIds] = useState([]);
  const [selectFilesOpen, setSelectFilesOpen] = useState(false);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState(null);
  const [copiedConvId, setCopiedConvId] = useState(false);
  const [expandedSources, setExpandedSources] = useState({});
  const [slashOpen, setSlashOpen] = useState(false);
  const [slashIndex, setSlashIndex] = useState(-1);
  const [slashFilter, setSlashFilter] = useState('');
  const [directStreaming, setDirectStreaming] = useState(false);
  const [modePickerOpen, setModePickerOpen] = useState(false);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [railOpen, setRailOpen] = useState(false);
  const [followups, setFollowups] = useState({ key: null, items: [], loading: false });
  const composerRef = useRef(null);
  const mobileHeaderRef = useRef(null);

  useChatViewportLock();
  const compactViewport = useCompactViewport();
  const {
    scrollRef: threadRef,
    contentRef: threadContentRef,
    isAtBottom,
    scrollToBottom,
    stopScroll,
  } = useStickToBottom({ initial: 'instant', resize: 'smooth' });
  const loadedCompletedJob = useRef(null);
  const aiPreferenceReady = useRef(false);
  const revealTimerRef = useRef(null);
  const directAbortRef = useRef(null);
  const stopRequestedRef = useRef(false);
  const modePickerRef = useClickOutside(modePickerOpen, () => setModePickerOpen(false));
  const optionsPopoverRef = useClickOutside(optionsOpen, () => setOptionsOpen(false));
  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  const moreMenuRef = useClickOutside(moreMenuOpen, () => setMoreMenuOpen(false));
  const slashScopeRef = useClickOutside(slashOpen, () => { setSlashOpen(false); setSlashIndex(-1); });

  const toggleSources = (messageIndex) => {
    setExpandedSources(prev => ({ ...prev, [messageIndex]: !prev[messageIndex] }));
  };
  const selectedCount = selectedFileIds === null ? files.length : selectedFileIds.length;
  // Header identity: the conversation's own title, with the model and mode as the second line.
  // On a phone this replaces the row of labels and stat pills that used to wrap over the thread.
  const activeChatTitle = chats.find(item => item.id === activeChat)?.title || 'New chat';
  const modeLabel = SLASH_COMMANDS.find(command => command.id === reasoningMode)?.label.slice(1) || reasoningMode;
  const headerSubtitle = [model, modeLabel].filter(Boolean).join(' · ');
  const activeJob = jobs.find(job => job.conversation_id === activeChat && ['queued', 'running'].includes(job.status));
  const thinking = Boolean(activeJob) || directStreaming;
  const readyCount = jobs.filter(job => job.status === 'completed' && !job.seen).length;
  const runningCount = jobs.filter(job => ['queued', 'running'].includes(job.status)).length;
  const failedCount = jobs.filter(job => job.status === 'failed').length;
  const sessionTokens = messages.reduce((sum, message) => sum + (message.totalTokens || 0), 0);
  const sessionLlmHits = messages.reduce((sum, message) => sum + (message.llmHits || 0), 0);

  const formatChatTime = ts => {
    const d = new Date(ts.replace(' ', 'T') + 'Z');
    const now = new Date();
    const diffMs = now - d;
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'now';
    if (diffMins < 60) return `${diffMins}m`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h`;
    return `${Math.floor(diffHours / 24)}d`;
  };

  const getReasoningMode = (text) => {
    for (const cmd of SLASH_COMMANDS) {
      const prefix = cmd.label + ' ';
      const label = cmd.label;
      if (text.startsWith(prefix) || text === label) return cmd.id;
    }
    return reasoningMode;
  };

  const previewReasoningMode = getReasoningMode(question.trim());
  const autoWebSearchPreview = shouldAutoWebSearch(question.trim().replace(/^\/\w+\s*/, ''), previewReasoningMode);
  const activeModeLabel = previewReasoningMode === 'light' ? 'Light'
    : previewReasoningMode === 'unrestricted' ? 'Unrestricted'
    : previewReasoningMode === 'thinking' ? 'Thinking'
    : previewReasoningMode === 'deep_summary' ? 'Deep Summary'
    : previewReasoningMode === 'ticket_analysis' ? 'Ticket Analysis'
    : previewReasoningMode === 'web_research' ? 'Web Research'
    : previewReasoningMode;
  const displayedModeLabel = autoWebSearchPreview
    ? `${activeModeLabel} + Auto Web`
    : activeModeLabel;

  useEffect(() => {
    if (activeChat) {
      window.localStorage.setItem(ACTIVE_CHAT_STORAGE_KEY, String(activeChat));
    }
  }, [activeChat]);

  useEffect(() => {
    Promise.all([
      api.llmConfig(),
      api.preference('explore_ai').catch(() => ({ value: {} })),
    ]).then(([config, preference]) => {
      setLlmConfig(config);
      const saved = { ...readSavedAiPreference(), ...(preference.value || {}) };
      const nextProvider = saved.provider || config.provider || 'ollama';
      const nextModel = saved.model || (nextProvider === config.provider ? config.model : DEFAULT_PROVIDER_MODELS[nextProvider]);
      setProvider(nextProvider);
      setModel(nextModel);
      setReasoningMode(saved.reasoning_mode === 'web_research' ? 'light' : (saved.reasoning_mode || 'light'));
      aiPreferenceReady.current = true;
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!aiPreferenceReady.current) return undefined;
    const payload = {
      provider,
      model,
      reasoning_mode: reasoningMode,
      web_source_limit: webSourceLimit,
    };
    window.localStorage.setItem(AI_PREFERENCE_STORAGE_KEY, JSON.stringify(payload));
    const timer = window.setTimeout(() => {
      api.updatePreference('explore_ai', payload).catch(() => {});
    }, 300);
    return () => window.clearTimeout(timer);
  }, [provider, model, reasoningMode, webSourceLimit]);

  useEffect(() => {
    setSelectedFileIds(current => current === null ? null : current.filter(id => files.some(file => file.id === id)));
  }, [files]);

  const toggleFile = id => {
    setSelectedFileIds(current => {
      const selected = current === null ? files.map(file => file.id) : current;
      return selected.includes(id) ? selected.filter(fileId => fileId !== id) : [...selected, id];
    });
  };

  const messageFromSaved = message => {
    const rawSources = message.sources || [];
    const meta = rawSources.find(s => s.meta);
    return {
      id: message.id,
      role: message.role,
      text: message.content,
      sources: rawSources.filter(s => !s.meta),
      llmHits: meta?.llm_hits || message.llm_hits || 0,
      webQueries: meta?.web_queries || message.web_queries || 0,
      promptTokens: meta?.prompt_tokens || message.prompt_tokens || 0,
      completionTokens: meta?.completion_tokens || message.completion_tokens || 0,
      totalTokens: meta?.total_tokens || message.total_tokens || 0,
      model: message.model,
      provider: message.provider,
      createdAt: message.created_at,
    };
  };

  const stopReveal = () => {
    if (revealTimerRef.current) {
      window.clearInterval(revealTimerRef.current);
      revealTimerRef.current = null;
    }
  };

  const revealAssistantMessage = saved => {
    const restored = saved.map(messageFromSaved);
    const assistantIndex = restored.findLastIndex(message => message.role === 'assistant' && message.text);
    if (assistantIndex === -1) {
      setMessages(restored);
      return;
    }
    stopReveal();
    const fullText = restored[assistantIndex].text;
    const chunkSize = Math.max(6, Math.ceil(fullText.length / 220));
    let visibleChars = 0;
    setMessages(restored.map((message, index) => index === assistantIndex
      ? { ...message, text: '', sources: [], streaming: true }
      : message));
    revealTimerRef.current = window.setInterval(() => {
      visibleChars = Math.min(fullText.length, visibleChars + chunkSize);
      setMessages(current => current.map((message, index) => index === assistantIndex
        ? {
            ...restored[assistantIndex],
            text: fullText.slice(0, visibleChars),
            sources: visibleChars >= fullText.length ? restored[assistantIndex].sources : [],
            streaming: visibleChars < fullText.length,
          }
        : message));
      if (visibleChars >= fullText.length) {
        window.clearInterval(revealTimerRef.current);
        revealTimerRef.current = null;
      }
    }, 16);
  };

  const openChat = async chat => {
    setRailOpen(false);
    stopReveal();
    const saved = await api.chatMessages(chat.id);
    const latestJob = jobs.find(job => job.conversation_id === chat.id);
    setSelectedFileIds(latestJob?.file_ids ?? []);
    setActiveChat(chat.id);
    const restored = saved.map(messageFromSaved);
    if (latestJob && !restored.some(message => message.role === 'user' && message.text === latestJob.question)) {
      restored.push({ id: 'temp-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6), role: 'user', text: latestJob.question });
    }
    if (latestJob?.status === 'failed') {
      restored.push({ role: 'assistant', text: jobFailureMessage(latestJob), sources: [], error: true, jobId: latestJob.id });
    }
    loadedCompletedJob.current = latestJob?.id || null;
    setMessages(restored);
    jobs.filter(job => job.conversation_id === chat.id && job.status === 'completed' && !job.seen).forEach(job => markJobSeen(job.id));
  };

  useEffect(() => {
    if (!initialChatId || !chats.length) return;
    const chat = chats.find(item => item.id === initialChatId);
    if (chat) openChat(chat);
    clearInitialChat();
  }, [initialChatId, chats]);

  useEffect(() => {
    if (initialChatId || activeChat || !chats.length) return;
    const savedChatId = Number(readStorage('explore-active-chat'));
    if (!savedChatId) return;
    const chat = chats.find(item => item.id === savedChatId);
    if (chat) openChat(chat);
  }, [initialChatId, activeChat, chats]);

  // Streaming answers grow the thread continuously; use-stick-to-bottom's ResizeObserver
  // keeps us pinned to the newest content while still letting the user scroll away.
  // Opening a conversation is the exception: jump to the newest message unconditionally,
  // including out of the released lock the empty landing screen leaves behind.
  const previousMessageCount = useRef(0);
  useEffect(() => {
    const openedTranscript = previousMessageCount.current === 0 && messages.length > 0;
    previousMessageCount.current = messages.length;
    if (openedTranscript) scrollToBottom({ animation: 'instant', ignoreEscapes: true });
    else scrollToBottom({ preserveScrollPosition: true });
  }, [messages.length, thinking, directStreaming]);

  // Below 820px the header floats over the thread (30-mobile-header.css) so its blur shows
  // scrolled content behind it, which means it no longer pushes the thread down by itself.
  // The thread needs the header's real height - title/subtitle can wrap to different line
  // counts - to pad itself clear at rest, published as a CSS var rather than hardcoded.
  useEffect(() => {
    const node = mobileHeaderRef.current;
    if (!node || typeof ResizeObserver === 'undefined') return undefined;
    const root = document.documentElement;
    const update = () => root.style.setProperty('--mobile-header-h', `${Math.ceil(node.getBoundingClientRect().height)}px`);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => {
      observer.disconnect();
      root.style.removeProperty('--mobile-header-h');
    };
  }, []);

  // Keyboard, rotation and a resizing composer all change the thread container's height
  // rather than its content; see useRepinOnResize.
  const setThreadResizeTarget = useRepinOnResize(scrollToBottom);
  const threadScrollRef = useCallback(node => {
    threadRef(node);
    setThreadResizeTarget(node);
  }, [threadRef, setThreadResizeTarget]);

  // An empty thread is a landing screen, not a transcript - start it at the top so the
  // prompt and the mode hints are what the user actually sees. Runs after the paint that
  // stick-to-bottom pins on, hence the timeout plus stopScroll.
  useEffect(() => {
    if (messages.length) return undefined;
    const timer = window.setTimeout(() => {
      stopScroll();
      threadRef.current?.scrollTo({ top: 0 });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [messages.length, activeChat, stopScroll]);

  useEffect(() => () => {
    stopReveal();
  }, []);

  useEffect(() => {
    const finished = jobs.find(job => job.conversation_id === activeChat && ['completed', 'failed'].includes(job.status));
    if (!finished || loadedCompletedJob.current === finished.id) return;
    loadedCompletedJob.current = finished.id;
    if (finished.status === 'failed') {
      const reason = jobFailureMessage(finished);
      setMessages(current => current.some(message => message.jobId === finished.id)
        ? current
        : [...current, { role: 'assistant', text: reason, sources: [], error: true, jobId: finished.id }]);
      toast(reason, 'error');
      return;
    }
    api.chatMessages(activeChat).then(saved => {
      revealAssistantMessage(saved);
      if (!finished.seen) markJobSeen(finished.id);
    });
  }, [jobs, activeChat, markJobSeen]);

  useEffect(() => {
    const last = messages[messages.length - 1];
    if (!last || last.role !== 'assistant' || last.streaming || last.error || !last.text) {
      setFollowups(current => (current.key === null ? current : { key: null, items: [], loading: false }));
      return;
    }
    const key = last.id ?? last.streamId ?? messages.length - 1;
    if (followups.key === key) return;
    const priorUser = [...messages.slice(0, messages.length - 1)].reverse().find(item => item.role === 'user');
    if (!priorUser) {
      setFollowups({ key, items: [], loading: false });
      return;
    }
    setFollowups({ key, items: [], loading: true });
    api.chatSuggestions(priorUser.text, last.text, provider, model)
      .then(result => setFollowups(current => (current.key === key ? { key, items: result.suggestions || [], loading: false } : current)))
      .catch(() => setFollowups(current => (current.key === key ? { key, items: [], loading: false } : current)));
  }, [messages]);

  const askSuggestion = (text) => {
    setFollowups({ key: null, items: [], loading: false });
    ask(text);
  };

  const newChat = () => {
    setRailOpen(false);
    stopReveal();
    setActiveChat(null);
    window.localStorage.removeItem(ACTIVE_CHAT_STORAGE_KEY);
    setMessages([]);
    setQuestion('');
    setSelectedFileIds([]);
  };

  useEffect(() => {
    if (newChatSignal) newChat();
  }, [newChatSignal]);

  const stripSlashPrefix = (text) => {
    for (const cmd of SLASH_COMMANDS) {
      const prefix = cmd.label;
      if (text === prefix) return '';
      if (text.startsWith(prefix + ' ')) return text.slice(prefix.length + 1);
    }
    return text;
  };

  const ask = async (text) => {
    stopReveal();
    const value = text.trim();
    if (!value) return;
    const mode = getReasoningMode(value);
    const cleanText = stripSlashPrefix(value);
    if (!cleanText) { toast('Ask a question', 'error'); return; }
    const effectiveWebSearch = shouldAutoWebSearch(cleanText, mode);
    if (mode === 'ticket_analysis' && (selectedFileIds === null || selectedFileIds.length !== 1)) {
      toast('Ticket Analysis requires exactly one selected ticket file', 'error');
      setSelectFilesOpen(true);
      return;
    }
    setQuestion('');
    // Keep the composer focused so the mobile keyboard does not collapse on send, and
    // re-arm stick-to-bottom in case the landing screen released it.
    composerRef.current?.focus();
    scrollToBottom({ ignoreEscapes: true });
    const canDirectStream = false;
    if (canDirectStream) {
      const streamId = crypto.randomUUID();
      const controller = new AbortController();
      let streamedChars = 0;
      let sawFirstToken = false;
      stopRequestedRef.current = false;
      directAbortRef.current = controller;
      const baseActivity = [
        { id: 'request', label: 'Sending request', detail: `${PROVIDER_LABELS[provider] || provider} · ${model}`, state: 'live' },
        { id: 'connect', label: 'Connecting model', detail: 'Waiting for first token', state: 'pending' },
        { id: 'stream', label: 'Streaming answer', detail: 'Preparing response', state: 'pending' },
        { id: 'save', label: 'Saving chat', detail: 'History will update after completion', state: 'pending' },
      ];
      setDirectStreaming(true);
      setMessages(current => [
        ...current,
        { id: 'temp-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6), role: 'user', text: cleanText },
        { role: 'assistant', text: '', sources: [], model, provider, streaming: true, streamId, activity: baseActivity },
      ]);
      try {
        const result = await api.directChatStream(cleanText, activeChat, provider, model, allowGeneralKnowledge, mode, event => {
          if (event.type === 'start') {
            setActiveChat(event.conversation_id);
            setMessages(current => current.map(message => message.streamId === streamId
              ? {
                  ...message,
                  activity: baseActivity.map(item => item.id === 'request'
                    ? { ...item, state: 'done', detail: 'Request accepted' }
                    : item.id === 'connect'
                      ? { ...item, state: 'live', detail: `Connected to ${PROVIDER_LABELS[event.provider] || event.provider || provider}` }
                      : item),
                }
              : message));
          }
          if (event.type === 'token') {
            streamedChars += event.text.length;
            sawFirstToken = true;
            setMessages(current => current.map(message => message.streamId === streamId
              ? {
                  ...message,
                  text: `${message.text || ''}${event.text}`,
                  streaming: true,
                  activity: baseActivity.map(item => {
                    if (item.id === 'request') return { ...item, state: 'done', detail: 'Request accepted' };
                    if (item.id === 'connect') return { ...item, state: 'done', detail: 'First token received' };
                    if (item.id === 'stream') return { ...item, state: 'live', detail: `${streamedChars.toLocaleString()} characters received` };
                    return item;
                  }),
                }
              : message));
          }
          if (event.type === 'result') {
            setMessages(current => current.map(message => message.streamId === streamId
              ? {
                  ...message,
                  text: event.data.answer,
                  sources: (event.data.sources || []).filter(s => !s.meta),
                  llmHits: event.data.llm_hits || 1,
                  webQueries: event.data.web_queries || 0,
                  promptTokens: event.data.prompt_tokens || 0,
                  completionTokens: event.data.completion_tokens || 0,
                  totalTokens: event.data.total_tokens || 0,
                  model: event.data.model,
                  provider,
                  streaming: false,
                  activity: [
                    { id: 'request', label: 'Request sent', detail: 'Accepted by backend', state: 'done' },
                    { id: 'connect', label: 'Model connected', detail: sawFirstToken ? 'Tokens streamed live' : 'Response completed', state: 'done' },
                    { id: 'stream', label: 'Answer received', detail: `${event.data.answer.length.toLocaleString()} characters`, state: 'done' },
                    { id: 'save', label: 'Saved to chat', detail: 'History is up to date', state: 'done' },
                    ...(message.activity || []).filter(item => item.id.startsWith('diagnostic-')),
                  ],
                }
              : message));
          }
          if (event.type === 'diagnostic') {
            setMessages(current => current.map(message => message.streamId === streamId
              ? {
                  ...message,
                  activity: [
                    ...(message.activity || []),
                    { id: `diagnostic-${Date.now()}`, label: 'Model constraint', detail: event.detail, state: 'failed' },
                  ],
                }
              : message));
          }
        }, { signal: controller.signal });
        setActiveChat(result.conversation_id);
        const saved = await api.chatMessages(result.conversation_id);
        setMessages(saved.map(messageFromSaved));
        await refreshChats?.();
      } catch (error) {
        if (stopRequestedRef.current || error.name === 'AbortError') {
          setMessages(current => current.map(message => message.streamId === streamId
            ? {
                ...message,
                text: message.text || 'Stopped.',
                streaming: false,
                activity: [
                  ...(message.activity || []).filter(item => item.state === 'done'),
                  { id: 'stopped', label: 'Stopped', detail: 'Answer stopped by user', state: 'failed' },
                ],
              }
            : message));
          return;
        }
        setMessages(current => current.map(message => message.streamId === streamId
          ? {
              ...message,
              text: message.text || error.message,
              sources: [],
              error: true,
              streaming: false,
              activity: [
                { id: 'request', label: 'Stream stopped', detail: error.message, state: 'failed' },
              ],
            }
          : message));
        toast(error.message, 'error');
      } finally {
        setDirectStreaming(false);
        directAbortRef.current = null;
      }
      return;
    }
      const tempId = 'temp-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6);
      setMessages(current => [...current, { id: tempId, role: 'user', text: cleanText }]);
      try {
        const job = await createChatJob(cleanText, activeChat, provider, model, allowGeneralKnowledge, mode, selectedFileIds, webSourceLimit, effectiveWebSearch);
        setActiveChat(job.conversation_id);
      } catch (error) {
        setMessages(current => [...current, { role: 'assistant', text: error.message, sources: [] }]);
        toast(error.message, 'error');
      }
  };

  const stopAnswer = async () => {
    stopRequestedRef.current = true;
    directAbortRef.current?.abort();
    setDirectStreaming(false);
    try {
      if (activeJob) {
        await api.cancelChatJob(activeJob.id);
      } else if (activeChat) {
        await api.stopChat(activeChat);
      }
      if (activeChat) {
        const saved = await api.chatMessages(activeChat).catch(() => null);
        if (saved) setMessages(saved.map(messageFromSaved));
      }
      await refreshJobs?.();
      await refreshChats?.();
    } catch (error) {
      toast(error.message, 'error');
      return;
    }
    setMessages(current => current.map(message => message.streaming
      ? { ...message, text: message.text || 'Stopped.', streaming: false }
      : message));
    toast('Stopped. You can switch model and ask again.', 'success');
  };

  const truncateFromMessage = async (message) => {
    if (!activeChat || !message.id) return null;
    stopReveal();
    const saved = await api.truncateChatFromMessage(activeChat, message.id);
    setMessages(saved.map(messageFromSaved));
    await Promise.all([refreshChats?.(), refreshJobs?.()]);
    loadedCompletedJob.current = null;
    return saved;
  };

  const editMessage = async (message) => {
    if (thinking || message.role !== 'user') return;
    try {
      if (message.id && !String(message.id).startsWith('temp-')) {
        await truncateFromMessage(message);
      }
      setQuestion(message.text);
      window.setTimeout(() => composerRef.current?.focus(), 0);
    } catch (error) {
      toast(error.message, 'error');
    }
  };

  const askAgain = async (message, index) => {
    if (thinking) return;
    let promptMessage = message;
    let promptIndex = index;
    if (message.role !== 'user') {
      const userEntry = [...messages.slice(0, index).entries()].reverse().find(([, item]) => item.role === 'user');
      if (!userEntry) return;
      [promptIndex, promptMessage] = userEntry;
    }
    try {
      if (promptMessage.id && !String(promptMessage.id).startsWith('temp-')) {
        await truncateFromMessage(promptMessage);
      } else {
        setMessages(current => current.slice(0, promptIndex));
      }
      await ask(promptMessage.text);
    } catch (error) {
      toast(error.message, 'error');
    }
  };

  const applySlashCommand = (cmd) => {
    setQuestion(cmd.label + ' ');
    setReasoningMode(cmd.id);
    setSlashOpen(false);
    setSlashIndex(-1);
    composerRef.current?.focus();
  };

  const handleComposerInput = (event) => {
    const val = event.target.value;
    setQuestion(val);
    if (val.match(/^\/(\w*)$/) && val.length > 0) {
      const partial = val.slice(1).toLowerCase();
      const matches = SLASH_COMMANDS.filter(c => c.label.slice(1).toLowerCase().startsWith(partial));
      if (matches.length > 0) {
        setSlashFilter(partial);
        setSlashOpen(true);
        setSlashIndex(0);
        return;
      }
    }
    setSlashOpen(false);
    setSlashIndex(-1);
  };

  const handleComposerKeyDown = (event) => {
    if (slashOpen) {
      const matches = SLASH_COMMANDS.filter(c => c.label.slice(1).toLowerCase().startsWith(slashFilter));
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setSlashIndex(i => Math.min(i + 1, matches.length - 1));
        return;
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        setSlashIndex(i => Math.max(i - 1, 0));
        return;
      }
      if (event.key === 'Enter' || event.key === 'Tab') {
        event.preventDefault();
        if (matches[slashIndex]) { applySlashCommand(matches[slashIndex]); }
        return;
      }
      if (event.key === 'Escape') {
        setSlashOpen(false);
        setSlashIndex(-1);
        return;
      }
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      ask(question);
    }
  };

  const matchedCommands = slashOpen ? SLASH_COMMANDS.filter(c => c.label.slice(1).toLowerCase().startsWith(slashFilter)) : [];

  const openUpload = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.pdf,.csv,.xlsx,.xls,.md,.txt';
    input.multiple = true;
    input.onchange = async (e) => {
      const fileList = Array.from(e.target.files);
      if (!fileList.length) return;
      const storeId = stores[0]?.id;
      if (!storeId) { toast('Create a store in Library first', 'error'); return; }
      let count = 0;
      for (const file of fileList) {
        try {
          const uploaded = await api.uploadFile(storeId, file);
          const fid = uploaded?.id || uploaded?.file?.id;
          if (fid) {
            setSelectedFileIds(cur => cur ? [...cur, fid] : [fid]);
            count++;
          }
        } catch { /* skip failed */ }
      }
      if (count) toast(`Uploaded ${count} file${count > 1 ? 's' : ''}`, 'success');
      else toast('Upload failed', 'error');
    };
    input.click();
  };

  const copyAnswer = async (text, index) => {
    await navigator.clipboard.writeText(text);
    setCopiedIndex(index);
    toast('Answer copied', 'success');
    window.setTimeout(() => setCopiedIndex(null), 1500);
  };

  const copyConversationId = async () => {
    if (!activeChat) return;
    const chat = chats.find(item => item.id === activeChat);
    const title = chat?.title || 'Untitled conversation';
    const statsParts = [
      `${messages.length} message${messages.length === 1 ? '' : 's'}`,
      model ? `${PROVIDER_LABELS[provider] || provider}/${model}` : null,
      sessionTokens > 0 ? `${sessionTokens.toLocaleString()} tokens` : null,
    ].filter(Boolean);
    const recent = messages.filter(message => message.text).slice(-6);
    const omitted = messages.filter(message => message.text).length - recent.length;
    const transcript = recent
      .map(message => `${message.role === 'user' ? 'Q' : 'A'}: ${message.text.length > 600 ? `${message.text.slice(0, 600)}…` : message.text}`)
      .join('\n\n');
    const payload = [
      `Locus conversation #${activeChat} — "${title}"`,
      statsParts.join(' · '),
      omitted > 0 ? `(${omitted} earlier message${omitted === 1 ? '' : 's'} omitted)` : null,
      '',
      transcript,
    ].filter(line => line !== null).join('\n');
    await navigator.clipboard.writeText(payload);
    setCopiedConvId(true);
    toast('Conversation context copied', 'success');
    window.setTimeout(() => setCopiedConvId(false), 1500);
  };

  const detachFile = (id) => {
    setSelectedFileIds(cur => cur ? cur.filter(fid => fid !== id) : []);
  };

  return (
    <div className="explore-shell">
      <aside className={`chat-rail ${railOpen ? 'open' : ''}`}>
        <div className="chat-rail-head">
          <span className="kicker">Chats</span>
          <span className="chat-rail-count">{chats.length}</span>
          {runningCount > 0 && <span className="chat-rail-running">{runningCount} running</span>}
          <button type="button" className="chat-rail-new" onClick={newChat} aria-label="Start a new conversation">
            <Plus size={13} /> New
          </button>
          <button type="button" className="chat-rail-close icon-button" onClick={() => setRailOpen(false)} aria-label="Close chat history">
            <X size={18} />
          </button>
        </div>
        <div className="chat-rail-list">
          {chats.map(chat => {
            const latestJob = jobs.find(j => j.conversation_id === chat.id);
            const inProgress = ['queued', 'running'].includes(latestJob?.status);
            const ready = latestJob?.status === 'completed' && !latestJob.seen;
            const failed = latestJob?.status === 'failed';
            return (
              <div
                key={chat.id}
                role="button"
                tabIndex={0}
                className={`chat-rail-item ${activeChat === chat.id ? 'active' : ''} ${inProgress ? 'in-progress' : ''} ${ready ? 'ready' : ''} ${failed ? 'failed' : ''}`}
                onClick={() => openChat(chat)}
                onKeyDown={e => {
                  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openChat(chat); }
                }}
                title={chat.title}
              >
                <span className="chat-rail-name">
                  <span>{chat.title}</span>
                  {inProgress && <i className="chat-dot progress" />}
                  {ready && <i className="chat-dot ready" />}
                  {failed && <i className="chat-dot failed" />}
                </span>
                <span className="chat-rail-time">{formatChatTime(chat.updated_at)}</span>
                <button
                  type="button"
                  className="chat-rail-delete"
                  onClick={e => { e.stopPropagation(); requestDeleteChat?.(chat, () => { if (activeChat === chat.id) newChat(); }); }}
                  aria-label={`Delete ${chat.title}`}
                >
                  <Trash2 size={12} />
                </button>
              </div>
            );
          })}
          {!chats.length && <span className="chat-rail-empty">No chats yet</span>}
        </div>
        {!!chats.length && (
          <button
            type="button"
            className="chat-rail-delete-all"
            disabled={hasActiveJobs}
            title={hasActiveJobs ? 'Wait for active answers to finish' : 'Delete all chats'}
            onClick={() => requestDeleteAllChats?.(() => newChat())}
          >
            <Trash2 size={13} /> Delete all chats
          </button>
        )}
      </aside>
      {railOpen && <button type="button" className="chat-rail-scrim" aria-label="Close chat history" onClick={() => setRailOpen(false)} />}
      <div className="chat-page">
        <div className="chat-top" ref={mobileHeaderRef}>
          <div className="chat-top-left">
            <button className="menu-button icon-button" onClick={openMenu} aria-label="Open menu">
              <Menu size={20} />
            </button>
            <button
              type="button"
              className="rail-toggle icon-button"
              onClick={() => setRailOpen(true)}
              aria-label="Show chat history"
            >
              <History size={19} />
              {chats.length > 0 && <span className="rail-toggle-count">{chats.length}</span>}
            </button>
            <span className="workspace-label"><i /> ASK</span>
            <div className="chat-top-heading">
              <strong>{activeChatTitle}</strong>
              <small>{headerSubtitle}</small>
            </div>
            <div className="chat-top-info">
              {activeChat && (
                <button
                  className="copy-conv-id-button"
                  onClick={copyConversationId}
                  aria-label="Copy conversation context"
                  title={`Copy conversation #${activeChat} with context`}
                  {...tip('Copy this conversation\'s title, stats, and recent messages so it makes sense wherever you paste it.')}
                >
                  {copiedConvId ? <Check size={14} /> : <Copy size={14} />}
                  <span>{activeChat}</span>
                </button>
              )}
              {sessionTokens > 0 && (
                <span className="chat-session-usage" {...tip('Total tokens and LLM calls used across this conversation')}>
                  <Cpu size={12} />
                  <span>{sessionTokens.toLocaleString()} tokens</span>
                  <span className="chat-session-usage-sep">·</span>
                  <span>{sessionLlmHits} LLM {sessionLlmHits === 1 ? 'hit' : 'hits'}</span>
                </span>
              )}
            </div>
          </div>
          <div className="chat-top-right">
            <button
              className="explore-header-new-chat mobile-only-new-chat"
              onClick={newChat}
              aria-label="New conversation"
            >
              <Plus size={20} />
            </button>
            {/* Phone-only overflow. Three separate controls in the header is what pushed the
                stat pills onto a second row and over the thread; behind one button they fit. */}
            <div className="chat-more-wrap" ref={moreMenuRef}>
              <button
                type="button"
                className="chat-more-toggle icon-button"
                onClick={() => setMoreMenuOpen(value => !value)}
                aria-label="More actions"
                aria-expanded={moreMenuOpen}
              >
                <MoreHorizontal size={19} />
              </button>
              {moreMenuOpen && (
                <div className="chat-more-menu" role="menu">
                  <button type="button" role="menuitem" onClick={() => { setMoreMenuOpen(false); newChat(); }}>
                    <Plus size={14} /> New chat
                  </button>
                  <button type="button" role="menuitem" onClick={() => { setMoreMenuOpen(false); setRailOpen(true); }}>
                    <History size={14} /> Chat history
                    {chats.length > 0 && <span className="chat-more-count">{chats.length}</span>}
                  </button>
                  <button type="button" role="menuitem" onClick={() => { setMoreMenuOpen(false); setOptionsOpen(true); }}>
                    <SlidersHorizontal size={14} /> Model options
                  </button>
                  {activeChat && (
                    <button type="button" role="menuitem" onClick={() => { setMoreMenuOpen(false); copyConversationId(); }}>
                      {copiedConvId ? <Check size={14} /> : <Copy size={14} />} Copy conversation
                    </button>
                  )}
                  {sessionTokens > 0 && (
                    <div className="chat-more-usage" role="note">
                      <Cpu size={14} />
                      <span>{sessionTokens.toLocaleString()} tokens · {sessionLlmHits} LLM {sessionLlmHits === 1 ? 'hit' : 'hits'}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
            <div className="desktop-controls">
              <ModelControl config={llmConfig} provider={provider} setProvider={setProvider} model={model} setModel={setModel} />
            </div>
            <div className="options-popover-wrap" ref={optionsPopoverRef}>
              <button
                type="button"
                className="options-toggle icon-button"
                onClick={() => setOptionsOpen(value => !value)}
                aria-label="Model options"
                aria-expanded={optionsOpen}
              >
                <SlidersHorizontal size={18} />
              </button>
              <div className={`options-popover desktop-controls ${optionsOpen ? 'open' : ''}`}>
                <ModelControl config={llmConfig} provider={provider} setProvider={setProvider} model={model} setModel={setModel} />
              </div>
            </div>
          </div>
        </div>

        <div
          ref={threadScrollRef}
          className={`chat-thread ${messages.length ? 'has-messages' : ''}`}
          aria-live="polite"
          aria-relevant="additions"
        >
          <div className="chat-thread-inner" ref={threadContentRef}>
            {!messages.length && (
              <div className="chat-empty">
                <div className="chat-orb"><Sparkles size={29} /></div>
                <h2>What do you want to ask?</h2>
                <p>Ask directly, attach files, or switch modes when the question needs deeper work.</p>
                {stores.length > 0 && (
                  <div className="quick-start-chips">
                    {stores.slice(0, 3).map(store => (
                      <button
                        key={store.id}
                        type="button"
                        className="quick-start-chip"
                        onClick={() => {
                          setQuestion(`What can you tell me about ${store.title}?`);
                          window.setTimeout(() => composerRef.current?.focus(), 0);
                        }}
                      >
                        <Folder size={12} /> Ask about {store.title}
                      </button>
                    ))}
                  </div>
                )}
                <div className="slash-hints">
                  {SLASH_COMMANDS.map(cmd => {
                    const Icon = cmd.icon;
                    return (
                      <button type="button" key={cmd.id} className="slash-hint" onClick={() => applySlashCommand(cmd)}>
                        <Icon size={13} style={{ color: cmd.color }} />
                        <span className="slash-hint-key">{cmd.label}</span>
                        <span className="slash-hint-desc">{cmd.desc}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
            {messages.map((message, index) => (
              <div className={`chat-message ${message.role} ${message.error ? 'error' : ''}`} key={message.id || message.streamId || index}>
                {message.role === 'assistant' && <div className="assistant-avatar"><Sparkles size={15} /></div>}
                <div className="message-body">
                  <div className="message-head">
                    <span className="message-head-label">
                      <span>{message.role === 'assistant' ? assistantLabel(message.model, message.provider, PROVIDER_LABELS) : 'You'}</span>
                      {message.role === 'assistant' && message.totalTokens > 0 && (
                        <span className="message-tokens" title={`${message.promptTokens.toLocaleString()} prompt + ${message.completionTokens.toLocaleString()} completion tokens`}>
                          {message.totalTokens.toLocaleString()} tokens
                        </span>
                      )}
                    </span>
                    <div className="message-actions">
                      {message.id && (
                        <>
                          {message.role === 'user' && (
                            <button className="message-action icon-button" type="button" disabled={thinking} onClick={() => editMessage(message)} aria-label="Edit question" title="Edit question">
                              <PenLine size={13} />
                            </button>
                          )}
                          {(message.role === 'user' || message.error) && (
                            <button className="message-action icon-button" type="button" disabled={thinking} onClick={() => askAgain(message, index)} aria-label="Ask again" title="Ask again with current model">
                              <RotateCcw size={13} />
                            </button>
                          )}
                          <button className="copy-button icon-button" type="button" onClick={() => copyAnswer(message.text, index)} aria-label="Copy query" title="Copy query">
                            {copiedIndex === index ? <Check size={14} /> : <Copy size={14} />}
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                  {message.role === 'assistant' ? (
                    <>
                      <DirectStreamTrace activity={message.activity} model={message.model} provider={message.provider} text={message.text} streaming={message.streaming} />
                      <div className={`markdown-answer ${message.streaming ? 'streaming' : ''}`}><AssistantMarkdown text={message.text} streaming={message.streaming} messageKey={message.id || message.streamId || index} /></div>
                    </>
                  ) : (
                    <p>{message.text}</p>
                  )}
  {message.sources?.length > 0 && (
                      <CollapsibleSources
                        sources={message.sources}
                        index={index}
                        isExpanded={expandedSources[index]}
                        onToggle={() => toggleSources(index)}
                        onOpenStore={onOpenStore}
                        model={message.model}
                        provider={message.provider}
                        llmHits={message.llmHits}
                        webQueries={message.webQueries}
                      />
                    )}
                </div>
              </div>
            ))}
            {!thinking && (followups.loading || followups.items.length > 0) && (
              <div className="chat-suggestions" aria-label="Suggested follow-up questions">
                {followups.loading
                  ? Array.from({ length: 3 }).map((_, index) => <span className="chat-suggestion-skeleton" key={index} />)
                  : followups.items.map((suggestion, index) => (
                      <button type="button" className="chat-suggestion-chip" key={index} onClick={() => askSuggestion(suggestion)}>
                        <Sparkles size={12} />
                        <span>{suggestion}</span>
                      </button>
                    ))}
              </div>
            )}
            {activeJob && (
              <PipelineActivity
                pipeline={{ stage: activeJob.stage, detail: activeJob.detail }}
                model={activeJob.model}
                provider={activeJob.provider}
                events={activeJob.events || []}
                startedAt={parseServerTime(activeJob.created_at)}
                reasoningMode={activeJob.reasoning_mode}
                webSearch={activeJob.web_search}
                fileCount={activeJob.file_ids === null ? files.length : (activeJob.file_ids?.length ?? selectedCount)}
                question={activeJob.question}
                liveLlmHits={activeJob.llm_hits}
                liveWebQueries={activeJob.web_queries}
                liveTotalTokens={activeJob.total_tokens}
              />
            )}
            {activeJob?.partial_answer && (
              <div className="chat-message assistant">
                <div className="assistant-avatar"><Sparkles size={15} /></div>
                <div className="message-body">
                  <div className="markdown-answer streaming">
                    <AssistantMarkdown text={activeJob.partial_answer} streaming messageKey={`job-${activeJob.id}`} />
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        <form
          className="chat-composer"
          ref={slashScopeRef}
          onSubmit={event => { event.preventDefault(); ask(question); }}
        >
          {!isAtBottom && messages.length > 0 && (
            <button
              type="button"
              className="scroll-to-bottom-btn"
              onPointerDown={event => event.preventDefault()}
              onClick={() => scrollToBottom()}
              aria-label="Scroll to latest message"
            >
              <ChevronDown size={14} /> Latest
            </button>
          )}
          {slashOpen && matchedCommands.length > 0 && (
            <div className="slash-popup">
              {matchedCommands.map((cmd, i) => {
                const Icon = cmd.icon;
                return (
                  <button
                    type="button"
                    className={`slash-item ${i === slashIndex ? 'selected' : ''}`}
                    key={cmd.id}
                    onMouseDown={e => { e.preventDefault(); applySlashCommand(cmd); }}
                    onMouseEnter={() => setSlashIndex(i)}
                  >
                    <Icon size={14} style={{ color: cmd.color }} />
                    <div className="slash-info">
                      <span className="slash-name">{cmd.label}</span>
                      <span className="slash-desc">{cmd.desc}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
          <div className="composer-tools">
            <div className="composer-tools-group">
              <div className={`mode-picker ${modePickerOpen ? 'open' : ''}`} ref={modePickerRef}>
                <button
                  type="button"
                  className={`composer-tool-btn mode-picker-trigger mode-${previewReasoningMode}`}
                  onClick={() => setModePickerOpen(v => !v)}
                  aria-expanded={modePickerOpen}
                  aria-label="Choose reasoning mode"
                >
                  {(() => { const Icon = (SLASH_COMMANDS.find(c => c.id === previewReasoningMode)?.icon) || Radio; return <Icon size={13} />; })()}
                  <span>{displayedModeLabel}</span>
                  <ChevronDown size={11} />
                </button>
                {modePickerOpen && (
                  <div className="mode-picker-menu" role="listbox" aria-label="Reasoning mode menu">
                    {SLASH_COMMANDS.map(cmd => {
                      const Icon = cmd.icon;
                      const active = cmd.id === reasoningMode;
                      return (
                        <button
                          type="button"
                          key={cmd.id}
                          className={`mode-picker-option ${active ? 'active' : ''}`}
                          onClick={() => { setReasoningMode(cmd.id); setModePickerOpen(false); }}
                          role="option"
                          aria-selected={active}
                        >
                          <Icon size={14} style={{ color: cmd.color }} />
                          <span className="mode-picker-option-text">
                            <strong>{cmd.label.slice(1)}</strong>
                            <small>{cmd.desc}</small>
                          </span>
                          {active && <Check size={13} />}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
              <button
                type="button"
                className={`composer-tool-btn composer-tool-btn-icon ${selectedCount > 0 ? 'active' : ''}`}
                onClick={() => setSelectFilesOpen(true)}
                aria-label={selectedCount > 0 ? `${selectedCount} file${selectedCount > 1 ? 's' : ''} selected` : 'Select files'}
                {...tip(selectedCount > 0 ? `${selectedCount} file${selectedCount > 1 ? 's' : ''} selected` : 'Select files to scope this chat')}
              >
                <FileText size={13} />
                {selectedCount > 0 && <span className="tool-count-badge">{selectedCount}</span>}
              </button>
              <button
                type="button"
                className="composer-tool-btn composer-tool-btn-icon"
                onClick={openUpload}
                aria-label="Upload a file"
                {...tip('Upload a file')}
              >
                <FilePlus2 size={13} />
              </button>
              <button
                type="button"
                className={`composer-tool-btn composer-tool-btn-icon ${allowGeneralKnowledge ? 'active' : ''}`}
                onClick={() => setAllowGeneralKnowledge(v => !v)}
                aria-pressed={allowGeneralKnowledge}
                aria-label={`LLM knowledge ${allowGeneralKnowledge ? 'on' : 'off'}`}
                {...tip('Allow the model to use general knowledge beyond your files')}
              >
                <BrainCircuit size={13} />
                <span className={`tool-dot ${allowGeneralKnowledge ? 'on' : ''}`} />
              </button>
            </div>
          </div>
          <div className="composer-input-row">
            <div className="input-wrap">
              <TextareaAutosize
                ref={composerRef}
                minRows={1}
                maxRows={compactViewport ? 3 : 6}
                value={question}
                onChange={handleComposerInput}
                onKeyDown={handleComposerKeyDown}
                placeholder="Ask or type / for commands..."
                enterKeyHint="send"
              />
            </div>
            {thinking ? (
              <button type="button" className="stop-answer-button" onClick={stopAnswer} aria-label="Stop answer" title="Stop answer">
                <Square size={15} />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!question.trim()}
                aria-label="Send question"
                onPointerDown={e => e.preventDefault()}
                onMouseDown={e => e.preventDefault()}
              >
                <Send size={17} />
              </button>
            )}
          </div>
          <div className="composer-meta">
            <div>
              {autoWebSearchPreview && (
                <span className="composer-meta-web"><Globe size={10} /> Will also search the web</span>
              )}
            </div>
            <small><kbd>Enter</kbd> to send · <kbd>Shift Enter</kbd> for a new line</small>
          </div>
        </form>
      </div>

      {/* Select Files Modal */}
      {selectFilesOpen && (
        <div className="modal-overlay" onMouseDown={e => e.target === e.currentTarget && setSelectFilesOpen(false)}>
          <div className="modal file-select-modal">
            <div className="modal-header">
              <h3>Select Files</h3>
              <button type="button" className="modal-close-btn" onClick={() => setSelectFilesOpen(false)}><X size={18} /></button>
            </div>
            <div className="file-select-list">
              {files.length === 0 && <p className="file-select-empty">No files uploaded yet. Upload files in Library first.</p>}
              {stores.map(store => {
                const storeFiles = files.filter(f => f.store_id === store.id);
                if (!storeFiles.length) return null;
                const allSelected = storeFiles.every(f => selectedFileIds?.includes(f.id));
                return (
                  <div className="file-select-store" key={store.id}>
                    <div className="file-select-store-head">
                      <Folder size={14} />
                      <strong>{store.title}</strong>
                      <button
                        type="button"
                        className="file-select-store-toggle"
                        onClick={() => {
                          const ids = storeFiles.map(f => f.id);
                          const current = selectedFileIds || [];
                          if (allSelected) setSelectedFileIds(current.filter(id => !ids.includes(id)));
                          else setSelectedFileIds([...new Set([...current, ...ids])]);
                        }}
                      >
                        {allSelected ? 'Deselect all' : 'Select all'}
                      </button>
                    </div>
                    {storeFiles.map(file => {
                      const checked = selectedFileIds?.includes(file.id) || false;
                      return (
                        <label key={file.id} className={`file-select-row ${checked ? 'checked' : ''}`}>
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleFile(file.id)}
                          />
                          <span className="file-select-check" />
                          <FileText size={13} />
                          <span className="file-select-name">
                            <strong>{file.name}</strong>
                            <small>{fileMetaLine(file)}</small>
                          </span>
                        </label>
                      );
                    })}
                  </div>
                );
              })}
            </div>
            <div className="modal-footer">
              <span className="file-select-count">{selectedFileIds?.length || 0} files selected</span>
              <button type="button" className="btn-primary" onClick={() => setSelectFilesOpen(false)}>Done</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
