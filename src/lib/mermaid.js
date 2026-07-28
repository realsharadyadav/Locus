import React, { useEffect, useRef, useState } from 'react';

export let mermaidModulePromise = null;
export function loadMermaid() {
  if (!mermaidModulePromise) mermaidModulePromise = import('mermaid').then(module => module.default);
  return mermaidModulePromise;
}

export function readMermaidTheme() {
  return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'neutral';
}

// LLMs frequently emit unquoted node labels like Ingress[Ingress Controller (NGINX/Traefik)] —
// Mermaid's grammar treats "(" right after "[" as the start of a different node shape, so the
// parser breaks on any punctuation inside a plain [label]. Auto-quoting is a safe, mechanical fix:
// a quoted label accepts arbitrary text, so this can only turn an invalid diagram valid, never the
// reverse. Only touched as a retry after the model's original syntax has already failed to render.
export function autoQuoteMermaidLabels(code) {
  return code.replace(/([A-Za-z_][\w-]*)\[([^[\]]*)\]/g, (match, id, content) => {
    const trimmed = content.trim();
    if (!trimmed || trimmed.startsWith('"')) return match;
    if (trimmed.startsWith('(') && trimmed.endsWith(')')) return match; // [(cylinder shape)]
    if (!/[()/\\{}|#;]/.test(trimmed)) return match;
    return `${id}["${trimmed.replace(/"/g, "'")}"]`;
  });
}

export function renameWholeWordOutsideQuotes(line, oldId, newId) {
  const quoted = [];
  const withoutQuotes = line.replace(/"[^"]*"/g, match => {
    quoted.push(match);
    return `\x00${quoted.length - 1}\x00`;
  });
  const renamed = withoutQuotes.replace(new RegExp(`\\b${oldId}\\b`, 'g'), newId);
  return renamed.replace(/\x00(\d+)\x00/g, (_, index) => quoted[Number(index)]);
}

// A subgraph id is itself a graph node, so a node inside it declared with the same id
// ("subgraph API[...]" containing "API[...]") makes that node its own parent — Mermaid
// rejects this as a cycle. Detect subgraph/node id collisions and rename the inner node,
// rewriting every bare reference to it (edges included) but never touching quoted label text
// or the subgraph's own id.
export function autoFixMermaidSubgraphCycles(code) {
  const lines = code.split('\n');
  const subgraphDeclareRegex = /^\s*subgraph\s+([A-Za-z_][\w-]*)/;
  const nodeDeclareRegex = /^\s*([A-Za-z_][\w-]*)\s*[[({]/;
  const stack = [];
  const renameMap = new Map();

  for (const line of lines) {
    const subgraphMatch = line.match(subgraphDeclareRegex);
    if (subgraphMatch) {
      stack.push(subgraphMatch[1]);
      continue;
    }
    if (/^\s*end\s*$/.test(line)) {
      stack.pop();
      continue;
    }
    const nodeMatch = line.match(nodeDeclareRegex);
    if (nodeMatch && stack.includes(nodeMatch[1]) && !renameMap.has(nodeMatch[1])) {
      renameMap.set(nodeMatch[1], `${nodeMatch[1]}Node`);
    }
  }

  if (renameMap.size === 0) return code;

  return lines
    .map(line => {
      const subgraphMatch = line.match(subgraphDeclareRegex);
      let result = line;
      for (const [oldId, newId] of renameMap) {
        if (subgraphMatch && subgraphMatch[1] === oldId) continue; // keep the subgraph's own id
        result = renameWholeWordOutsideQuotes(result, oldId, newId);
      }
      return result;
    })
    .join('\n');
}

export function repairMermaidCode(code) {
  return autoFixMermaidSubgraphCycles(autoQuoteMermaidLabels(code));
}

export let mermaidDiagramSeq = 0;

export function useMermaidRender(code) {
  const [result, setResult] = useState({ svg: null, error: null });
  const [themeTick, setThemeTick] = useState(0);
  const idRef = useRef(null);
  if (!idRef.current) idRef.current = `mermaid-diagram-${++mermaidDiagramSeq}`;

  useEffect(() => {
    const observer = new MutationObserver(() => setThemeTick(tick => tick + 1));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    loadMermaid()
      .then(async mermaid => {
        if (cancelled) return null;
        mermaid.initialize({ startOnLoad: false, theme: readMermaidTheme(), securityLevel: 'strict', fontFamily: 'inherit', suppressErrorRendering: true });
        try {
          return await mermaid.render(idRef.current, code);
        } catch (firstError) {
          const repaired = repairMermaidCode(code);
          if (repaired === code) throw firstError;
          try {
            return await mermaid.render(`${idRef.current}-repaired`, repaired);
          } catch {
            throw firstError;
          }
        }
      })
      .then(rendered => { if (!cancelled && rendered) setResult({ svg: rendered.svg, error: null }); })
      .catch(error => { if (!cancelled) setResult({ svg: null, error: error?.message || 'Invalid diagram syntax' }); });
    return () => { cancelled = true; };
  }, [code, themeTick]);

  return result;
}
