// react-markdown emits a heading and the content that follows it as flat siblings, so there is no
// element that represents "a section" to collapse, animate, or outline. This plugin walks the root
// children once and wraps each h2 together with everything up to the next h2 in a <section>.
//
// Only h2 starts a section: h1 is the answer title when the model emits one, and h3 is a subheading
// inside a section. Content before the first h2 (the summary paragraph) is left at the root so it
// keeps styling as the lede.
export function rehypeAnswerSections() {
  return tree => {
    if (!tree || !Array.isArray(tree.children)) return;

    const next = [];
    let current = null;

    for (const node of tree.children) {
      const isSectionHead = node.type === 'element' && node.tagName === 'h2';

      if (isSectionHead) {
        node.properties = { ...(node.properties || {}), 'data-section-head': 'true' };
        current = {
          type: 'element',
          tagName: 'section',
          properties: { 'data-answer-section': 'true' },
          children: [node],
        };
        next.push(current);
        continue;
      }

      if (current) current.children.push(node);
      else next.push(node);
    }

    tree.children = next;
  };
}
