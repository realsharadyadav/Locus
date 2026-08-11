import React from 'react';
import {
  Menu, Search,
} from 'lucide-react';

/**
 * The header carries navigation and search only.
 *
 * It used to also render a "New library" button on the Library page, but
 * HubPage already renders one beside its own title — on desktop the two sat
 * roughly 180px apart, and on mobile the header collapsed to a bare "+" that
 * duplicated the labelled button just below it. The page-level button wins:
 * it is the one with a label and with the heading for context.
 */
export function Header({ query, openMenu, openCommand }) {
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
    </header>
  );
}
