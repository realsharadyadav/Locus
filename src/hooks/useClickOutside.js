import { useEffect, useRef } from 'react';

/**
 * Dismiss a popover when the pointer goes down outside it, or on Escape.
 *
 * Returns a ref to attach to the popover's outermost element. Listeners are
 * only bound while `active` is true, so closed menus cost nothing.
 */
export function useClickOutside(active, onDismiss) {
  const ref = useRef(null);
  const handlerRef = useRef(onDismiss);
  handlerRef.current = onDismiss;

  useEffect(() => {
    if (!active) return undefined;

    const dismissOnPointer = event => {
      if (ref.current && !ref.current.contains(event.target)) handlerRef.current(event);
    };
    const dismissOnEscape = event => {
      if (event.key === 'Escape') handlerRef.current(event);
    };

    window.addEventListener('mousedown', dismissOnPointer);
    window.addEventListener('touchstart', dismissOnPointer);
    window.addEventListener('keydown', dismissOnEscape);
    return () => {
      window.removeEventListener('mousedown', dismissOnPointer);
      window.removeEventListener('touchstart', dismissOnPointer);
      window.removeEventListener('keydown', dismissOnEscape);
    };
  }, [active]);

  return ref;
}
