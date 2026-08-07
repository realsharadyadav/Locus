import React, { useState } from 'react';
import {
  Check, Copy, Download,
} from 'lucide-react';
import { useHighlightedCode } from '../lib/highlight';
import { MermaidBlock } from './MermaidBlock';

export const CODE_FILE_EXTENSIONS = {
  html: 'html', htm: 'html', xml: 'xml', svg: 'svg',
  javascript: 'js', js: 'js', jsx: 'jsx', typescript: 'ts', ts: 'ts', tsx: 'tsx',
  python: 'py', py: 'py', json: 'json', css: 'css', scss: 'scss',
  bash: 'sh', sh: 'sh', shell: 'sh', zsh: 'sh',
  yaml: 'yaml', yml: 'yaml', sql: 'sql', java: 'java', c: 'c', cpp: 'cpp', 'c++': 'cpp',
  go: 'go', rust: 'rs', rb: 'rb', ruby: 'rb', php: 'php', markdown: 'md', md: 'md',
};

export const LANGUAGE_ACCENT_COLORS = {
  javascript: '#f0db4f', js: '#f0db4f', jsx: '#f0db4f',
  typescript: '#3178c6', ts: '#3178c6', tsx: '#3178c6',
  python: '#ffd43b', py: '#ffd43b',
  json: '#8bc34a', css: '#42a5f5', scss: '#c06ed6',
  bash: '#8bc9a8', sh: '#8bc9a8', shell: '#8bc9a8', zsh: '#8bc9a8',
  yaml: '#e08ec2', yml: '#e08ec2', sql: '#ff9e64',
  java: '#ea9d5a', c: '#7aa2f7', cpp: '#7aa2f7', 'c++': '#7aa2f7',
  go: '#5bc8af', rust: '#dd8866', ruby: '#e0605b', php: '#8892c7',
  html: '#e0714f', xml: '#e0714f', markdown: '#9aa5ce', md: '#9aa5ce',
};

export function CodeBlock({ className, children, streaming }) {
  const [copied, setCopied] = useState(false);
  const match = /language-(\w+)/.exec(className || '');
  const language = match ? match[1].toLowerCase() : '';
  const codeText = String(children).replace(/\n$/, '');
  const isMermaid = language === 'mermaid';
  const highlighted = useHighlightedCode(match && !isMermaid ? codeText : '', language);

  if (!match) {
    return <code className={className}>{children}</code>;
  }

  if (isMermaid) {
    if (streaming) {
      // A full-height dump of raw Mermaid syntax here would collapse into the much shorter
      // rendered diagram the instant streaming ends — a code block full of "flowchart LR" and
      // node ids folding down into a small figure reads as a pop, not a reveal. Showing the same
      // placeholder MermaidBlock itself uses keeps that transition to one step instead of two:
      // the identical DOM means the placeholder simply resizes into the diagram once.
      return (
        <div className="code-block mermaid-block mermaid-block-pending">
          <div className="code-block-toolbar"><span className="code-block-lang">diagram</span></div>
          <div className="mermaid-loading">Rendering diagram…</div>
        </div>
      );
    }
    return <MermaidBlock code={codeText} />;
  }

  const handleCopy = async () => {
    await navigator.clipboard.writeText(codeText);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  const handleDownload = () => {
    const extension = CODE_FILE_EXTENSIONS[language] || 'txt';
    const blob = new Blob([codeText], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `snippet.${extension}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="code-block">
      <div className="code-block-toolbar">
        <span className="code-block-lang">
          <span className="code-block-lang-dot" style={{ background: LANGUAGE_ACCENT_COLORS[language] || '#8b95a5' }} aria-hidden="true" />
          {language}
        </span>
        <div className="code-block-actions">
          <button type="button" className="code-block-action" onClick={handleCopy} title="Copy code">
            {copied ? <Check size={12} /> : <Copy size={12} />}
          </button>
          <button type="button" className="code-block-action" onClick={handleDownload} title="Download as file">
            <Download size={12} />
          </button>
        </div>
      </div>
      {highlighted != null ? (
        <pre><code className={`hljs language-${language}`} dangerouslySetInnerHTML={{ __html: highlighted }} /></pre>
      ) : (
        <pre><code className={className}>{children}</code></pre>
      )}
    </div>
  );
}
