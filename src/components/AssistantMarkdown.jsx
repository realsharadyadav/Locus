import React, { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { AnswerSection } from './AnswerSection';
import { AnswerToc } from './AnswerToc';
import { CodeBlock } from './CodeBlock';
import ReactMarkdown from 'react-markdown';
import rehypeSlug from 'rehype-slug';
import remarkGfm from 'remark-gfm';
import { rehypeAnswerSections } from '../lib/rehypeAnswerSections';

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
      table: ({ node, ...props }) => <div className="answer-table-wrap"><table {...props} /></div>,
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
