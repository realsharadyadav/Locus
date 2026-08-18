import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Compass, FileText, Folder, LockKeyhole, Search, Settings2 } from 'lucide-react';

function formatFileSize(bytes = 0) {
  const size = Number(bytes) || 0;
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(size >= 10 * 1024 * 1024 ? 0 : 1)} MB`;
  if (size >= 1024) return `${(size / 1024).toFixed(size >= 10 * 1024 ? 0 : 1)} KB`;
  return `${size} B`;
}

function fileDetail(file, storeTitle) {
  const chunks = Number(file.embedding_chunks || 0);
  return `${storeTitle || 'File'} · ${formatFileSize(file.size)} · ${chunks === 1 ? '1 chunk' : `${chunks} chunks`}`;
}

const pages = [
  { id: 'library', label: 'Library', icon: Folder, keywords: 'stores files upload library' },
  { id: 'ask', label: 'Ask', icon: Compass, keywords: 'chat ask ai question' },
  { id: 'secret-chat', label: 'Private', icon: LockKeyhole, keywords: 'secret private encrypted chat' },
  { id: 'settings', label: 'Settings', icon: Settings2, keywords: 'settings provider model default config preferences' },
];

export function CommandPalette({ open, close, query, setQuery, stores, files, chats, onSelect }) {
  const inputRef = useRef(null);
  const [activeIndex, setActiveIndex] = useState(0);

  const items = useMemo(() => {
    const term = query.trim().toLowerCase();
    const matches = (label, extra = '') => `${label} ${extra}`.toLowerCase().includes(term);

    const navigation = pages
      .filter(page => !term || matches(page.label, page.keywords))
      .map(page => ({ type: 'page', id: page.id, label: page.label, icon: page.icon, detail: 'Navigate' }));

    const storeItems = stores
      .filter(store => !term || matches(store.title, store.description))
      .map(store => ({ type: 'store', id: store.id, label: store.title, icon: Folder, detail: `${store.count} files` }));

    const fileItems = files
      .filter(file => !term || matches(file.name))
      .slice(0, 8)
      .map(file => ({
        type: 'file',
        id: file.id,
        storeId: file.store_id,
        label: file.name,
        icon: FileText,
        detail: fileDetail(file, stores.find(store => store.id === file.store_id)?.title),
      }));

    const chatItems = chats
      .filter(chat => !term || matches(chat.title))
      .slice(0, 6)
      .map(chat => ({ type: 'chat', id: chat.id, label: chat.title, icon: Compass, detail: 'Open chat' }));

    return [...navigation, ...storeItems, ...fileItems, ...chatItems];
  }, [query, stores, files, chats]);

  useEffect(() => {
    if (open) {
      setActiveIndex(0);
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key === 'Escape') close();
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setActiveIndex(index => Math.min(index + 1, items.length - 1));
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        setActiveIndex(index => Math.max(index - 1, 0));
      }
      if (event.key === 'Enter' && items[activeIndex]) {
        event.preventDefault();
        onSelect(items[activeIndex]);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, items, activeIndex, onSelect, close]);

  if (!open) return null;

  return (
    <div className="command-palette-backdrop" onClick={close}>
      <div className="command-palette" onClick={event => event.stopPropagation()}>
        <div className="command-palette-input">
          <Search size={17} />
          <input
            ref={inputRef}
            value={query}
            onChange={event => setQuery(event.target.value)}
            placeholder="Search pages, libraries, files, chats..."
          />
        </div>
        <div className="command-palette-results">
          {items.map((item, index) => {
            const Icon = item.icon;
            return (
              <button
                key={`${item.type}-${item.id}`}
                className={index === activeIndex ? 'active' : ''}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => onSelect(item)}
              >
                <Icon size={16} />
                <span>{item.label}</span>
                <small>{item.detail}</small>
              </button>
            );
          })}
          {!items.length && <p className="command-palette-empty">No matches</p>}
        </div>
      </div>
    </div>
  );
}
