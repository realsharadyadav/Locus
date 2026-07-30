import React, { useEffect, useRef, useState } from 'react';
import {
  RotateCcw, X,
} from 'lucide-react';
import { createPortal } from 'react-dom';

export function DiagramLightbox({ svg, onClose }) {
  const [transform, setTransform] = useState({ scale: 1, x: 0, y: 0 });
  const dragRef = useRef(null);

  useEffect(() => {
    const handleKey = event => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [onClose]);

  const handleWheel = event => {
    event.preventDefault();
    setTransform(current => ({
      ...current,
      scale: Math.min(4, Math.max(0.5, current.scale * (event.deltaY < 0 ? 1.12 : 0.89))),
    }));
  };

  const handlePointerDown = event => {
    dragRef.current = { startX: event.clientX, startY: event.clientY, originX: transform.x, originY: transform.y };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const handlePointerMove = event => {
    if (!dragRef.current) return;
    const { startX, startY, originX, originY } = dragRef.current;
    setTransform(current => ({ ...current, x: originX + (event.clientX - startX), y: originY + (event.clientY - startY) }));
  };
  const stopDrag = () => { dragRef.current = null; };

  return createPortal(
    <div className="diagram-lightbox" onClick={onClose}>
      <div className="diagram-lightbox-toolbar" onClick={event => event.stopPropagation()}>
        <button type="button" className="diagram-lightbox-action" onClick={() => setTransform({ scale: 1, x: 0, y: 0 })} title="Reset zoom">
          <RotateCcw size={15} />
        </button>
        <button type="button" className="diagram-lightbox-action" onClick={onClose} title="Close">
          <X size={17} />
        </button>
      </div>
      <div
        className="diagram-lightbox-canvas"
        onClick={event => event.stopPropagation()}
        onWheel={handleWheel}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={stopDrag}
        onPointerLeave={stopDrag}
        onDoubleClick={() => setTransform({ scale: 1, x: 0, y: 0 })}
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
