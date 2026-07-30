import React from 'react';
import {
  BookOpen, Database, Radio, Sparkles, Zap,
} from 'lucide-react';

export const SLASH_COMMANDS = [
  { id: 'light', label: '/light', desc: 'Fast direct chat — default mode', icon: Radio, color: '#7c6cff' },
  { id: 'unrestricted', label: '/unrestricted', desc: 'Expert mode — direct, low-fluff answers', icon: Zap, color: '#ff6b6b' },
  { id: 'thinking', label: '/thinking', desc: 'Deep analysis — inspects all selected content', icon: Sparkles, color: '#a78bfa' },
  { id: 'deep_summary', label: '/deepsummary', desc: 'Complete section-by-section doc coverage', icon: BookOpen, color: '#60a5fa' },
  { id: 'ticket_analysis', label: '/ticketanalysis', desc: 'Group incidents by problem pattern', icon: Database, color: '#34d399' },
];

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

export const shouldAutoWebSearch = (text, mode = 'light') => {
  if (['ticket_analysis', 'deep_summary'].includes(mode)) return false;
  const normalized = String(text || '').replace(/\s+/g, ' ').trim();
  return Boolean(normalized) && AUTO_WEB_SEARCH_PATTERNS.some(pattern => pattern.test(normalized));
};
