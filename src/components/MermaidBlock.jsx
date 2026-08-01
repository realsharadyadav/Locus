import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Check, Code2, Copy, Maximize2,
} from 'lucide-react';
import { useScrollEdgeShadows } from '../hooks/useScrollEdgeShadows';
import { naturalDiagramWidth, useMermaidRender } from '../lib/mermaid';
import { readMermaidMeta } from '../lib/mermaidMeta';
import { DiagramLightbox } from './DiagramLightbox';

// Below roughly 70% of the size Mermaid laid the diagram out at, node labels stop being readable.
// A wide flowchart squeezed into a phone lands near 17%, which is why fitting to width alone turns
// diagrams into smudges.
const MIN_LEGIBLE_SCALE = 0.7;

export function MermaidBlock({ code }) {
  const [copied, setCopied] = useState(false);
  const [showSource, setShowSource] = useState(false);
  const [zoomed, setZoomed] = useState(false);
  const { svg, error } = useMermaidRender(code);
  const { title, legend } = useMemo(() => readMermaidMeta(code), [code]);
  const canvasRef = useRef(null);
  useScrollEdgeShadows(canvasRef);

  // Mermaid draws a frontmatter title into the SVG itself. The figure caption already shows it —
  // pinned, styled, and outside the scroll area, which a centred in-SVG title is not on a wide
  // diagram — so the drawn one is removed and the vertical band it occupied is reclaimed by
  // trimming the viewBox. Naturally idempotent: once removed there is nothing left to match.
  const dropDrawnTitle = svgElement => {
    const drawn = svgElement.querySelector('[class*="TitleText"]');
    const viewBox = svgElement.viewBox?.baseVal;
    if (!drawn || !viewBox || !viewBox.height) return;
    let band = 0;
    try {
      const bounds = drawn.getBBox();
      band = bounds.y + bounds.height - viewBox.y;
    } catch {
      band = 0;
    }
    drawn.remove();
    // Guard against a malformed box swallowing the diagram along with the title.
    if (band > 0 && band < viewBox.height * 0.6) {
      svgElement.setAttribute('viewBox', `${viewBox.x} ${viewBox.y + band} ${viewBox.width} ${viewBox.height - band}`);
    }
  };

  // Scale the diagram down to fit its container, but stop at the legibility floor and let the
  // container scroll from there. Narrow diagrams fit exactly; wide ones stay readable and pan.
  const fitDiagram = useCallback(() => {
    const canvas = canvasRef.current;
    const svgElement = canvas?.querySelector('svg');
    if (!canvas || !svgElement) return;
    dropDrawnTitle(svgElement);
    const natural = naturalDiagramWidth(svgElement);
    if (!natural) return;
    const style = window.getComputedStyle(canvas);
    const available = canvas.clientWidth - parseFloat(style.paddingLeft || 0) - parseFloat(style.paddingRight || 0);
    if (available <= 0) return;
    // Never enlarge past the natural size — an upscaled diagram is blurry text, not more detail.
    const scale = Math.min(1, Math.max(available / natural, MIN_LEGIBLE_SCALE));
    svgElement.style.width = `${Math.round(natural * scale)}px`;
    svgElement.style.maxWidth = 'none';
    svgElement.style.height = 'auto';
  }, []);

  useEffect(() => {
    if (!svg || showSource) return undefined;
    fitDiagram();
    const canvas = canvasRef.current;
    if (!canvas || typeof ResizeObserver === 'undefined') return undefined;
    // Rotating the phone or opening the sidebar changes the available width.
    const observer = new ResizeObserver(fitDiagram);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [svg, showSource, fitDiagram]);

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
        <figure className="mermaid-figure">
          {title && <figcaption className="mermaid-figure-title">{title}</figcaption>}
          <div ref={canvasRef} className="mermaid-canvas mermaid-canvas-zoomable" onClick={() => setZoomed(true)} dangerouslySetInnerHTML={{ __html: svg }} />
          {legend.length > 0 && (
            <ul className="mermaid-legend">
              {legend.map(entry => (
                <li key={entry.name} className="mermaid-legend-item">
                  <span className="mermaid-legend-swatch" style={{ background: entry.fill, borderColor: entry.stroke }} />
                  {entry.label}
                </li>
              ))}
            </ul>
          )}
          <p className="mermaid-figure-hint">Tap to expand · pinch to zoom</p>
        </figure>
      ) : (
        <div className="mermaid-loading">Rendering diagram…</div>
      )}
      {zoomed && svg && <DiagramLightbox svg={svg} title={title} onClose={() => setZoomed(false)} />}
    </div>
  );
}
