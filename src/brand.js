export const BRAND = {
  name: 'Locus',
  tagline: 'Your knowledge, one question away.',
  assistantName: 'Locus AI',
  storagePrefix: 'locus',
};

const LEGACY_PREFIX = 'mindmap';

export function storageKey(suffix) {
  return `${BRAND.storagePrefix}-${suffix}`;
}

export function readStorage(suffix, fallback = null) {
  const key = storageKey(suffix);
  const value = window.localStorage.getItem(key);
  if (value != null) return value;
  const legacyKey = `${LEGACY_PREFIX}-${suffix}`;
  const legacy = window.localStorage.getItem(legacyKey);
  if (legacy != null) {
    window.localStorage.setItem(key, legacy);
    return legacy;
  }
  return fallback;
}

export function writeStorage(suffix, value) {
  window.localStorage.setItem(storageKey(suffix), value);
}

export function readSessionFlag(suffix) {
  const key = storageKey(suffix);
  const value = window.sessionStorage.getItem(key);
  if (value != null) return value;
  const legacy = window.sessionStorage.getItem(`${LEGACY_PREFIX}-${suffix}`);
  if (legacy != null) {
    window.sessionStorage.setItem(key, legacy);
    return legacy;
  }
  return null;
}

export function writeSessionFlag(suffix, value) {
  window.sessionStorage.setItem(storageKey(suffix), value);
}

export function assistantLabel(model, provider, providerLabels = {}) {
  if (!model) return BRAND.name;
  const providerLabel = provider ? `${providerLabels[provider] || provider} / ` : '';
  return `${BRAND.name} · ${providerLabel}${model}`;
}
