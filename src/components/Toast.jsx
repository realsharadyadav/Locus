import React, { useEffect, useRef } from 'react';
import { CheckCircle2, AlertCircle, X } from 'lucide-react';

export function ToastStack({ toasts, dismiss }) {
  return (
    <div className="toast-stack" aria-live="polite">
      {toasts.map(toast => (
        <Toast key={toast.id} toast={toast} onDismiss={() => dismiss(toast.id)} />
      ))}
    </div>
  );
}

function Toast({ toast, onDismiss }) {
  const savedDismiss = useRef(onDismiss);
  useEffect(() => { savedDismiss.current = onDismiss; });

  useEffect(() => {
    const timer = window.setTimeout(() => savedDismiss.current(), 3200);
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <div className={`toast toast-${toast.type}`}>
      {toast.type === 'error' ? <AlertCircle size={16} /> : <CheckCircle2 size={16} />}
      <span>{toast.message}</span>
      <button className="icon-button toast-close" onClick={() => onDismiss()} aria-label="Dismiss">
        <X size={14} />
      </button>
    </div>
  );
}
