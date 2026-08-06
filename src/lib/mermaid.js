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

// A left-to-right flowchart is the shape LLMs reach for by default, and it is the worst possible
// shape for a phone: nine nodes in a row means a 1500px-wide drawing, of which a 375px screen shows
// two. The same graph drawn top-down is narrow and tall — and vertical is the direction a phone has
// room in. Only the top-level direction is rewritten; a `direction LR` inside a subgraph keeps its
// row layout, which is what makes those groups readable in the first place.
export function reflowDiagramTopDown(code) {
  let done = false;
  return (code || '').replace(/^(\s*(?:flowchart|graph)[ \t]+)(LR|RL)\b/gim, (match, head) => {
    if (done) return match;
    done = true;
    return `${head}TD`;
  });
}

export function repairMermaidCode(code) {
  return autoFixMermaidSubgraphCycles(autoQuoteMermaidLabels(code));
}

export let mermaidDiagramSeq = 0;

/** Natural pixel width the diagram was laid out at, read from its viewBox. */
export function naturalDiagramWidth(svgElement) {
  const viewBox = svgElement?.getAttribute?.('viewBox');
  if (!viewBox) return 0;
  const width = Number(viewBox.trim().split(/\s+/)[2]);
  return Number.isFinite(width) && width > 0 ? width : 0;
}

// Every diagram Mermaid can render opens with one of these keywords (optionally after a
// frontmatter block or blank lines). CodeBlock already withholds a ```mermaid fence from
// MermaidBlock entirely until the whole message has finished streaming (see the
// `mermaid-block-pending` branch), so by the time code reaches here it is never a
// still-arriving partial chunk - a code block that doesn't start with one of these is a
// genuinely malformed diagram, not a diagram that just needs more time. Checking this before
// calling mermaid.render() turns "No diagram type detected" from a parser exception (thrown
// from deep inside Mermaid, then retried once against the auto-repair pass for no benefit)
// into an immediate, predictable fallback.
const KNOWN_DIAGRAM_TYPES = /^\s*(?:---[\s\S]*?---\s*)?(flowchart|graph|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|gantt|pie|journey|gitGraph|mindmap|timeline|quadrantChart|requirementDiagram|c4Context|c4Container|c4Component|c4Dynamic|block-beta|xychart-beta|sankey-beta)\b/i;

export function hasRecognizedDiagramType(code) {
  return KNOWN_DIAGRAM_TYPES.test(code || '');
}

export function useMermaidRender(code) {
  const [result, setResult] = useState({ svg: null, error: null });
  const [themeTick, setThemeTick] = useState(0);
  const lastRenderedRef = useRef({ code: null, themeTick: null });

  useEffect(() => {
    const observer = new MutationObserver(() => setThemeTick(tick => tick + 1));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    // Guards against a parent re-render passing an equal-by-value code/themeTick pair back in -
    // React already skips the effect when neither dependency changed, but a remount (a fresh
    // component instance picking up the same finished message on route-back, for example)
    // would otherwise re-run the whole render-and-fade-in sequence for a diagram already drawn.
    if (lastRenderedRef.current.code === code && lastRenderedRef.current.themeTick === themeTick) return undefined;
    if (!hasRecognizedDiagramType(code)) {
      lastRenderedRef.current = { code, themeTick };
      setResult({ svg: null, error: 'No diagram type detected' });
      return undefined;
    }
    let cancelled = false;
    // A fresh id per render, never one per component. Mermaid scopes the diagram's stylesheet to
    // this id and looks the element up by it while drawing — so rendering again under an id whose
    // markup is already mounted (a theme switch, or a re-layout for a narrower screen) makes it
    // collide with the diagram already on screen: the previous one gets reset mid-life and the new
    // one comes back as an empty, viewBox-less shell.
    const renderId = `mermaid-diagram-${++mermaidDiagramSeq}`;
    loadMermaid()
      .then(async mermaid => {
        if (cancelled) return null;
        mermaid.initialize({
          startOnLoad: false,
          theme: readMermaidTheme(),
          // 'strict' HTML-encodes label text, which turns an intentional <br/> line break
          // inside a node label into the literal text "<br>" instead of a line break. 'loose'
          // fixes that but disables Mermaid's own sanitization entirely - unacceptable here
          // since diagram source can come from an LLM answer (including unrestricted-mode
          // output) or a summarized untrusted document, and the rendered SVG is inserted via
          // dangerouslySetInnerHTML. 'antiscript' is the middle ground Mermaid ships for
          // exactly this: HTML tags in labels (including <br/>) render, only <script> is
          // stripped.
          securityLevel: 'antiscript',
          flowchart: { htmlLabels: true },
          fontFamily: 'inherit',
          suppressErrorRendering: true,
        });
        try {
          return await mermaid.render(renderId, code);
        } catch (firstError) {
          const repaired = repairMermaidCode(code);
          if (repaired === code) throw firstError;
          try {
            return await mermaid.render(`${renderId}-repaired`, repaired);
          } catch {
            throw firstError;
          }
        }
      })
      .then(rendered => {
        if (cancelled || !rendered) return;
        lastRenderedRef.current = { code, themeTick };
        setResult({ svg: rendered.svg, error: null });
      })
      .catch(error => {
        if (cancelled) return;
        lastRenderedRef.current = { code, themeTick };
        setResult({ svg: null, error: error?.message || 'Invalid diagram syntax' });
      });
    return () => { cancelled = true; };
  }, [code, themeTick]);

  return result;
}
