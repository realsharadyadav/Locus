import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Minus, Plus, RotateCcw, X,
} from 'lucide-react';
import { createPortal } from 'react-dom';

const MIN_SCALE = 0.5;
const MAX_SCALE = 6;
const DOUBLE_TAP_SCALE = 2.2;

const clampScale = value => Math.min(MAX_SCALE, Math.max(MIN_SCALE, value));

export function DiagramLightbox({ svg, title, onClose }) {
  const [transform, setTransform] = useState({ scale: 1, x: 0, y: 0 });
  const canvasRef = useRef(null);
  // Every pointer currently down, keyed by pointerId — one entry is a drag, two is a pinch.
  const pointersRef = useRef(new Map());
  const dragRef = useRef(null);
  const pinchRef = useRef(null);
  const lastTapRef = useRef(0);

  useEffect(() => {
    const handleKey = event => {
      if (event.key === 'Escape') onClose();
      if (event.key === '0') setTransform({ scale: 1, x: 0, y: 0 });
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [onClose]);

  // A pinch on the diagram must not also scroll or zoom the page behind the overlay.
  useEffect(() => {
    const { body } = document;
    const previous = body.style.overflow;
    body.style.overflow = 'hidden';
    return () => { body.style.overflow = previous; };
  }, []);

  // The app deliberately leaves browser page-zoom enabled (disabling it globally is an
  // accessibility regression), so this surface has to claim its own two-finger gesture.
  // `touch-action: none` on the canvas is what does that, and is verified sufficient in Chromium.
  // This non-passive touchmove is a belt-and-braces guard for engines where a fixed overlay can
  // still rubber-band the page underneath; React attaches touch listeners passively, so it has
  // to be bound directly on the node.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const swallow = event => { if (event.cancelable) event.preventDefault(); };
    canvas.addEventListener('touchmove', swallow, { passive: false });
    return () => canvas.removeEventListener('touchmove', swallow);
  }, []);

  /** Scale about a fixed screen point so the content under the fingers stays under the fingers. */
  const zoomAround = useCallback((nextScale, clientX, clientY) => {
    const bounds = canvasRef.current?.getBoundingClientRect();
    setTransform(current => {
      const scale = clampScale(nextScale);
      if (!bounds) return { ...current, scale };
      // Offset of the focal point from the canvas centre, which is where the untransformed
      // content sits — the translation has to absorb the change in magnification about it.
      const focusX = clientX - bounds.left - bounds.width / 2;
      const focusY = clientY - bounds.top - bounds.height / 2;
      const ratio = scale / current.scale;
      return {
        scale,
        x: focusX - (focusX - current.x) * ratio,
        y: focusY - (focusY - current.y) * ratio,
      };
    });
  }, []);

  // The +/- buttons zoom about the middle of the viewport, so whatever the user panned to
  // stays in view instead of drifting back toward the diagram's centre.
  const zoomBy = useCallback(factor => {
    const bounds = canvasRef.current?.getBoundingClientRect();
    if (!bounds) {
      setTransform(current => ({ ...current, scale: clampScale(current.scale * factor) }));
      return;
    }
    zoomAround(transform.scale * factor, bounds.left + bounds.width / 2, bounds.top + bounds.height / 2);
  }, [transform.scale, zoomAround]);

  const reset = useCallback(() => setTransform({ scale: 1, x: 0, y: 0 }), []);

  // Wheel and trackpad pinch (which arrives as ctrlKey + wheel) both zoom about the cursor.
  const handleWheel = event => {
    event.preventDefault();
    const intensity = event.ctrlKey ? 0.01 : 0.0022;
    setTransform(current => {
      const next = clampScale(current.scale * Math.exp(-event.deltaY * intensity));
      const bounds = canvasRef.current?.getBoundingClientRect();
      if (!bounds) return { ...current, scale: next };
      const focusX = event.clientX - bounds.left - bounds.width / 2;
      const focusY = event.clientY - bounds.top - bounds.height / 2;
      const ratio = next / current.scale;
      return { scale: next, x: focusX - (focusX - current.x) * ratio, y: focusY - (focusY - current.y) * ratio };
    });
  };

  const pinchState = () => {
    const [first, second] = Array.from(pointersRef.current.values());
    const distance = Math.hypot(second.x - first.x, second.y - first.y);
    return { distance, centerX: (first.x + second.x) / 2, centerY: (first.y + second.y) / 2 };
  };

  const handlePointerDown = event => {
    event.currentTarget.setPointerCapture(event.pointerId);
    pointersRef.current.set(event.pointerId, { x: event.clientX, y: event.clientY });

    if (pointersRef.current.size === 2) {
      // A second finger converts an in-progress drag into a pinch.
      dragRef.current = null;
      const { distance, centerX, centerY } = pinchState();
      pinchRef.current = { startDistance: distance, startScale: transform.scale, centerX, centerY };
      return;
    }

    if (pointersRef.current.size === 1) {
      dragRef.current = { startX: event.clientX, startY: event.clientY, originX: transform.x, originY: transform.y };

      // Double-tap zooms in on the tapped point, and zooms back out if already magnified. Touch has
      // no dblclick contract worth relying on, so the interval is measured here.
      const now = Date.now();
      if (now - lastTapRef.current < 300) {
        lastTapRef.current = 0;
        dragRef.current = null;
        if (transform.scale > 1.05) reset();
        else zoomAround(DOUBLE_TAP_SCALE, event.clientX, event.clientY);
        return;
      }
      lastTapRef.current = now;
    }
  };

  const handlePointerMove = event => {
    if (!pointersRef.current.has(event.pointerId)) return;
    pointersRef.current.set(event.pointerId, { x: event.clientX, y: event.clientY });

    if (pointersRef.current.size >= 2 && pinchRef.current) {
      const { distance, centerX, centerY } = pinchState();
      const { startDistance, startScale } = pinchRef.current;
      if (startDistance > 0) zoomAround(startScale * (distance / startDistance), centerX, centerY);
      return;
    }

    if (!dragRef.current) return;
    const { startX, startY, originX, originY } = dragRef.current;
    setTransform(current => ({ ...current, x: originX + (event.clientX - startX), y: originY + (event.clientY - startY) }));
  };

  const releasePointer = event => {
    pointersRef.current.delete(event.pointerId);
    if (pointersRef.current.size < 2) pinchRef.current = null;
    if (pointersRef.current.size === 0) dragRef.current = null;
    else if (pointersRef.current.size === 1) {
      // Lifting one finger of a pinch resumes a drag from wherever the remaining one is.
      const [remaining] = Array.from(pointersRef.current.values());
      dragRef.current = { startX: remaining.x, startY: remaining.y, originX: transform.x, originY: transform.y };
    }
  };

  return createPortal(
    <div className="diagram-lightbox" onClick={onClose}>
      <div className="diagram-lightbox-toolbar" onClick={event => event.stopPropagation()}>
        {title && <span className="diagram-lightbox-title">{title}</span>}
        <span className="diagram-lightbox-zoom">{Math.round(transform.scale * 100)}%</span>
        <button type="button" className="diagram-lightbox-action" onClick={() => zoomBy(1 / 1.3)} title="Zoom out" aria-label="Zoom out">
          <Minus size={16} />
        </button>
        <button type="button" className="diagram-lightbox-action" onClick={() => zoomBy(1.3)} title="Zoom in" aria-label="Zoom in">
          <Plus size={16} />
        </button>
        <button type="button" className="diagram-lightbox-action" onClick={reset} title="Reset zoom" aria-label="Reset zoom">
          <RotateCcw size={15} />
        </button>
        <button type="button" className="diagram-lightbox-action" onClick={onClose} title="Close" aria-label="Close">
          <X size={17} />
        </button>
      </div>
      <div
        ref={canvasRef}
        className="diagram-lightbox-canvas"
        onClick={event => event.stopPropagation()}
        onWheel={handleWheel}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={releasePointer}
        onPointerCancel={releasePointer}
        // Ends a mouse drag that exits the window. Safe for touch: the leave events fired as the
        // content transforms under a finger target descendants, which this never sees.
        onPointerLeave={releasePointer}
      >
        <div
          className="diagram-lightbox-content"
          style={{ transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})` }}
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      </div>
    </div>,
    document.body,
  );
}
