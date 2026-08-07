import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  Minus, Plus, RotateCcw, X,
} from 'lucide-react';
import { createPortal } from 'react-dom';

// Past 6x even a freshly re-rendered label is more magnified than useful, and below half size
// there's nothing worth seeing that fitDiagram() didn't already show inline.
const MIN_SCALE = 0.5;
const MAX_SCALE = 6;

const DOUBLE_TAP_MS = 300;
const DOUBLE_TAP_DIST = 24;

// A CSS transform never re-rasterizes an SVG: the browser composites the texture it already
// rasterized at the element's layout size, so scaling the wrapper up just stretches that bitmap —
// Mermaid's HTML labels (flowchart htmlLabels) are the first things to turn into blurry pixels.
// Zoom is therefore implemented by growing the SVG's own width, which makes the browser lay the
// whole diagram (labels included) out again at the new resolution, and the pan is real scrolling:
// the canvas is an overflow:auto flex container and the content is a margin:auto flex item, so
// a fitting diagram sits centred while an overflowing one scrolls from its top-left edge with
// native trackpad/wheel/touch momentum and desktop scrollbars. Crisp at every zoom level, and
// there is no giant composited layer for the GPU to drag around — which was the scroll-stutter
// on mobile.
function parseViewBox(svgString) {
  const match = /viewBox="([\d.\s-]+)"/.exec(svgString || '');
  if (!match) return null;
  const parts = match[1].trim().split(/\s+/).map(Number);
  if (parts.length < 4) return null;
  const w = parts[2];
  const h = parts[3];
  if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) return null;
  return { w, h };
}

function ZoomReadout({ zoom }) {
  return <span className="diagram-lightbox-zoom">{zoom}%</span>;
}

function LightboxToolbar({ title, zoom, onClose, onZoomIn, onZoomOut, onReset }) {
  return (
    <div className="diagram-lightbox-toolbar" onClick={event => event.stopPropagation()}>
      {title && <span className="diagram-lightbox-title">{title}</span>}
      <ZoomReadout zoom={zoom} />
      <button type="button" className="diagram-lightbox-action" onClick={onZoomOut} title="Zoom out" aria-label="Zoom out">
        <Minus size={16} />
      </button>
      <button type="button" className="diagram-lightbox-action" onClick={onZoomIn} title="Zoom in" aria-label="Zoom in">
        <Plus size={16} />
      </button>
      <button type="button" className="diagram-lightbox-action" onClick={onReset} title="Reset zoom" aria-label="Reset zoom">
        <RotateCcw size={15} />
      </button>
      <button type="button" className="diagram-lightbox-action" onClick={onClose} title="Close" aria-label="Close">
        <X size={17} />
      </button>
    </div>
  );
}

export function DiagramLightbox({ svg, title, onClose }) {
  const canvasRef = useRef(null);
  const svgHolderRef = useRef(null);
  const [ready, setReady] = useState(false);
  // Live transform, held in a ref so gesture frames never round-trip React; the zoom readout is
  // throttled through an animation frame so it tracks a pinch without forcing a render each move.
  const transformRef = useRef({ scale: 1, x: 0, y: 0 });
  const baseRef = useRef({ w: 0, h: 0 });
  const lastWidthRef = useRef(0);
  const readoutFrame = useRef(0);
  const pointersRef = useRef(new Map());
  const pinchRef = useRef(null);
  const pointerDownRef = useRef(null);
  const lastTapRef = useRef(null);

  const [zoom, setZoom] = useState(100);

  const canvasPoint = (clientX, clientY) => {
    const rect = canvasRef.current.getBoundingClientRect();
    return { x: clientX - rect.left, y: clientY - rect.top };
  };

  // Pan positions live in the canvas scroll offsets, so "clamping" means keeping them inside the
  // scrollable range: 0..(content - viewport) when the diagram overflows, and 0 when it fits (the
  // margin:auto flex item then centres itself).
  const clampPan = (x, y) => {
    const canvas = canvasRef.current;
    const w = baseRef.current.w * transformRef.current.scale;
    const h = baseRef.current.h * transformRef.current.scale;
    const cw = canvas.clientWidth;
    const ch = canvas.clientHeight;
    const cx = w > cw ? Math.min(Math.max(0, x), w - cw) : 0;
    const cy = h > ch ? Math.min(Math.max(0, y), h - ch) : 0;
    return { x: cx, y: cy };
  };

  const applyTransform = () => {
    // Write the width before the scroll offsets: reading the canvas size forces a layout flush,
    // so the scroll range below always reflects the just-grown diagram.
    const t = transformRef.current;
    const svgEl = svgHolderRef.current?.querySelector('svg');
    const w = baseRef.current.w * t.scale;
    if (svgEl && w > 0 && w !== lastWidthRef.current) {
      svgEl.style.width = `${w}px`;
      svgEl.style.height = 'auto';
      lastWidthRef.current = w;
    }
    const canvas = canvasRef.current;
    if (canvas) {
      canvas.scrollLeft = t.x;
      canvas.scrollTop = t.y;
    }
    if (readoutFrame.current) return;
    readoutFrame.current = window.requestAnimationFrame(() => {
      readoutFrame.current = 0;
      setZoom(Math.round(transformRef.current.scale * 100));
    });
  };

  // Zoom about a canvas-local focal point. Scroll semantics: the content-local feature under the
  // focal sits at (focal + scroll) / scale; after growing to the next scale it must land back
  // under the focal, so the new scroll is feature * next - focal. A browser may clamp the scroll
  // to the current range, so clampPan runs after the scale is set and normalises the position.
  const scaleTo = (next, fx, fy) => {
    const t = transformRef.current;
    next = Math.min(MAX_SCALE, Math.max(MIN_SCALE, next));
    if (next === t.scale) return;
    const px = (fx + t.x) / t.scale;
    const py = (fy + t.y) / t.scale;
    t.scale = next;
    const clamped = clampPan(px * next - fx, py * next - fy);
    t.x = clamped.x;
    t.y = clamped.y;
    applyTransform();
  };

  const zoomAt = (factor, fx, fy) => {
    const t = transformRef.current;
    scaleTo(t.scale * factor, fx, fy);
  };

  // Fit the whole diagram into the viewport at scale 1, then centre it. Runs before the first
  // paint, so the opening frame is already the centred one — no top-left-corner blink.
  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    const svgEl = svgHolderRef.current?.querySelector('svg');
    if (!canvas || !svgEl) return;
    const natural = parseViewBox(svg);
    if (!natural) {
      setReady(true);
      return;
    }
    const margin = 48;
    const fit = Math.min(1, (canvas.clientWidth - margin) / natural.w, (canvas.clientHeight - margin) / natural.h);
    const baseW = Math.max(1, natural.w * fit);
    const baseH = Math.max(1, natural.h * fit);
    baseRef.current = { w: baseW, h: baseH };
    const t = transformRef.current;
    t.scale = 1;
    t.x = 0;
    t.y = 0;
    applyTransform();
    setReady(true);
  }, [svg]);

  const handlePointerDown = event => {
    canvasRef.current?.setPointerCapture?.(event.pointerId);
    pointersRef.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    pointerDownRef.current = {
      x: event.clientX,
      y: event.clientY,
      target: event.target,
    };
    if (pointersRef.current.size === 2) {
      const [a, b] = [...pointersRef.current.values()];
      const mid = canvasPoint((a.x + b.x) / 2, (a.y + b.y) / 2);
      pinchRef.current = {
        dist: Math.hypot(b.x - a.x, b.y - a.y),
        cx: mid.x,
        cy: mid.y,
      };
    }
  };

  const handlePointerMove = event => {
    const pointers = pointersRef.current;
    if (!pointers.has(event.pointerId)) return;
    const prev = pointers.get(event.pointerId);
    const cur = { x: event.clientX, y: event.clientY };
    pointers.set(event.pointerId, cur);

    if (pointers.size === 1) {
      // A touch is already scrolling natively (touch-action: pan-x pan-y, so it keeps momentum);
      // double-scrolling it here too is what makes a drag jitter. Programmatic drag-pan is only
      // for the mouse, which the browser never scrolls.
      if (event.pointerType !== 'touch') {
        const t = transformRef.current;
        // Dragging the content with the pointer: moving it right must push the scroll back.
        const clamped = clampPan(t.x - (cur.x - prev.x), t.y - (cur.y - prev.y));
        t.x = clamped.x;
        t.y = clamped.y;
        applyTransform();
      }
    } else if (pointers.size === 2 && pinchRef.current) {
      const [a, b] = [...pointers.values()];
      const dist = Math.hypot(b.x - a.x, b.y - a.y);
      const mid = canvasPoint((a.x + b.x) / 2, (a.y + b.y) / 2);
      const p = pinchRef.current;
      if (dist > 0 && p.dist > 0) {
        const t = transformRef.current;
        scaleTo(t.scale * (dist / p.dist), mid.x, mid.y);
      }
      // Re-anchor to this frame so only the delta between frames counts — anchoring to the gesture
      // start every frame is what makes a pinch drift.
      pinchRef.current = { dist, cx: mid.x, cy: mid.y };
    }
  };

  const handlePointerUp = event => {
    const pointers = pointersRef.current;
    const wasPinching = pointers.size === 2;
    const down = pointerDownRef.current;
    if (!wasPinching && down) {
      const moved = Math.hypot(event.clientX - down.x, event.clientY - down.y);
      if (moved < DOUBLE_TAP_DIST) {
        if (down.target === canvasRef.current) {
          // A clean tap on the empty margin is "close"; a tap on the diagram itself is not.
          onClose();
        } else {
          // Double-tap zooms in from 1x (about the tap point) and resets once magnified.
          const last = lastTapRef.current;
          const now = performance.now();
          const p = canvasPoint(event.clientX, event.clientY);
          if (last && now - last.t < DOUBLE_TAP_MS) {
            lastTapRef.current = null;
            if (transformRef.current.scale > 1.25) {
              const t = transformRef.current;
              t.scale = 1;
              t.x = 0;
              t.y = 0;
              applyTransform();
            } else {
              zoomAt(2.5, p.x, p.y);
            }
          } else {
            lastTapRef.current = { x: event.clientX, y: event.clientY, t: now };
          }
        }
      }
    }
    pointers.delete(event.pointerId);
    if (pointers.size < 2) pinchRef.current = null;
    pointerDownRef.current = null;
  };

  // A cancelled pointer (browser takes the gesture over, pointer capture lost, etc.) must clean
  // up the same bookkeeping but must never be treated as a tap — a cancel is not a "close" or a
  // double-tap, and closing the lightbox mid-gesture is exactly the kind of jump a cancel causes.
  const handlePointerCancel = event => {
    pointersRef.current.delete(event.pointerId);
    if (pointersRef.current.size < 2) pinchRef.current = null;
    pointerDownRef.current = null;
  };

  const zoomIn = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    zoomAt(1.4, canvas.clientWidth / 2, canvas.clientHeight / 2);
  };

  const zoomOut = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    zoomAt(1 / 1.4, canvas.clientWidth / 2, canvas.clientHeight / 2);
  };

  const resetTransform = () => {
    const t = transformRef.current;
    t.scale = 1;
    t.x = 0;
    t.y = 0;
    applyTransform();
  };

  useEffect(() => {
    const handleKey = event => {
      if (event.key === 'Escape') onClose();
      if (event.key === '0') resetTransform();
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [onClose]);

  // Plain wheel/trackpad scrolling pans the diagram natively (it is a real scroll container now).
  // Ctrl/Cmd+wheel zooms about the cursor — and a trackpad pinch is delivered as exactly that
  // ctrl+wheel sequence by Chrome and Safari, so pinch-to-zoom works on laptops too. Attached
  // manually (not via React's onWheel) because the zoom branch must be non-passive: without
  // preventDefault the browser would pinch-zoom the page behind the lightbox instead.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const onWheel = event => {
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        const p = canvasPoint(event.clientX, event.clientY);
        scaleTo(transformRef.current.scale * Math.exp(-event.deltaY * 0.0025), p.x, p.y);
      }
    };
    canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', onWheel);
  }, []);

  // A pinch on the diagram must not also scroll or zoom the page behind the overlay.
  useEffect(() => {
    const { body } = document;
    const previous = body.style.overflow;
    body.style.overflow = 'hidden';
    return () => { body.style.overflow = previous; };
  }, []);

  return createPortal(
    <div className="diagram-lightbox">
      <LightboxToolbar title={title} zoom={zoom} onClose={onClose} onZoomIn={zoomIn} onZoomOut={zoomOut} onReset={resetTransform} />
      <div
        ref={canvasRef}
        className={`diagram-lightbox-canvas${ready ? ' is-ready' : ''}`}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerCancel}
      >
        <div className="diagram-lightbox-content">
          <div ref={svgHolderRef} dangerouslySetInnerHTML={{ __html: svg }} />
        </div>
      </div>
    </div>,
    document.body,
  );
}
