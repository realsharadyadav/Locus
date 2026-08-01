import React, { useState } from 'react';
import { ChevronDown } from 'lucide-react';

// One collapsible block of an answer: its h2 plus everything under it, grouped by
// rehypeAnswerSections. Sections start expanded — collapsing is there to get a long answer out of
// the way, not to hide content the user has not seen yet. The children are left untouched and the
// collapsed state is a data attribute, so CSS does the hiding and no child surgery is needed.
// `node` is react-markdown's hast node — it must be dropped rather than spread onto the DOM.
export function AnswerSection({ children, node, ...props }) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <section {...props} data-collapsed={collapsed ? 'true' : undefined}>
      <button
        type="button"
        className="answer-section-toggle"
        aria-expanded={!collapsed}
        onClick={() => setCollapsed(value => !value)}
      >
        <ChevronDown size={14} className={`answer-section-chevron ${collapsed ? 'collapsed' : ''}`} />
      </button>
      {children}
    </section>
  );
}
