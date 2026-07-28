import React, { useEffect, useState } from 'react';

export let highlighterPromise = null;
export function loadHighlighter() {
  if (!highlighterPromise) {
    highlighterPromise = Promise.all([
      import('highlight.js'),
      import('highlight.js/styles/atom-one-dark.css'),
    ]).then(([module]) => module.default);
  }
  return highlighterPromise;
}

export const HLJS_LANGUAGE_OVERRIDES = { jsx: 'javascript', tsx: 'typescript', 'c++': 'cpp', golang: 'go', vue: 'xml' };

export function useHighlightedCode(code, language) {
  const [html, setHtml] = useState(null);
  useEffect(() => {
    if (!code) {
      setHtml(null);
      return;
    }
    let cancelled = false;
    loadHighlighter()
      .then(hljs => {
        if (cancelled) return;
        const resolved = HLJS_LANGUAGE_OVERRIDES[language] || language;
        const result = hljs.getLanguage(resolved)
          ? hljs.highlight(code, { language: resolved, ignoreIllegals: true })
          : hljs.highlightAuto(code);
        setHtml(result.value);
      })
      .catch(() => { if (!cancelled) setHtml(null); });
    return () => { cancelled = true; };
  }, [code, language]);
  return html;
}
