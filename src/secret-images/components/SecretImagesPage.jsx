import React, { useEffect, useRef, useState } from 'react';
import { Camera, Loader2, Lock, Menu, ShieldOff, Trash2, X } from 'lucide-react';
import { secretImagesApi } from '../api';

export default function SecretImagesPage({ toast, openMenu, requestConfirm }) {
  const [configured, setConfigured] = useState(true);
  const [checkingStatus, setCheckingStatus] = useState(true);
  const [images, setImages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [viewerImage, setViewerImage] = useState(null);
  const [sources, setSources] = useState({});
  const inputRef = useRef(null);
  // Object URLs hold their blob alive until revoked, so every one handed out is
  // tracked here and released on unmount.
  const sourcesRef = useRef({});
  sourcesRef.current = sources;

  useEffect(() => () => {
    Object.values(sourcesRef.current).forEach(URL.revokeObjectURL);
  }, []);

  // Resolve any image we do not have bytes for yet. Keyed by id, so re-running
  // after an upload only fetches the new one.
  useEffect(() => {
    let cancelled = false;
    const missing = images.filter(image => !sources[image.id]);
    if (!missing.length) return undefined;
    (async () => {
      for (const image of missing) {
        try {
          const url = await secretImagesApi.view(image.id);
          if (cancelled) { URL.revokeObjectURL(url); return; }
          setSources(current => (current[image.id] ? current : { ...current, [image.id]: url }));
        } catch {
          // A single unreadable photo should not take the gallery down with it;
          // its tile stays in the placeholder state.
        }
      }
    })();
    return () => { cancelled = true; };
  }, [images, sources]);

  const releaseSource = id => setSources(current => {
    if (!current[id]) return current;
    URL.revokeObjectURL(current[id]);
    const next = { ...current };
    delete next[id];
    return next;
  });

  const load = async () => {
    setLoading(true);
    try {
      setImages(await secretImagesApi.list());
    } catch (error) {
      toast?.(error.message || 'Could not load images', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    (async () => {
      try {
        const status = await secretImagesApi.status();
        setConfigured(status.configured);
        if (status.configured) await load();
      } catch {
        setConfigured(false);
      } finally {
        setCheckingStatus(false);
      }
    })();
  }, []);

  const handleFile = async event => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    setUploading(true);
    try {
      const created = await secretImagesApi.upload(file);
      setImages(current => [created, ...current]);
    } catch (error) {
      toast?.(error.message || 'Upload failed', 'error');
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = image => {
    requestConfirm?.({
      title: 'Delete image?',
      message: 'This removes it from storage permanently.',
      onConfirm: async () => {
        try {
          await secretImagesApi.remove(image.id);
          setImages(current => current.filter(item => item.id !== image.id));
          releaseSource(image.id);
          if (viewerImage?.id === image.id) setViewerImage(null);
        } catch (error) {
          toast?.(error.message || 'Could not delete image', 'error');
        }
      },
    });
  };

  return (
    <div className="page secret-images-page">
      <div className="secret-images-header">
        <button className="menu-button icon-button" onClick={openMenu} aria-label="Open menu">
          <Menu size={20} />
        </button>
        <div className="secret-images-title">
          <Lock size={16} />
          <h1>Secret Images</h1>
        </div>
        <button
          className="new-button secret-images-add"
          onClick={() => inputRef.current?.click()}
          disabled={!configured || uploading}
        >
          {uploading ? <Loader2 size={16} className="spin" /> : <Camera size={16} />}
          {uploading ? 'Uploading…' : 'Add photo'}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="secret-images-input"
          onChange={handleFile}
        />
      </div>

      {!checkingStatus && !configured && (
        <div className="secret-images-empty">
          <ShieldOff size={28} />
          <p>Secret Images isn't set up on this deployment yet.</p>
          <p className="secret-images-hint">Set the R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY and R2_BUCKET_NAME environment variables to enable it.</p>
        </div>
      )}

      {configured && !loading && images.length === 0 && (
        <div className="secret-images-empty">
          <Camera size={28} />
          <p>No photos yet. Add one to get started.</p>
        </div>
      )}

      {configured && (
        <div className="secret-images-grid">
          {images.map(image => (
            <button
              key={image.id}
              className="secret-images-tile"
              onClick={() => sources[image.id] && setViewerImage(image)}
            >
              {sources[image.id]
                ? <img src={sources[image.id]} alt="" />
                : <span className="secret-images-tile-loading"><Loader2 size={18} className="spin" /></span>}
            </button>
          ))}
        </div>
      )}

      {viewerImage && (
        <div className="secret-images-viewer" onClick={() => setViewerImage(null)}>
          <button className="icon-button secret-images-viewer-close" onClick={() => setViewerImage(null)} aria-label="Close">
            <X size={20} />
          </button>
          <img src={sources[viewerImage.id]} alt="" onClick={event => event.stopPropagation()} />
          <button
            className="secret-images-viewer-delete"
            onClick={event => { event.stopPropagation(); handleDelete(viewerImage); }}
          >
            <Trash2 size={16} /> Delete
          </button>
        </div>
      )}
    </div>
  );
}
