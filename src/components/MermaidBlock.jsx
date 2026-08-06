import React, {
  useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState,
} from 'react';
import {
  Check, Code2, Copy, Maximize2,
} from 'lucide-react';
import { useScrollEdgeShadows } from '../hooks/useScrollEdgeShadows';
import { naturalDiagramWidth, reflowDiagramTopDown, useMermaidRender } from '../lib/mermaid';
import { readMermaidMeta } from '../lib/mermaidMeta';
import { DiagramLightbox } from './DiagramLightbox';

// Below roughly 70% of the size Mermaid laid the diagram out at, node labels stop being readable.
// A wide flowchart squeezed into a phone lands near 17%, which is why fitting to width alone turns
// diagrams into smudges.
const MIN_LEGIBLE_SCALE = 0.7;

// Matches the 640px breakpoint the diagram styles already use, so layout direction and chrome
// change together rather than at two different widths.
const NARROW_QUERY = '(max-width: 640px)';

function useNarrowViewport() {
  const [narrow, setNarrow] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(NARROW_QUERY).matches,
  );
  useEffect(() => {
    const query = window.matchMedia(NARROW_QUERY);
    const handleChange = event => setNarrow(event.matches);
    setNarrow(query.matches);
    query.addEventListener('change', handleChange);
    return () => query.removeEventListener('change', handleChange);
  }, []);
  return narrow;
}

export function MermaidBlock({ code }) {
  const [copied, setCopied] = useState(false);
  const [showSource, setShowSource] = useState(false);
  const [zoomed, setZoomed] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const narrow = useNarrowViewport();
  // Only what gets drawn is re-oriented. Copy and "view source" still hand back exactly what the
  // answer contained — a reader who copies a diagram on their phone and opens it on a laptop
  // should get the author's diagram, not a phone-shaped rewrite of it.
  const renderCode = useMemo(() => (narrow ? reflowDiagramTopDown(code) : code), [code, narrow]);
  const { svg, error } = useMermaidRender(renderCode);
  const { title, legend } = useMemo(() => readMermaidMeta(code), [code]);
  const canvasRef = useRef(null);
  // Width the diagram was last laid out against. Fitting writes an explicit pixel width onto the
  // SVG, which can make a horizontal scrollbar appear or disappear — that resizes the canvas and
  // wakes the ResizeObserver right back up. Re-fitting only when the *available width* actually
  // changed breaks that feedback loop, which is what made a freshly drawn diagram twitch.
  const lastFitRef = useRef(-1);
  useScrollEdgeShadows(canvasRef, [svg, showSource]);

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
    const style = window.getComputedStyle(canvas);
    const available = canvas.clientWidth - parseFloat(style.paddingLeft || 0) - parseFloat(style.paddingRight || 0);
    if (available <= 0) return;
    const alreadySized = Boolean(svgElement.style.width);
    if (alreadySized && Math.abs(available - lastFitRef.current) < 1 && canvas.dataset.fitted === 'true') return;
    dropDrawnTitle(svgElement);
    const natural = naturalDiagramWidth(svgElement);
    if (!natural) return;
    // Never enlarge past the natural size — an upscaled diagram is blurry text, not more detail.
    const scale = Math.min(1, Math.max(available / natural, MIN_LEGIBLE_SCALE));
    const width = Math.round(natural * scale);
    svgElement.style.width = `${width}px`;
    svgElement.style.maxWidth = 'none';
    svgElement.style.height = 'auto';
    lastFitRef.current = available;
    // Only now is the diagram at its final size. The canvas stays hidden until this flips, so the
    // first frame the user sees is the fitted one rather than Mermaid's own full-size layout.
    canvas.dataset.fitted = 'true';
    setOverflows(width > available + 1);
  }, []);

  // Layout effect, not effect: this runs after React writes the SVG into the canvas but before the
  // browser paints, so the unfitted size is never on screen for a frame.
  useLayoutEffect(() => {
    if (!svg || showSource) return undefined;
    lastFitRef.current = -1;
    if (canvasRef.current) delete canvasRef.current.dataset.fitted;
    fitDiagram();
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    // Rotating the phone or opening the sidebar changes the available width. Coalescing into an
    // animation frame keeps the measure-then-write pair out of the observer's own callback, which
    // is what otherwise trips the browser's "ResizeObserver loop" warning on the first fit.
    let frame = 0;
    let sizeObserver;
    if (typeof ResizeObserver !== 'undefined') {
      sizeObserver = new ResizeObserver(() => {
        if (frame) return;
        frame = window.requestAnimationFrame(() => {
          frame = 0;
          fitDiagram();
        });
      });
      sizeObserver.observe(canvas);
    }
    // Backstop for anything that resets the drawing after it has been fitted — Mermaid used to do
    // exactly that from inside a later render (see the render-id comment in lib/mermaid.js), and
    // the resulting jump back to full size is what read as a flicker. A MutationObserver callback
    // runs before the next paint, so the repair is invisible. Our own writes always leave a width
    // behind, which is what keeps this from reacting to itself.
    const contentObserver = new MutationObserver(() => {
      const svgElement = canvas.querySelector('svg');
      if (svgElement && !svgElement.style.width) fitDiagram();
    });
    contentObserver.observe(canvas, { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'viewBox'] });
    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      sizeObserver?.disconnect();
      contentObserver.disconnect();
    };
  }, [svg, showSource, fitDiagram]);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  // The inline canvas only scrolls (touch-action: pan-x pan-y in CSS) — pinch-zoom needs pan
  // bounds and a reset affordance that only make sense full-screen, and DiagramLightbox already
  // has all of that. Rather than duplicate it here, a second finger touching down on the inline
  // preview jumps straight into the lightbox mid-gesture, so "pinch to zoom" in the hint below is
  // never a dead gesture — it always does something, even though the zoom itself starts fresh.
  const handleCanvasTouchStart = event => {
    if (event.touches.length >= 2) setZoomed(true);
  };

  // Panning a wide diagram ends in a click on the canvas, which would otherwise throw the reader
  // into the lightbox every time they dragged the diagram sideways. Only a press that neither
  // moved the pointer nor scrolled the canvas counts as "tap to expand".
  const pressRef = useRef(null);
  const handleCanvasPointerDown = event => {
    pressRef.current = { x: event.clientX, y: event.clientY, scrollLeft: canvasRef.current?.scrollLeft ?? 0 };
  };
  const handleCanvasClick = event => {
    const press = pressRef.current;
    if (!press) return;
    const moved = Math.hypot(event.clientX - press.x, event.clientY - press.y) > 6;
    const scrolled = Math.abs((canvasRef.current?.scrollLeft ?? 0) - press.scrollLeft) > 2;
    if (moved || scrolled) return;
    setZoomed(true);
  };

  return (
    <div className="code-block mermaid-block">
      <div className="code-block-toolbar">
        <span className="code-block-lang">diagram</span>
        <div className="code-block-actions">
          {svg && !showSource && (
            <button type="button" className="code-block-action mermaid-expand-action" onClick={() => setZoomed(true)} title="Expand diagram">
              <Maximize2 size={12} />
              <span>Expand</span>
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
          <div
            ref={canvasRef}
            className="mermaid-canvas mermaid-canvas-zoomable"
            onPointerDown={handleCanvasPointerDown}
            onClick={handleCanvasClick}
            onTouchStart={handleCanvasTouchStart}
            dangerouslySetInnerHTML={{ __html: svg }}
          />
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
          {/* Says what this particular diagram can do: only a diagram too wide for its box can be
              dragged, and claiming otherwise sends readers hunting for a gesture that does nothing. */}
          <p className="mermaid-figure-hint">
            {overflows ? 'Drag sideways to pan · tap to expand' : 'Tap to expand · pinch to zoom'}
          </p>
        </figure>
      ) : (
        <div className="mermaid-loading">Rendering diagram…</div>
      )}
      {zoomed && svg && <DiagramLightbox svg={svg} title={title} onClose={() => setZoomed(false)} />}
    </div>
  );
}
