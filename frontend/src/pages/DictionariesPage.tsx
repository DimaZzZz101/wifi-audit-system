/** Dictionaries page: system-level wordlist management. */
import { useState, useEffect, useCallback, useRef } from "react";
import { api, type DictionaryItem } from "../api/client";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString("ru-RU");
  } catch {
    return iso;
  }
}

function isGenerating(d: DictionaryItem): boolean {
  return d.size_bytes === 0 && d.word_count === 0;
}

export default function DictionariesPage() {
  const [dicts, setDicts] = useState<DictionaryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showUpload, setShowUpload] = useState(false);
  const [showGenerate, setShowGenerate] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval>>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setDicts(await api.dictionaries.list());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const hasGenerating = dicts.some(isGenerating);
    if (hasGenerating) {
      pollRef.current = setInterval(async () => {
        try {
          const fresh = await api.dictionaries.list();
          setDicts(fresh);
          if (!fresh.some(isGenerating)) clearInterval(pollRef.current);
        } catch { /* ignore */ }
      }, 3000);
    }
    return () => clearInterval(pollRef.current);
  }, [dicts.length]);

  const handleDelete = async (id: number) => {
    if (!confirm("Delete this dictionary?")) return;
    try {
      await api.dictionaries.delete(id);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  };

  return (
    <div className="panel-page dictionaries-page">
      <div className="panel-card">
        <div className="dict-header">
          <h2 className="dict-title">Dictionaries</h2>
          <div className="dict-actions">
            <button type="button" className="dict-btn dict-btn--primary" onClick={() => setShowUpload(true)}>
              Upload
            </button>
            <button type="button" className="dict-btn dict-btn--secondary" onClick={() => setShowGenerate(true)}>
              Generate
            </button>
          </div>
        </div>

        {error && <p className="error">{error}</p>}

        {showUpload && (
          <UploadModal
            onClose={() => setShowUpload(false)}
            onDone={() => { setShowUpload(false); load(); }}
          />
        )}

        {showGenerate && (
          <GenerateModal
            onClose={() => setShowGenerate(false)}
            onDone={() => { setShowGenerate(false); load(); }}
          />
        )}

        {loading ? (
          <p className="dict-loading">Loading...</p>
        ) : dicts.length === 0 ? (
          <p className="dict-empty">No dictionaries yet. Upload or generate one.</p>
        ) : (
          <table className="dict-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Size</th>
                <th>Words</th>
                <th>Created</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {dicts.map((d) => {
                const generating = isGenerating(d);
                return (
                  <tr key={d.id} className={generating ? "dict-row--generating" : ""}>
                    <td>
                      <span className="dict-name">{d.name}</span>
                      {generating && <span className="dict-generating-badge">Generating...</span>}
                      {d.description && <span className="dict-desc">{d.description}</span>}
                    </td>
                    <td>{generating ? "-" : formatSize(d.size_bytes)}</td>
                    <td>{generating ? "-" : d.word_count.toLocaleString()}</td>
                    <td>{formatDate(d.created_at)}</td>
                    <td className="dict-row-actions">
                      {!generating && (
                        <button
                          type="button"
                          className="dict-btn dict-btn--small"
                          onClick={() => api.dictionaries.download(d.id, d.filename)}
                        >
                          Download
                        </button>
                      )}
                      <button
                        type="button"
                        className="dict-btn dict-btn--small dict-btn--danger"
                        onClick={() => handleDelete(d.id)}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function UploadModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [desc, setDesc] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async () => {
    if (!name || !file) return;
    setSaving(true);
    try {
      await api.dictionaries.upload(name, file, desc || undefined);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="dict-modal-overlay" onClick={onClose}>
      <div className="dict-modal" onClick={(e) => e.stopPropagation()}>
        <h3>Upload Dictionary</h3>
        <label>
          Name
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. rockyou" />
        </label>
        <label>
          File
          <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <label>
          Description (optional)
          <input type="text" value={desc} onChange={(e) => setDesc(e.target.value)} />
        </label>
        {error && <p className="error">{error}</p>}
        <div className="dict-modal-actions">
          <button type="button" className="dict-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="dict-btn dict-btn--primary" onClick={handleSubmit} disabled={saving || !name || !file}>
            {saving ? "Uploading..." : "Upload"}
          </button>
        </div>
      </div>
    </div>
  );
}

function GenerateModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState("");
  const [masks, setMasks] = useState("?d?d?d?d?d?d?d?d");
  const [desc, setDesc] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async () => {
    if (!name || !masks.trim()) return;
    setSaving(true);
    try {
      const maskList = masks.split("\n").map((m) => m.trim()).filter(Boolean);
      await api.dictionaries.generate(name, maskList, desc || undefined);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="dict-modal-overlay" onClick={onClose}>
      <div className="dict-modal" onClick={(e) => e.stopPropagation()}>
        <h3>Generate Dictionary</h3>
        <label>
          Name
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. 8-digit-pins" />
        </label>
        <label>
          Mask patterns (one per line)
          <textarea value={masks} onChange={(e) => setMasks(e.target.value)} rows={4} placeholder="?d?d?d?d?d?d?d?d" />
        </label>
        <div className="dict-mask-hint">
          ?d = digits, ?l = lowercase, ?u = uppercase, ?s = special, ?a = all printable, ?h = hex lower, ?H = hex upper
        </div>
        <label>
          Description (optional)
          <input type="text" value={desc} onChange={(e) => setDesc(e.target.value)} />
        </label>
        {error && <p className="error">{error}</p>}
        <div className="dict-modal-actions">
          <button type="button" className="dict-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="dict-btn dict-btn--primary" onClick={handleSubmit} disabled={saving || !name}>
            {saving ? "Generating..." : "Generate"}
          </button>
        </div>
      </div>
    </div>
  );
}
