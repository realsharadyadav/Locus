import React from 'react';
import {
  Menu, Plus, Search,
} from 'lucide-react';

export function Header({ query, setQuery, openMenu, openCreate, openCommand, page }) {
  return (
    <header>
      <button className="menu-button icon-button" onClick={openMenu} aria-label="Open menu">
        <Menu size={20} />
      </button>
      <button className="global-search" onClick={openCommand} aria-label="Open search">
        <Search size={17} />
        <span>{query || 'Search everything you know...'}</span>
        <kbd>⌘ K</kbd>
      </button>
      {page === 'library' && (
        <button className="new-button" onClick={openCreate}>
          <Plus size={17} /> New library
        </button>
      )}
    </header>
  );
}
