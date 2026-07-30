import React, { useState } from 'react';
import {
  ChevronDown, List,
} from 'lucide-react';

export function AnswerToc({ headings }) {
  const [collapsed, setCollapsed] = useState(false);

  if (headings.length < 3) return null;

  const jumpTo = id => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="answer-toc">
      <button type="button" className="answer-toc-toggle" onClick={() => setCollapsed(value => !value)}>
        <List size={13} />
        <span>Contents · {headings.length}</span>
        <ChevronDown size={13} className={`answer-toc-chevron ${collapsed ? 'collapsed' : ''}`} />
      </button>
      {!collapsed && (
        <ul className="answer-toc-list">
          {headings.map(heading => (
            <li key={heading.id} className={`answer-toc-item level-${heading.level}`}>
              <button type="button" onClick={() => jumpTo(heading.id)}>{heading.text}</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
