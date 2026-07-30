import React, { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { AnswerToc } from './AnswerToc';
import { CodeBlock } from './CodeBlock';
import ReactMarkdown from 'react-markdown';
import rehypeSlug from 'rehype-slug';
import remarkGfm from 'remark-gfm';

export function AssistantMarkdown({ text, streaming, messageKey }) {
  const containerRef = useRef(null);
  const [headings, setHeadings] = useState([]);
  // components must stay referentially stable across re-renders (e.g. from chat-job
  // polling) — react-markdown remounts the code renderer whenever its identity changes,
  // which would restart any in-flight Mermaid render before it ever resolves.
  const components = useMemo(
    () => ({ code: props => <CodeBlock {...props} streaming={streaming} /> }),
    [streaming],
  );
  const rehypePlugins = useMemo(() => [[rehypeSlug, { prefix: `md-${messageKey}-` }]], [messageKey]);

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
