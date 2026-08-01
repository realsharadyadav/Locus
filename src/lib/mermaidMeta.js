// Figure chrome for a Mermaid diagram — title and colour legend — read back out of the diagram
// source itself rather than carried alongside it. Mermaid already needs `classDef` to colour nodes
// and frontmatter to title them, so deriving the chrome from those means the legend can never drift
// out of sync with the drawing, and the model has no extra contract to satisfy.

const FRONTMATTER = /^\s*---\r?\n([\s\S]*?)\r?\n---/;
const TITLE_LINE = /^\s*title\s*:\s*(.+?)\s*$/m;
// classDef <name> <k:v,k:v...>  — one or more class names may share a single declaration.
const CLASS_DEF = /^\s*classDef\s+([A-Za-z0-9_,\-\s]+?)\s+(.+?)\s*$/gm;

// Mermaid's own reserved class; it styles every node and is not a category worth showing.
const IGNORED_CLASSES = new Set(['default']);

function readTitle(code) {
  const frontmatter = FRONTMATTER.exec(code);
  if (!frontmatter) return '';
  const title = TITLE_LINE.exec(frontmatter[1]);
  if (!title) return '';
  return title[1].replace(/^['"]|['"]$/g, '').trim();
}

function humanize(name) {
  return name
    .replace(/[_-]+/g, ' ')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .trim()
    .replace(/^./, character => character.toUpperCase());
}

function readStyle(declaration) {
  const style = {};
  for (const pair of declaration.split(',')) {
    const [key, ...rest] = pair.split(':');
    if (!key || !rest.length) continue;
    style[key.trim().toLowerCase()] = rest.join(':').trim();
  }
  return style;
}

function readLegend(code) {
  const entries = [];
  const seen = new Set();
  CLASS_DEF.lastIndex = 0;
  let match = CLASS_DEF.exec(code);
  while (match) {
    const style = readStyle(match[2]);
    for (const raw of match[1].split(',')) {
      const name = raw.trim();
      if (!name || seen.has(name) || IGNORED_CLASSES.has(name)) continue;
      // A class with no fill is a shape or stroke tweak, not a category — nothing to show a swatch for.
      if (!style.fill) continue;
      seen.add(name);
      entries.push({ name, label: humanize(name), fill: style.fill, stroke: style.stroke || style.fill });
    }
    match = CLASS_DEF.exec(code);
  }
  return entries;
}

export function readMermaidMeta(code) {
  if (typeof code !== 'string' || !code.trim()) return { title: '', legend: [] };
  const legend = readLegend(code);
  return {
    title: readTitle(code),
    // A single category explains nothing, and past a handful the legend competes with the diagram.
    legend: legend.length >= 2 ? legend.slice(0, 6) : [],
  };
}
