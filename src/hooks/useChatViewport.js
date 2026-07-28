import { useEffect, useRef, useState } from 'react';

// Mobile browsers disagree about what happens when the on-screen keyboard opens.
//
// - iOS Safari keeps the layout viewport (and 100vh/100dvh) at full size and instead
//   scrolls the whole page up so the focused field clears the keyboard. A shell sized
//   with viewport units therefore stays too tall and its bottom-pinned composer ends up
//   underneath the keyboard.
// - Android Chrome only resizes the layout viewport when the page opts in with
//   `interactive-widget=resizes-content` (see index.html); otherwise it behaves like iOS.
// - Both keep `window.visualViewport` accurate, which is what we actually want to size to.
//
// So: while a chat surface is mounted we lock document scrolling and publish the visual
// viewport height as `--app-vh` (plus `--keyboard-inset` and a `data-keyboard` flag for
// styling). Chat shells size themselves off `--app-vh` and stay entirely on screen, which
// also removes the stray page-level vertical/horizontal scrolling those surfaces used to
// pick up from mismatched 100vh math.

const KEYBOARD_OPEN_THRESHOLD_PX = 120;
const REPIN_SETTLE_MS = 60;

// Guards against two surfaces briefly overlapping during a route swap - the outgoing
// component's cleanup must not strip the lock the incoming one just installed.
let lockCount = 0;

const readViewport = () => {
  const vv = window.visualViewport;
  if (!vv) return { height: window.innerHeight, keyboardInset: 0, scale: 1 };
  return {
    height: vv.height,
    keyboardInset: Math.max(0, window.innerHeight - vv.height - vv.offsetTop),
    scale: vv.scale || 1,
  };
};

export function useChatViewportLock(active = true) {
  useEffect(() => {
    if (!active) return undefined;
    const root = document.documentElement;
    const vv = window.visualViewport;
    lockCount += 1;
    root.classList.add('viewport-locked');

    let frame = 0;
    const apply = () => {
      frame = 0;
      const { height, keyboardInset, scale } = readViewport();
      root.style.setProperty('--app-vh', `${Math.round(height)}px`);
      root.style.setProperty('--keyboard-inset', `${Math.round(keyboardInset)}px`);
      root.dataset.keyboard = keyboardInset > KEYBOARD_OPEN_THRESHOLD_PX ? 'open' : 'closed';
      // Undo iOS's "scroll the page up to reveal the input" shift: the shell already
      // tracks the visual viewport, so that shift only pushes the composer out of sight.
      // Skip it while the user is pinch-zoomed, where panning the page is intentional.
      if (window.scrollY !== 0 && scale <= 1.01) window.scrollTo(0, 0);
    };
    const schedule = () => { if (!frame) frame = window.requestAnimationFrame(apply); };

    apply();
    vv?.addEventListener('resize', schedule);
    vv?.addEventListener('scroll', schedule);
    window.addEventListener('resize', schedule);
    window.addEventListener('orientationchange', schedule);

    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      vv?.removeEventListener('resize', schedule);
      vv?.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
      window.removeEventListener('orientationchange', schedule);
      lockCount = Math.max(0, lockCount - 1);
      if (lockCount > 0) return;
      root.classList.remove('viewport-locked');
      delete root.dataset.keyboard;
      root.style.removeProperty('--app-vh');
      root.style.removeProperty('--keyboard-inset');
    };
  }, [active]);
}

// Keeps a chat pinned to its newest message when the scroll *container* changes size:
// the keyboard opening, the device rotating, or the composer growing/shrinking a row as
// the textarea autosizes. use-stick-to-bottom's own ResizeObserver watches the *content*
// element, so none of these reach it - yet every one of them can leave the last message
// stranded behind the composer.
//
// The re-pin only fires if the user was already near the bottom, tracked on scroll: a
// resize must never yank someone who has deliberately scrolled back through history.
//
// Returns a state-backed callback ref rather than taking a ref object, because chat
// surfaces render a loading state first - a plain ref would still be null when the effect
// ran, and nothing would re-run it once the real container appeared.
export function useRepinOnResize(scrollToBottom, thresholdPx = 150) {
  const scrollToBottomRef = useRef(scrollToBottom);
  scrollToBottomRef.current = scrollToBottom;
  const [element, setElement] = useState(null);

  useEffect(() => {
    if (!element) return undefined;
    let nearBottom = true;
    let timer = 0;

    const measure = () => {
      nearBottom = element.scrollHeight - element.scrollTop - element.clientHeight <= thresholdPx;
    };
    measure();
    element.addEventListener('scroll', measure, { passive: true });

    // Deliberately trailing-edge. A container that *grows* makes the browser clamp
    // scrollTop, which use-stick-to-bottom reads (on a deferred handler) as the user
    // scrolling up, and it releases its stick-to-bottom lock. Correcting inside the
    // resize callback would just be undone a tick later, so wait for the library's own
    // bookkeeping to settle and re-assert the bottom after it.
    const repin = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => scrollToBottomRef.current?.({ animation: 'instant' }), REPIN_SETTLE_MS);
    };

    let observer;
    if (typeof ResizeObserver !== 'undefined') {
      let measured = false;
      observer = new ResizeObserver(() => {
        // Skip the observer's initial measurement callback.
        if (!measured) { measured = true; return; }
        if (nearBottom) repin();
      });
      observer.observe(element);
    }

    return () => {
      window.clearTimeout(timer);
      element.removeEventListener('scroll', measure);
      observer?.disconnect();
    };
  }, [element, thresholdPx]);

  return setElement;
}

// True when the visible area is too short to spend much of it on a composer - a phone
// with the keyboard up, or a small landscape window. Callers use it to cap how far the
// autosizing textarea is allowed to grow so the transcript stays readable.
export function useCompactViewport(maxHeightPx = 520) {
  const [compact, setCompact] = useState(() => (
    typeof window !== 'undefined'
    && (window.visualViewport?.height ?? window.innerHeight) < maxHeightPx
  ));

  useEffect(() => {
    const vv = window.visualViewport;
    const read = () => setCompact((vv?.height ?? window.innerHeight) < maxHeightPx);
    read();
    vv?.addEventListener('resize', read);
    window.addEventListener('resize', read);
    return () => {
      vv?.removeEventListener('resize', read);
      window.removeEventListener('resize', read);
    };
  }, [maxHeightPx]);

  return compact;
}
