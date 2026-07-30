import React from 'react';


export const humanizePipelineDetail = (detail = '') => {
  const text = String(detail || '').replace(/\s+/g, ' ').trim();
  const lowered = text.toLowerCase();
  if (!text) return 'Starting the pipeline.';
  if (lowered.startsWith('auto-enabled')) return 'Search intent detected. Auto-enabling web research and collecting sources.';
  if (lowered.includes('planning up to')) return 'Planning the query first, so the search is not random.';
  if (lowered.includes('round') && lowered.includes('follow-up')) return `Initial results were weak, trying the next search angle: ${text}`;
  if (lowered.includes('search') && lowered.includes(':')) return `Running search: ${text.split(':').slice(1).join(':').trim() || text}`;
  if (lowered.startsWith('→')) return `Found source: ${text.replace(/^→\s*/, '')}`;
  if (lowered.includes('collected') && lowered.includes('unique sources')) return `Collecting sources: ${text}`;
  if (lowered.includes('semantic retrieval')) return `Searching local files for relevant chunks: ${text}`;
  if (lowered.startsWith('searching')) return `Scanning uploaded files: ${text}`;
  if (lowered.includes('analysis plan ready')) return `Plan is ready. Building the answer against the evidence now.`;
  if (lowered.includes('calling') && lowered.includes('understand')) return `Understanding the question's intent and building the answer structure.`;
  if (lowered.startsWith('preparing')) return `Composing the draft: ${text}`;
  if (lowered.includes('synthesizing')) return `Merging sources and writing the final answer.`;
  if (lowered.includes('verify') || lowered.includes('quality')) return `Checking answer quality and grounding.`;
  if (lowered.includes('repair')) return `Found a gap, refining the answer.`;
  if (lowered.includes('answer ready') || lowered.includes('ready')) return `Answer is ready.`;
  if (lowered.includes('still') || lowered.includes('active')) return `Still working: ${text}`;
  return text.length > 170 ? `${text.slice(0, 167)}...` : text;
};

export const buildWorkingNotes = (events = [], pipeline = {}) => {
  const notes = [];
  const candidates = [
    ...events.filter(event => event.detail).map(event => ({
      id: `${event.at || ''}-${event.stage || ''}-${event.detail}`,
      stage: event.stage || pipeline.stage || 'working',
      text: humanizePipelineDetail(event.detail),
      live: false,
    })),
  ];
  if (pipeline.detail) {
    candidates.push({
      id: `current-${pipeline.stage}-${pipeline.detail}`,
      stage: pipeline.stage || 'working',
      text: humanizePipelineDetail(pipeline.detail),
      live: true,
    });
  }
  const seen = new Set();
  for (const item of candidates.reverse()) {
    const key = item.text.toLowerCase();
    if (!item.text || seen.has(key)) continue;
    seen.add(key);
    notes.unshift(item);
    if (notes.length >= 4) break;
  }
  return notes.length ? notes : [{ id: 'start', stage: 'starting', text: 'Got it. Processing the request.', live: true }];
};

export const directActivityToNote = item => {
  const label = item?.label || '';
  const detail = item?.detail || '';
  if (/sending/i.test(label)) return `Request sent: ${detail}`;
  if (/connecting/i.test(label)) return `Connecting to the model: ${detail}`;
  if (/streaming/i.test(label)) return `Answer is streaming in: ${detail}`;
  if (/saving/i.test(label)) return `Saving chat history.`;
  if (/stopped/i.test(label)) return `Stopped. You can change the model here and ask again.`;
  return detail || label || 'Working...';
};
