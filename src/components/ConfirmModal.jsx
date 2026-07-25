import React from 'react';
import { Trash2, X } from 'lucide-react';

export function ConfirmModal({ config, close }) {
  if (!config) return null;

  const confirm = async () => {
    await config.onConfirm();
    close();
  };

  return (
    <div className="modal-wrap" onMouseDown={event => event.target === event.currentTarget && close()}>
      <div className="modal confirm-modal">
        <button className="modal-close icon-button" onClick={close} aria-label="Close">
          <X size={18} />
        </button>
        <div className="modal-symbol danger">
          <Trash2 size={20} />
        </div>
        <span className="kicker">CONFIRM</span>
        <h2>{config.title}</h2>
        <p>{config.message}</p>
        <div className="confirm-actions">
          <button className="ghost-button" onClick={close}>Cancel</button>
          <button className="danger-button" onClick={confirm}>{config.confirmLabel || 'Delete'}</button>
        </div>
      </div>
    </div>
  );
}
