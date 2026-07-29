import React, { useLayoutEffect, useRef, useState } from 'react';
import {
  PanelLeftClose,
  PanelLeftOpen,
  Settings2,
  X,
  LayoutDashboard,
  Library,
  MessagesSquare,
  ChartNoAxesCombined,
  Fingerprint,
  Sun,
  Moon,
} from 'lucide-react';
import { Logo } from './Logo';
import { useMediaQuery } from '../hooks/useMediaQuery';

/* Keep in sync with the drawer breakpoint in the stylesheets (08-responsive.css). */
const DRAWER_QUERY = '(max-width: 980px)';

export const NAV_SECTIONS = [
  {
    label: 'Workspace',
    items: [
      { id: 'home', Icon: LayoutDashboard, label: 'Home', accent: '166 84% 55%' },
      { id: 'library', Icon: Library, label: 'Library', accent: '38 94% 60%' },
      { id: 'ask', Icon: MessagesSquare, label: 'Ask', accent: '255 88% 74%' },
    ],
  },
  {
    label: 'Signals',
    items: [
      { id: 'ticket-analysis', Icon: ChartNoAxesCombined, label: 'Patterns', accent: '205 92% 62%' },
      { id: 'secret-chat', Icon: Fingerprint, label: 'Private', accent: '341 85% 66%' },
    ],
  },
];

export function Sidebar({
  page, setPage, mobileOpen, close, fileCount, readyCount, compact, toggleCompact,
  files = [], onOpenFile, onOpenSecretChat, onNewChat, historyCollapsed, setHistoryCollapsed,
  theme, setTheme,
}) {
  const railRef = useRef(null);
  const [marker, setMarker] = useState(null);
  // Below the breakpoint the sidebar is an off-canvas drawer, so the icon-rail
  // (compact) mode has nothing to collapse into — the collapse control closes the
  // drawer instead, and the drawer always renders in its full-width form.
  const isDrawer = useMediaQuery(DRAWER_QUERY);
  const railCompact = compact && !isDrawer;

  // Measure the active nav button so a single indicator can glide between items
  // instead of each button popping its own highlight.
  useLayoutEffect(() => {
    const rail = railRef.current;
    if (!rail) return;
    const measure = () => {
      const active = rail.querySelector('.nav-item.active');
      if (!active) { setMarker(null); return; }
      setMarker({
        top: active.offsetTop,
        height: active.offsetHeight,
        accent: active.style.getPropertyValue('--nav-accent'),
      });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(rail);
    return () => observer.disconnect();
  }, [page, railCompact, mobileOpen]);

  return (
    <>
      <aside className={`sidebar ${mobileOpen ? 'open' : ''} ${railCompact ? 'compact' : ''} ${page === 'ask' ? 'sidebar-explore' : ''}`}>
        <div className="side-top">
          <Logo />
          <button className="mobile-close icon-button" onClick={close} aria-label="Close navigation">
            <X size={18} />
          </button>
        </div>
        <nav ref={railRef} className="nav-rail">
          <span
            className={`nav-marker ${marker ? 'visible' : ''}`}
            aria-hidden="true"
            style={marker ? {
              transform: `translateY(${marker.top}px)`,
              height: `${marker.height}px`,
              '--nav-accent': marker.accent,
            } : undefined}
          />
          {NAV_SECTIONS.map((section, sectionIndex) => (
            <div className="nav-group" key={section.label}>
              <span className="nav-group-label">{section.label}</span>
              {section.items.map(({ id, Icon, label, accent }, itemIndex) => (
                <button
                  key={id}
                  className={`nav-item ${page === id ? 'active' : ''}`}
                  style={{ '--nav-accent': accent, '--nav-order': sectionIndex * 3 + itemIndex }}
                  onClick={() => {
                    if (id === 'secret-chat') {
                      onOpenSecretChat?.();
                    } else {
                      setPage(id);
                      close();
                    }
                  }}
                >
                  <span className="nav-icon">
                    <Icon size={18} strokeWidth={1.9} />
                  </span>
                  <span className="nav-label">{label}</span>
                  {id === 'library' && <span className="nav-count">{fileCount}</span>}
                  {id === 'ask' && readyCount > 0 && <span className="nav-ready-dot" title={`${readyCount} answer${readyCount === 1 ? '' : 's'} ready`} />}
                </button>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <button
            className="sidebar-collapse-btn nav-item"
            style={{ '--nav-accent': '220 12% 66%' }}
            onClick={isDrawer ? close : toggleCompact}
            aria-label={isDrawer ? 'Close navigation' : railCompact ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            <span className="nav-icon">
              {railCompact ? <PanelLeftOpen size={17} strokeWidth={1.9} /> : <PanelLeftClose size={17} strokeWidth={1.9} />}
            </span>
            <span className="nav-label">{isDrawer ? 'Close menu' : 'Collapse'}</span>
          </button>
          {railCompact ? (
            <button
              className="theme-nav-toggle nav-item"
              style={{ '--nav-accent': theme === 'dark' ? '45 96% 62%' : '235 70% 66%' }}
              onClick={() => setTheme?.(theme === 'dark' ? 'light' : 'dark')}
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            >
              <span className="nav-icon">
                <span className="theme-nav-glyphs" data-theme-state={theme}>
                  <Sun size={18} strokeWidth={1.9} />
                  <Moon size={18} strokeWidth={1.9} />
                </span>
              </span>
            </button>
          ) : (
            <div className="theme-switch" role="group" aria-label="Colour theme">
              <span className="theme-switch-thumb" data-theme-state={theme} aria-hidden="true" />
              <button
                type="button"
                className={theme === 'light' ? 'active' : ''}
                onClick={() => setTheme?.('light')}
                aria-pressed={theme === 'light'}
              >
                <Sun size={15} strokeWidth={2} />
                <span>Bright</span>
              </button>
              <button
                type="button"
                className={theme === 'dark' ? 'active' : ''}
                onClick={() => setTheme?.('dark')}
                aria-pressed={theme === 'dark'}
              >
                <Moon size={15} strokeWidth={2} />
                <span>Dark</span>
              </button>
            </div>
          )}
          <button
            className={`sidebar-settings-btn nav-item ${page === 'settings' ? 'active' : ''}`}
            style={{ '--nav-accent': '220 12% 66%' }}
            onClick={() => { setPage('settings'); close(); }}
          >
            <span className="nav-icon">
              <Settings2 size={17} strokeWidth={1.9} />
            </span>
            <span className="nav-label">Settings</span>
          </button>
        </div>
      </aside>
      {mobileOpen && <button className="scrim" aria-label="Close navigation" onClick={close} />}
    </>
  );
}
