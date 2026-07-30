import React, { useEffect, useState } from 'react';
import {
  ArrowLeft, Check, Database, FileText, Folder, Plus, Trash2, Upload,
} from 'lucide-react';
import { api } from '../api';
import { BRAND } from '../brand';
import { DEFAULT_UPLOAD_LIMIT_MB } from '../lib/appState';
import { embeddingMeta, fileMetaLine, formatFileSize } from '../lib/format';
import { displayTime } from '../utils';

export function HubPage({
  query, files, stores, focusStoreId, clearFocusStore, openCreate,
  uploadFile, requestDeleteFile, requestDeleteStore, toast,
}) {
  const [activeStore, setActiveStore] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadStage, setUploadStage] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [uploadLimitMb, setUploadLimitMb] = useState(DEFAULT_UPLOAD_LIMIT_MB);

  useEffect(() => {
    let cancelled = false;
    api.systemLimits()
      .then(limits => { if (!cancelled && limits?.upload_max_mb) setUploadLimitMb(limits.upload_max_mb); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (focusStoreId) {
      const store = stores.find(item => item.id === focusStoreId);
      if (store) setActiveStore(store);
      clearFocusStore();
    }
  }, [focusStoreId, stores, clearFocusStore]);

  const visibleStores = stores.filter(store =>
    store.title.toLowerCase().includes(query.toLowerCase()) ||
    store.description?.toLowerCase().includes(query.toLowerCase()),
  );
  const visibleFiles = files.filter(file =>
    file.store_id === activeStore?.id &&
    file.name.toLowerCase().includes(query.toLowerCase()),
  );

  const handleUpload = async (fileList) => {
    const file = fileList?.[0];
    if (!file || !activeStore) return;
    if (file.size > uploadLimitMb * 1024 * 1024) {
      toast(`Files must be ${uploadLimitMb} MB or smaller`, 'error');
      return;
    }
    setUploading(true);
    setUploadStage({
      step: 0,
      title: 'Receiving file',
      detail: `${file.name} · ${formatFileSize(file.size)}`,
    });
    const timers = [
      window.setTimeout(() => setUploadStage({ step: 1, title: 'Extracting text', detail: 'Reading pages, sheets, rows and code blocks' }), 500),
      window.setTimeout(() => setUploadStage({ step: 2, title: 'Creating embeddings', detail: 'Model: local-hash-embedding-v1' }), 1200),
      window.setTimeout(() => setUploadStage({ step: 3, title: 'Writing vector index', detail: 'Persisting chunks to local Chroma/SQLite store' }), 2200),
    ];
    try {
      const uploaded = await uploadFile(activeStore.id, file);
      const meta = embeddingMeta(uploaded || {});
      setUploadStage({
        step: 4,
        title: meta.status === 'failed' ? 'Upload saved, index failed' : 'Ready for semantic search',
        detail: `${meta.label} · ${meta.detail}`,
      });
      toast(meta.status === 'failed' ? 'File uploaded, indexing failed' : 'File uploaded and indexed', meta.status === 'failed' ? 'error' : 'success');
    } catch (error) {
      setUploadStage({ step: 4, title: 'Upload failed', detail: error.message });
      toast(error.message, 'error');
    } finally {
      timers.forEach(timer => window.clearTimeout(timer));
      window.setTimeout(() => setUploadStage(null), 1800);
      setUploading(false);
    }
  };

  if (activeStore) {
    return (
      <div className="page inner-page">
        <button className="back-button" onClick={() => setActiveStore(null)}>
          <ArrowLeft size={15} /> All libraries
        </button>
        <div className="inner-title store-title">
          <div>
            <span className="kicker">LIBRARY</span>
            <h1>{activeStore.title}</h1>
            <p>{activeStore.description || 'Files in this library are available in Ask.'}</p>
          </div>
          <label className={`new-button upload-button ${uploading ? 'disabled' : ''}`}>
            <Upload size={16} />{uploading ? 'Uploading...' : 'Upload file'}
            <input
              type="file"
              accept=".xlsx,.xlsm,.csv,.tsv,.txt,.md,.pdf,.docx,.json,.html,.css,.js,.jsx,.py"
              onChange={event => handleUpload(event.target.files).finally(() => { event.target.value = ''; })}
              disabled={uploading}
            />
          </label>
        </div>

        <div
          className={`drop-zone ${dragging ? 'dragging' : ''} ${uploading ? 'processing' : ''}`}
          onDragOver={event => { event.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={event => {
            event.preventDefault();
            setDragging(false);
            handleUpload(event.dataTransfer.files);
          }}
        >
          <Upload size={18} />
          <div>
            <span>{uploadStage?.title || 'Drop files here to upload'}</span>
            {uploadStage ? <small>{uploadStage.detail}</small> : <small>PDF, DOCX, XLSX, XLSM, CSV, TSV and text · up to {uploadLimitMb} MB</small>}
          </div>
          {uploadStage && (
            <div className="upload-pipeline" aria-live="polite">
              {['Upload', 'Extract', 'Embed', 'Index', 'Ready'].map((label, index) => (
                <span key={label} className={index <= uploadStage.step ? 'active' : ''}>
                  <i>{index < uploadStage.step ? <Check size={10} /> : index + 1}</i>
                  {label}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="simple-files">
          {visibleFiles.map(file => {
            const meta = embeddingMeta(file);
            return (
              <article key={file.id}>
                <div className="file-icon"><FileText /></div>
                <div>
                  <h3>{file.name}</h3>
                  <p>{fileMetaLine(file)} · {displayTime(file.created_at)}</p>
                  <span className={`embedding-badge ${meta.status}`} title={meta.detail}>
                    <Database size={11} /> {meta.label}
                  </span>
                </div>
                <button
                  className="icon-button delete-button"
                  onClick={() => requestDeleteFile(file)}
                  aria-label={`Delete ${file.name}`}
                >
                  <Trash2 size={16} />
                </button>
              </article>
            );
          })}
          {!visibleFiles.length && (
            <div className="store-empty">
              <Upload size={24} />
              <h3>No files yet</h3>
              <p>Upload a document or spreadsheet to make it available in Ask.</p>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="page inner-page">
      <div className="inner-title">
        <div>
          <span className="kicker">LIBRARY</span>
          <h1>Your libraries</h1>
          <p>Create a library, then add the files you want {BRAND.name} to understand.</p>
          {query && <p className="filter-note">Showing libraries matching “{query}”</p>}
        </div>
        <button className="new-button" onClick={openCreate}><Plus size={17} /> New library</button>
      </div>
      <div className="stores-grid">
        {visibleStores.map(store => (
          <article className="store-card" key={store.id}>
            <button className="store-open" onClick={() => setActiveStore(store)}>
              <span className={`store-folder ${store.color}`}><Folder size={23} /></span>
              <span>
                <strong>{store.title}</strong>
                <small>{store.count} {store.count === 1 ? 'file' : 'files'}</small>
              </span>
            </button>
            <button
              className="store-delete icon-button"
              onClick={() => requestDeleteStore(store)}
              aria-label={`Delete ${store.title}`}
            >
              <Trash2 size={16} />
            </button>
          </article>
        ))}
        <button className="store-card create-store" onClick={openCreate}>
          <span className="store-folder"><Plus size={22} /></span>
          <span><strong>Create a library</strong><small>Organize a new topic</small></span>
        </button>
      </div>
    </div>
  );
}
