import { useEffect } from 'react';

// Wide tables and diagrams scroll horizontally inside their own box, but a plain
// `overflow-x: auto` gives no hint that there is more to see off to one side - on a phone,
// where there is no scrollbar to notice, that reads as the content being cut off rather than
// scrollable. This toggles `can-scroll-start`/`can-scroll-end` on the container so CSS can
// paint an edge shadow only on the side that actually has more content, and only while it does.
export function useScrollEdgeShadows(ref) {
  useEffect(() => {
    const node = ref.current;
    if (!node) return undefined;
    const update = () => {
      const max = node.scrollWidth - node.clientWidth;
      node.classList.toggle('can-scroll-start', node.scrollLeft > 2);
      node.classList.toggle('can-scroll-end', node.scrollLeft < max - 2);
    };
    update();
    node.addEventListener('scroll', update, { passive: true });
    let observer;
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(update);
      observer.observe(node);
    }
    return () => {
      node.removeEventListener('scroll', update);
      observer?.disconnect();
    };
  }, [ref]);
}
