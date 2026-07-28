import React from 'react';


export function greetingForHour(hour) {
  if (hour < 5) return 'Still up?';
  if (hour < 12) return 'Good morning';
  if (hour < 17) return 'Good afternoon';
  if (hour < 21) return 'Good evening';
  return 'Good night';
}

export function formatElapsedTime(totalSeconds) {
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

export function formatFileSize(bytes = 0) {
  const size = Number(bytes) || 0;
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(size >= 10 * 1024 * 1024 ? 0 : 1)} MB`;
  if (size >= 1024) return `${(size / 1024).toFixed(size >= 10 * 1024 ? 0 : 1)} KB`;
  return `${size} B`;
}

export function fileMetaLine(file) {
  if (!file) return 'No metadata';
  const chunks = Number(file.embedding_chunks || 0);
  const chunkLabel = chunks === 1 ? '1 chunk' : `${chunks} chunks`;
  return `${formatFileSize(file.size)} · ${chunkLabel}`;
}

export function embeddingMeta(file) {
  const status = file.embedding_status || 'pending';
  const chunks = file.embedding_chunks || 0;
  const backend = file.embedding_backend || 'local';
  const model = file.embedding_model || 'local-hash-embedding-v1';
  const labels = {
    embedded: `${chunks} chunks indexed`,
    indexing: 'Embedding now',
    pending: 'Waiting to index',
    empty: 'No searchable text',
    failed: 'Index failed',
  };
  return {
    status,
    backend,
    model,
    label: labels[status] || 'Index pending',
    detail: status === 'embedded' ? `${backend} · ${model}` : (file.embedding_error || model),
  };
}

export function modelProvider(model) {
  if (model.includes('/') || model.startsWith('llama-3.')) return 'Groq';
  if (model.startsWith('gpt-')) return 'OpenAI';
  if (model.startsWith('gemini-')) return 'Google Gemini';
  if (model.includes('cloud')) return 'Ollama Cloud';
  return 'On-device';
}

export function formatContextLength(value) {
  if (!value) return null;
  if (value >= 1000000) return `${(value / 1000000).toFixed(value % 1000000 === 0 ? 0 : 1)}M ctx`;
  if (value >= 1000) return `${Math.round(value / 1000)}K ctx`;
  return `${value} ctx`;
}

export function jobFailureMessage(job) {
  const error = job?.error || job?.detail || 'The answer could not be completed.';
  const diagnosticId = job?.id ? `\n\nDiagnostic ID: ${job.id}` : '';
  const lowered = error.toLowerCase();
  if (job?.model?.startsWith('gemini-') && lowered.includes('quota')) {
    const zeroLimit = lowered.includes('limit: 0');
    return `Gemini quota exceeded for ${job.model}. ${zeroLimit ? 'Google reports that this project has no available quota for this model. Enable billing or quota in Google AI Studio, or select Gemini 2.5 Flash.' : 'Wait for the quota window to reset, increase your quota, or select another model.'}${diagnosticId}`;
  }
  if (lowered.includes('api key') || lowered.includes('authentication')) {
    return `${modelProvider(job?.model || '')} authentication failed. Check the API key in .env and restart the backend.${diagnosticId}`;
  }
  return `${error}${diagnosticId}`;
}
