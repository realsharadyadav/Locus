import React, { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { AnswerSection } from './AnswerSection';
import { AnswerToc } from './AnswerToc';
import { CodeBlock } from './CodeBlock';
import ReactMarkdown from 'react-markdown';
import rehypeSlug from 'rehype-slug';
import remarkGfm from 'remark-gfm';
import { useScrollEdgeShadows } from '../hooks/useScrollEdgeShadows';
import { rehypeAnswerSections } from '../lib/rehypeAnswerSections';

// A named component (rather than the inline arrow function this replaced) so it can hold its
// own ref for the scroll-edge-shadow hook - a wide table needs to say which side still has more
// to scroll to, not just that it scrolls at all.
function TableScrollWrap(props) {
  const wrapRef = useRef(null);
  useScrollEdgeShadows(wrapRef);
  return (
    <div className="answer-table-wrap" ref={wrapRef}>
      <table {...props} />
    </div>
  );
}

export function AssistantMarkdown({ text, streaming, messageKey }) {
  const containerRef = useRef(null);
  const [headings, setHeadings] = useState([]);
  // components must stay referentially stable across re-renders (e.g. from chat-job
  // polling) — react-markdown remounts the code renderer whenever its identity changes,
  // which would restart any in-flight Mermaid render before it ever resolves. Any new
  // override belongs in this same memo for the same reason.
  const components = useMemo(
    () => ({
      code: props => <CodeBlock {...props} streaming={streaming} />,
      section: props => <AnswerSection {...props} />,
      // Wide tables must scroll inside their own box rather than stretching the chat bubble.
      // `node` is react-markdown's hast node and must not reach the DOM.
      table: ({ node, ...props }) => <TableScrollWrap {...props} />,
    }),
    [streaming],
  );
  // Sectioning is applied only once streaming settles: mid-stream the markdown is truncated, so
  // headings arrive before their content and sections would be rebuilt on every token. Mermaid
  // does not start rendering until streaming ends either, so the plugin set is stable for the
  // whole window where a remount would actually cost something.
  const rehypePlugins = useMemo(
    () => (streaming
      ? [[rehypeSlug, { prefix: `md-${messageKey}-` }]]
      : [[rehypeSlug, { prefix: `md-${messageKey}-` }], rehypeAnswerSections]),
    [messageKey, streaming],
  );

  useLayoutEffect(() => {
    if (streaming || !containerRef.current) return;
    const nodes = containerRef.current.querySelectorAll('h1[id], h2[id], h3[id]');
    setHeadings(Array.from(nodes).map(node => ({ id: node.id, level: Number(node.tagName[1]), text: node.textContent })));
  }, [streaming, text]);

  return (
    <div ref={containerRef}>
      {!streaming && <AnswerToc headings={headings} />}
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={rehypePlugins} components={components}>{text || ' '}</ReactMarkdown>
    </div>
  );
}
