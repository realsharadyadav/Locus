import React, { useEffect, useRef, useState } from 'react';
import {
  Minus, Plus, RotateCcw, X,
} from 'lucide-react';
import { createPortal } from 'react-dom';
import {
  TransformWrapper, TransformComponent, useControls, useTransformEffect,
} from 'react-zoom-pan-pinch';

// Same range the hand-rolled version used: past 6x a Mermaid label is just blurry pixels, and
// there's nothing below half size worth seeing that fitDiagram() didn't already show inline.
const MIN_SCALE = 0.5;
const MAX_SCALE = 6;

// The zoom percentage in the toolbar needs the live transform state, which only exists inside
// TransformWrapper's context - useTransformEffect fires on every frame of an in-progress gesture
// without going through the rest of the toolbar's render, so the readout tracks a pinch smoothly
// instead of lagging a state update made elsewhere.
function ZoomReadout() {
  const [percent, setPercent] = useState(100);
  useTransformEffect(({ state }) => setPercent(Math.round(state.scale * 100)));
  return <span className="diagram-lightbox-zoom">{percent}%</span>;
}

function LightboxToolbar({ title, onClose }) {
  const { zoomIn, zoomOut, resetTransform } = useControls();
  return (
    <div className="diagram-lightbox-toolbar" onClick={event => event.stopPropagation()}>
      {title && <span className="diagram-lightbox-title">{title}</span>}
      <ZoomReadout />
      <button type="button" className="diagram-lightbox-action" onClick={() => zoomOut()} title="Zoom out" aria-label="Zoom out">
        <Minus size={16} />
      </button>
      <button type="button" className="diagram-lightbox-action" onClick={() => zoomIn()} title="Zoom in" aria-label="Zoom in">
        <Plus size={16} />
      </button>
      <button type="button" className="diagram-lightbox-action" onClick={() => resetTransform()} title="Reset zoom" aria-label="Reset zoom">
        <RotateCcw size={15} />
      </button>
      <button type="button" className="diagram-lightbox-action" onClick={onClose} title="Close" aria-label="Close">
        <X size={17} />
      </button>
    </div>
  );
}

export function DiagramLightbox({ svg, title, onClose }) {
  // react-zoom-pan-pinch exposes zoomIn/zoomOut/resetTransform on this ref, which is how the
  // "0 to reset" shortcut reaches it from outside the toolbar's own component tree.
  const transformRef = useRef(null);
  // centerOnInit repositions the content a moment after its first paint (it needs a measured
  // size first), which without this would show one frame pinned to the top-left corner before
  // jumping to centre - exactly the "blink" a hand-rolled version wouldn't have had either.
  // Staying invisible until onInit fires (which runs after that repositioning) skips straight to
  // the centred frame instead of ever painting the wrong one.
  const [ready, setReady] = useState(false);
  // A drag that starts on the empty margin is a legitimate pan, not a request to close - the
  // pointer's own down-vs-click distance is what decides that, independent of the library's pan
  // gesture recognition (which has its own threshold/timing and isn't meant for this).
  const pointerDownRef = useRef(null);

  useEffect(() => {
    const handleKey = event => {
      if (event.key === 'Escape') onClose();
      if (event.key === '0') transformRef.current?.resetTransform();
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

  return createPortal(
    <div className="diagram-lightbox" onClick={onClose}>
      <TransformWrapper
        ref={transformRef}
        initialScale={1}
        minScale={MIN_SCALE}
        maxScale={MAX_SCALE}
        centerOnInit
        doubleClick={{ mode: 'toggle', step: 1 }}
        onInit={() => setReady(true)}
      >
        <LightboxToolbar title={title} onClose={onClose} />
        <TransformComponent
          wrapperClass={`diagram-lightbox-canvas${ready ? ' is-ready' : ''}`}
          contentClass="diagram-lightbox-content"
          wrapperStyle={{ width: '100%', height: '100%' }}
          // Closing on background click is the expected lightbox gesture, but only for the empty
          // margin around the diagram, and only when the pointer never actually moved between down
          // and up - a click that landed on the diagram itself (a descendant of the wrapper, not
          // the wrapper element itself), or that ends a drag which happened to start on the empty
          // margin, must not also close the box under it.
          wrapperProps={{
            onPointerDown: event => {
              pointerDownRef.current = { x: event.clientX, y: event.clientY };
            },
            onClick: event => {
              const down = pointerDownRef.current;
              const dragged = down && Math.hypot(event.clientX - down.x, event.clientY - down.y) > 5;
              if (dragged || event.target !== event.currentTarget) event.stopPropagation();
            },
          }}
        >
          <div dangerouslySetInnerHTML={{ __html: svg }} />
        </TransformComponent>
      </TransformWrapper>
    </div>,
    document.body,
  );
}
