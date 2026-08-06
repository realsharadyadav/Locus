import { useEffect } from 'react';

// Wide tables and diagrams scroll horizontally inside their own box, but a plain
// `overflow-x: auto` gives no hint that there is more to see off to one side - on a phone,
// where there is no scrollbar to notice, that reads as the content being cut off rather than
// scrollable. This toggles `can-scroll-start`/`can-scroll-end` on the container so CSS can
// paint an edge shadow only on the side that actually has more content, and only while it does.
// `deps` re-attaches the observers when the container's content element is replaced rather than
// resized — a diagram re-rendered for a theme change is a brand new <svg>, and an observer left
// pointing at the discarded one never fires again.
export function useScrollEdgeShadows(ref, deps = []) {
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
      // The container's own box does not change when its contents outgrow it — scrollWidth does.
      // Watching the content element as well is what makes the shadow appear on a diagram that
      // was sized after mount (MermaidBlock writes the fitted width once it has measured).
      if (node.firstElementChild) observer.observe(node.firstElementChild);
    }
    return () => {
      node.removeEventListener('scroll', update);
      observer?.disconnect();
    };
  }, [ref, ...deps]);
}
