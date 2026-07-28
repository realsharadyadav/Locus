import React, { useState } from 'react';
import {
  Check, Code2, Copy, Maximize2,
} from 'lucide-react';
import { useMermaidRender } from '../lib/mermaid';
import { DiagramLightbox } from './DiagramLightbox';

export function MermaidBlock({ code }) {
  const [copied, setCopied] = useState(false);
  const [showSource, setShowSource] = useState(false);
  const [zoomed, setZoomed] = useState(false);
  const { svg, error } = useMermaidRender(code);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="code-block mermaid-block">
      <div className="code-block-toolbar">
        <span className="code-block-lang">diagram</span>
        <div className="code-block-actions">
          {svg && !showSource && (
            <button type="button" className="code-block-action" onClick={() => setZoomed(true)} title="Expand diagram">
              <Maximize2 size={12} />
            </button>
          )}
          <button type="button" className="code-block-action" onClick={() => setShowSource(value => !value)} title={showSource ? 'Show diagram' : 'View source'}>
            <Code2 size={12} />
          </button>
          <button type="button" className="code-block-action" onClick={handleCopy} title="Copy source">
            {copied ? <Check size={12} /> : <Copy size={12} />}
          </button>
        </div>
      </div>
      {showSource ? (
        <pre><code>{code}</code></pre>
      ) : error ? (
        <div className="mermaid-error">
          <p className="mermaid-error-message">Couldn't render this diagram: {error}</p>
          <pre><code>{code}</code></pre>
        </div>
      ) : svg ? (
        <div className="mermaid-canvas mermaid-canvas-zoomable" onClick={() => setZoomed(true)} dangerouslySetInnerHTML={{ __html: svg }} />
      ) : (
        <div className="mermaid-loading">Rendering diagram…</div>
      )}
      {zoomed && svg && <DiagramLightbox svg={svg} onClose={() => setZoomed(false)} />}
    </div>
  );
}
