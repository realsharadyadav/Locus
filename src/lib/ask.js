import React from 'react';
import {
  BookOpen, Radio, Sparkles,
} from 'lucide-react';

// One effort dial, three stops. Each stop is still backed by the same reasoning-mode id the
// backend has always used (light / thinking / deep_summary) — only the product-facing label
// changed, so MODE_CONFIG, the API contract, and every existing test stay put. Effort is a
// straight line from "fast" to "exhaustive": with files selected, that means reading more of
// them (light -> excerpts, thinking -> everything, deep_summary -> every section); with no
// files selected, there's nothing local to read more of, so effort instead means digging
// further into the web — more sources, more search rounds — rather than just answering from
// the model's own memory. See EFFORT_WEB_SOURCE_LIMIT and shouldAutoWebSearch below.
export const SLASH_COMMANDS = [
  {
    id: 'light',
    label: '/normal',
    desc: 'Fast, everyday answers — default effort',
    friendlyLabel: 'Normal',
    friendlyDesc: 'Fast answer from the most relevant context',
    icon: Radio,
    color: '#7c6cff',
  },
  {
    id: 'thinking',
    label: '/high',
    desc: 'Reads everything selected and reasons across it',
    friendlyLabel: 'High',
    friendlyDesc: 'Inspects every selected file, or researches the web if none are selected',
    icon: Sparkles,
    color: '#a78bfa',
  },
  {
    id: 'deep_summary',
    label: '/max',
    desc: 'Exhaustive section-by-section document coverage',
    friendlyLabel: 'Max',
    friendlyDesc: 'Covers every document section, or the widest web research if none are selected',
    icon: BookOpen,
    color: '#60a5fa',
  },
];

// Effort governs more than file inspection: it also caps how far the web-research pipeline is
// allowed to go. The backend's LLM planner already picks its own source count per query
// (3-200, scaled to how complex the question looks — see agentic_pipeline.py) and clamps it to
// this ceiling before running; number of search rounds scales off the same ceiling. Normal
// keeps that clamp tight so a quick question can't balloon into a 50-source research pass; Max
// removes the clamp entirely so a genuinely deep question gets everything the planner asks for.
export const EFFORT_WEB_SOURCE_LIMIT = {
  light: 20,
  thinking: 60,
  deep_summary: 200,
};

export const AUTO_WEB_SEARCH_PATTERNS = [
  /\b(search|browse|look\s*up|google|find\s+(?:me\s+)?(?:latest|current|recent|news|online|web|internet))\b/i,
  /\b(latest|current|recent|today|yesterday|this\s+week|this\s+month|news|breaking|updates?)\b/i,
  /\b(youtube|video|videos)\b/i,
  /\b(source|sources|citation|citations|link|links|url|website|webpage)\b/i,
  // Sports
  /\b(cricket|football|soccer|tennis|basketball|match|score|live\s+score|result|ipl|epl|nba|nfl)\b/i,
  // Stock/Finance
  /\b(stock|share|shares|nse|bse|sensex|nifty|mutual\s+fund|ipo|dividend|trading|portfolio)\b/i,
  // Currency
  /\b(currency|exchange\s+rate|forex|dollar|euro|pound|rupee|usd|eur|gbp|inr)\b/i,
  // Flight
  /\b(flight|airline|airport|pnr|boarding|departure|arrival|delayed)\b/i,
  // Food
  /\b(recipe|recipes|cook|cooking|restaurant|cafe|menu|ingredients)\b/i,
  // Health
  /\b(symptom|symptoms|treatment|medicine|diagnosis|disease|doctor|hospital)\b/i,
  // Entertainment
  /\b(movie|movies|film|cinema|series|netflix|concert|album|song|music)\b/i,
  // Mixed-language current-query keywords
  /\b(barish|barsaat|mausam|tapman|garmi|thand|sardi|toofan|aandhi|kohra|dhund)\b/i,
  /\b(aaj|kal|abhi|taza|samachar|khabar|score|natija|result|bhav|kimat|dam)\b/i,
  /\b(cricket|football|match|khel|maukka)\b/i,
  /\b(stock|share|bazaar|bhav|nivesh|munafa)\b/i,
  /\b(dollar|rupaye|exchange|currency|kitna)\b/i,
  /\b(flight|hawai|pnr)\b/i,
  /\b(recipe|pakwan|khaana|restaurant)\b/i,
  /\b(bimari|dawa|ilaj|doctor|hospital|bukhar)\b/i,
  /\b(movie|film|cinema|gaana|concert)\b/i,
  /\b(hoga|hogi|hoga\s+kya|batao|dikhao|btao|konsa|kaunsa|kaisa|kaise)\b/i,
  /\b(sasta|mehnga|kharid|accha|badhiya|sabse)\b/i,
  /\b(comp(?:are|aire?)|vs\.?|versus|difference\s+between|contras?t)\b/i,
  /\b(better|worse|best|worst|which\s+(?:one|is|should|do)|recommend(?:ed|ation)?|suggestion|pros?\s+and\s+cons?)\b/i,
];

// Mirrors backend/app/main.py's _effective_web_search: at High/Max effort with no files
// selected, there's nothing local to inspect, so more effort has to mean going and finding
// real sources rather than answering from the model's memory. `noFilesSelected` should be true
// only when the user explicitly has zero files in scope (not "search my whole library").
export const shouldAutoWebSearch = (text, mode = 'light', noFilesSelected = false) => {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim();
  if (!normalized) return false;
  if ((mode === 'thinking' || mode === 'deep_summary') && noFilesSelected) return true;
  if (mode === 'deep_summary') return false;
  return AUTO_WEB_SEARCH_PATTERNS.some(pattern => pattern.test(normalized));
};
