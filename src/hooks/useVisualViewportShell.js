import { useEffect, useState } from 'react';

// iOS Safari keeps the layout viewport (and 100vh/100dvh) fixed when the on-screen
// keyboard opens instead of shrinking it - only the visual viewport shrinks. Without this,
// a fixed-height shell stays full-size and gets shifted up by the OS to keep the focused
// input visible, pushing content (e.g. a composer pinned to the shell's bottom) off the
// visible area. Pin the shell's height/top to window.visualViewport so it always tracks
// the space actually visible above the keyboard.
//
// Returns a state-backed callback ref (not a plain useRef) because the shell this attaches
// to is often only mounted after some async state resolves, and a plain ref wouldn't re-run
// the sizing effect when that DOM node actually appears.
export function useVisualViewportShell() {
  const [el, setEl] = useState(null);

  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv || !el) return undefined;
    const applyLayout = () => {
      el.style.height = `${vv.height}px`;
      el.style.top = `${vv.offsetTop}px`;
    };
    applyLayout();
    vv.addEventListener('resize', applyLayout);
    vv.addEventListener('scroll', applyLayout);
    return () => {
      vv.removeEventListener('resize', applyLayout);
      vv.removeEventListener('scroll', applyLayout);
      el.style.height = '';
      el.style.top = '';
    };
  }, [el]);

  return setEl;
}
