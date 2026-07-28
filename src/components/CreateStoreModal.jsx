import React, { useEffect, useState } from 'react';
import { ArrowRight, Folder, X } from 'lucide-react';
import { STORE_COLORS } from '../utils';

export function CreateStoreModal({ open, close, onCreate }) {
  const [form, setForm] = useState({ title: '', description: '', color: 'violet' });
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setForm({ title: '', description: '', color: 'violet' });
      setError('');
    }
  }, [open]);

  if (!open) return null;

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    try {
      await onCreate(form);
      close();
    } catch (exception) {
      setError(exception.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-wrap" onMouseDown={event => event.target === event.currentTarget && close()}>
      <div className="modal">
        <button className="modal-close icon-button" onClick={close} aria-label="Close">
          <X size={18} />
        </button>
        <div className="modal-symbol"><Folder /></div>
        <span className="kicker">NEW LIBRARY</span>
        <h2>Create a home for your files</h2>
        <p>Group related files so your knowledge stays organized.</p>
        <form onSubmit={submit} className="capture-form">
          <input
            required
            autoFocus
            placeholder="Library name"
            value={form.title}
            onChange={event => setForm({ ...form, title: event.target.value })}
          />
          <textarea
            placeholder="Short description (optional)"
            value={form.description}
            onChange={event => setForm({ ...form, description: event.target.value })}
          />
          <div className="color-picker">
            {STORE_COLORS.map(color => (
              <button
                key={color}
                type="button"
                className={`color-option ${color} ${form.color === color ? 'selected' : ''}`}
                onClick={() => setForm({ ...form, color })}
                aria-label={`${color} color`}
              />
            ))}
          </div>
          {error && <p className="form-error">{error}</p>}
          <button className="save-button" disabled={saving}>
            {saving ? 'Creating...' : 'Create library'} <ArrowRight size={16} />
          </button>
        </form>
      </div>
    </div>
  );
}
