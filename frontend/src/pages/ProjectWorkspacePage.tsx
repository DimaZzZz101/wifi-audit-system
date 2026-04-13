/** Рабочая область проекта - файловая структура, инструменты, просмотр и скачивание. */
import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  getToken,
  ApiError,
  type ProjectItem,
  type ProjectFileItem,
} from "../api/client";
import { useActiveProject } from "../contexts/ActiveProjectContext";
import SessionReconTab from "./SessionReconTab";
import SessionAuditTab from "./SessionAuditTab";
import "./SessionReconTab.css";

type WorkspaceTab = "files" | "recon" | "filters" | "audit";

const TEXT_EXTENSIONS = new Set([
  "txt", "log", "json", "xml", "html", "htm", "css", "js", "md", "csv", "cap", "pcap",
]);

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function isTextViewable(name: string): boolean {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  return TEXT_EXTENSIONS.has(ext);
}


// ---------------------------------------------------------------------------
// Files tab
// ---------------------------------------------------------------------------

function FilesTab({ projectId }: { projectId: number }) {
  const { clearActiveProject } = useActiveProject();
  const navigate = useNavigate();
  const [path, setPath] = useState("");
  const [items, setItems] = useState<ProjectFileItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [viewingFile, setViewingFile] = useState<{ path: string; content: string } | null>(null);
  const [downloadingPath, setDownloadingPath] = useState<string | null>(null);
  const [pathLabels, setPathLabels] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api.projects.filesList(projectId, path || undefined);
      setItems(data.items);
      setPathLabels((prev) => {
        const next = { ...prev };
        for (const item of data.items) {
          if (item.display_name) {
            next[item.path] = item.display_name;
          }
        }
        return next;
      });
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        clearActiveProject();
        navigate("/projects");
      } else {
        setError(e instanceof Error ? e.message : "Ошибка загрузки файлов");
      }
    } finally {
      setLoading(false);
    }
  }, [projectId, path]);

  useEffect(() => {
    load();
  }, [load]);

  const handleNavigate = (item: ProjectFileItem) => {
    if (item.is_dir) {
      setPath(item.path);
      setViewingFile(null);
    } else if (isTextViewable(item.name)) {
      const token = getToken();
      fetch(`/api/projects/${projectId}/files/content?path=${encodeURIComponent(item.path)}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
        .then((r) => r.text())
        .then((content) => setViewingFile({ path: item.path, content }))
        .catch(() => setError("Не удалось загрузить файл"));
    }
  };

  const handleDownload = async (item: ProjectFileItem) => {
    if (item.is_dir) return;
    setDownloadingPath(item.path);
    setError("");
    try {
      await api.projects.fileDownload(projectId, item.path, item.name);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка скачивания");
    } finally {
      setDownloadingPath(null);
    }
  };

  const handleBack = () => {
    const parts = path.split("/").filter(Boolean);
    parts.pop();
    setPath(parts.join("/"));
    setViewingFile(null);
  };

  if (viewingFile) {
    return (
      <div className="session-workspace-viewer">
        <div className="session-workspace-viewer-header">
          <button type="button" className="session-workspace-btn-back" onClick={() => setViewingFile(null)}>
            {"<- Назад"}
          </button>
          <span className="session-workspace-viewer-path">{viewingFile.path}</span>
        </div>
        <pre className="session-workspace-viewer-content">{viewingFile.content}</pre>
      </div>
    );
  }

  return (
    <>
      <div className="session-workspace-breadcrumb">
        <button
          type="button"
          className="session-workspace-breadcrumb-item"
          onClick={() => {
            setPath("");
            setViewingFile(null);
          }}
        >
          /
        </button>
        {path
          .split("/")
          .filter(Boolean)
          .map((part, i, arr) => {
            const partialPath = arr.slice(0, i + 1).join("/");
            const label = pathLabels[partialPath] || part;
            return (
            <span key={`${i}-${part}`} className="session-workspace-breadcrumb-bits">
              {i > 0 ? (
                <span className="session-workspace-breadcrumb-slash" aria-hidden="true">
                  /
                </span>
              ) : null}
              <button
                type="button"
                className="session-workspace-breadcrumb-item"
                onClick={() => setPath(arr.slice(0, i + 1).join("/"))}
              >
                {label}
              </button>
            </span>
            );
          })}
      </div>

      {error && <p className="error">{error}</p>}

      {loading ? (
        <p className="session-workspace-loading">Загрузка...</p>
      ) : (
        <div className="session-workspace-files">
          {path && (
            <div className="session-workspace-file-row session-workspace-file-row--dir">
              <button
                type="button"
                className="session-workspace-file-main"
                onClick={handleBack}
              >
                <span className="session-workspace-file-icon">📁</span>
                <span className="session-workspace-file-name">..</span>
              </button>
            </div>
          )}
          {items.map((item) => (
            <div
              key={item.path}
              className={`session-workspace-file-row ${item.is_dir ? "session-workspace-file-row--dir" : ""}`}
            >
              <button
                type="button"
                className="session-workspace-file-main"
                onClick={() => handleNavigate(item)}
              >
                <span className="session-workspace-file-icon">{item.is_dir ? "📁" : "📄"}</span>
                <span className="session-workspace-file-name">{item.display_name || item.name}</span>
                {!item.is_dir && item.size != null && (
                  <span className="session-workspace-file-size">{formatSize(item.size)}</span>
                )}
              </button>
              {!item.is_dir && (
                <button
                  type="button"
                  className="session-workspace-file-download"
                  onClick={() => handleDownload(item)}
                  disabled={downloadingPath === item.path}
                >
                  {downloadingPath === item.path ? "..." : "Скачать"}
                </button>
              )}
            </div>
          ))}
          {items.length === 0 && !path && (
            <p className="session-workspace-empty">Папка пуста</p>
          )}
        </div>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Filters tab
// ---------------------------------------------------------------------------

const MAC_RE = /^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$/;

function FiltersTab({ projectId }: { projectId: number }) {
  const [filterType, setFilterType] = useState<"whitelist" | "blacklist">("blacklist");
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [validationErrors, setValidationErrors] = useState<string[]>([]);

  useEffect(() => {
    api.projects.getMacFilter(projectId).then((data) => {
      if (data.filter_type === "whitelist" || data.filter_type === "blacklist") {
        setFilterType(data.filter_type);
      }
      if (data.entries.length > 0) {
        setText(data.entries.join("\n"));
      }
    }).catch(() => {});
  }, [projectId]);

  const validate = (raw: string): { valid: string[]; errors: string[] } => {
    const lines = raw.split("\n").map((l) => l.trim()).filter(Boolean);
    const valid: string[] = [];
    const errors: string[] = [];
    for (const line of lines) {
      if (MAC_RE.test(line)) {
        valid.push(line.toUpperCase());
      } else {
        errors.push(line);
      }
    }
    return { valid, errors };
  };

  const handleSave = async () => {
    setError("");
    setSuccess("");
    const { valid, errors: errs } = validate(text);
    setValidationErrors(errs);
    if (errs.length > 0) {
      setError(`${errs.length} invalid MAC address(es)`);
      return;
    }
    setSaving(true);
    try {
      await api.projects.putMacFilter(projectId, {
        filter_type: filterType,
        entries: valid,
      });
      setSuccess(`Saved: ${valid.length} MAC address(es)`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save error");
    } finally {
      setSaving(false);
    }
  };

  const handleDownload = async () => {
    try {
      await api.projects.downloadMacFilter(projectId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download error");
    }
  };

  return (
    <div className="filters-tab">
      <div className="filters-type-toggle">
        <button
          type="button"
          className={`filters-type-btn ${filterType === "blacklist" ? "filters-type-btn--active" : "filters-type-btn--inactive"}`}
          onClick={() => setFilterType("blacklist")}
        >
          Blacklist
        </button>
        <button
          type="button"
          className={`filters-type-btn ${filterType === "whitelist" ? "filters-type-btn--active" : "filters-type-btn--inactive"}`}
          onClick={() => setFilterType("whitelist")}
        >
          Whitelist
        </button>
      </div>
      <p className="filters-hint">
        {filterType === "blacklist"
          ? "Networks with these BSSIDs will be excluded from results."
          : "Only networks with these BSSIDs will be shown."}
      </p>
      <textarea
        className="filters-textarea"
        rows={12}
        placeholder={"AA:BB:CC:DD:EE:FF\n11:22:33:44:55:66\n...one MAC per line"}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setValidationErrors([]);
          setError("");
          setSuccess("");
        }}
      />
      {validationErrors.length > 0 && (
        <div className="filters-validation">
          Invalid: {validationErrors.map((v, i) => <code key={i}>{v}</code>)}
        </div>
      )}
      <div className="filters-actions">
        <button
          type="button"
          className="filters-btn filters-btn--save"
          disabled={saving}
          onClick={handleSave}
        >
          {saving ? "Saving..." : "Save"}
        </button>
        <button
          type="button"
          className="filters-btn filters-btn--download"
          onClick={handleDownload}
        >
          Download mac_filter.txt
        </button>
      </div>
      {error && <p className="filters-error">{error}</p>}
      {success && <p className="filters-success">{success}</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ProjectWorkspacePage() {
  const navigate = useNavigate();
  const { activeProject, clearActiveProject } = useActiveProject();
  const [tab, setTab] = useState<WorkspaceTab>("recon");
  const [project, setProject] = useState<ProjectItem | null>(null);
  const [obfToggling, setObfToggling] = useState(false);

  useEffect(() => {
    if (activeProject) {
      api.projects.get(activeProject.id).then(setProject).catch(() => {});
    } else {
      setProject(null);
    }
  }, [activeProject?.id]);

  const obfuscationEnabled = project?.obfuscation_enabled ?? false;

  const toggleObfuscation = async () => {
    if (!project) return;
    setObfToggling(true);
    try {
      const updated = await api.projects.update(project.id, {
        obfuscation_enabled: !obfuscationEnabled,
      });
      setProject(updated);
    } catch {
      // ignore
    } finally {
      setObfToggling(false);
    }
  };

  if (!activeProject) {
    return (
      <div className="panel-page session-workspace-page">
        <div className="panel-card">
          <h2 className="session-workspace-title">Workspace</h2>
          <p className="session-workspace-message">
            Проект не выбран. Перейдите в раздел "Проекты" и активируйте проект.
          </p>
          <button type="button" className="session-workspace-btn" onClick={() => navigate("/projects")}>
            Перейти к проектам
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="panel-page session-workspace-page">
      <div className="panel-card session-workspace-card">
        <div className="session-workspace-header">
          <h2 className="session-workspace-title">
            Workspace: {activeProject.name}
            <span className="session-workspace-id" title="ID проекта"> (#{activeProject.slug})</span>
          </h2>
          <div className="session-workspace-actions">
            <button
              type="button"
              className={`obfuscation-toggle ${obfuscationEnabled ? "obfuscation-toggle--on" : ""}`}
              onClick={toggleObfuscation}
              disabled={obfToggling}
              title={obfuscationEnabled ? "Obfuscation ON - click to disable" : "Obfuscation OFF - click to enable"}
            >
              <span className="obfuscation-toggle-label">{obfuscationEnabled ? "Censored" : "Open"}</span>
            </button>
            <button
              type="button"
              className="session-workspace-btn-secondary"
              onClick={() => {
                clearActiveProject();
                navigate("/projects");
              }}
            >
              Сменить проект
            </button>
          </div>
        </div>

        <div className="session-workspace-tabs">
          <button
            type="button"
            className={`session-workspace-tab ${tab === "recon" ? "is-active" : ""}`}
            onClick={() => setTab("recon")}
          >
            Recon
          </button>
          <button
            type="button"
            className={`session-workspace-tab ${tab === "audit" ? "is-active" : ""}`}
            onClick={() => setTab("audit")}
          >
            Audit
          </button>
          <button
            type="button"
            className={`session-workspace-tab ${tab === "filters" ? "is-active" : ""}`}
            onClick={() => setTab("filters")}
          >
            Filters
          </button>
          <button
            type="button"
            className={`session-workspace-tab ${tab === "files" ? "is-active" : ""}`}
            onClick={() => setTab("files")}
          >
            Files
          </button>
        </div>

        {tab === "recon" && <SessionReconTab projectId={activeProject.id} obfuscationEnabled={obfuscationEnabled} onPlanAudit={() => setTab("audit")} />}
        {tab === "audit" && <SessionAuditTab projectId={activeProject.id} obfuscationEnabled={obfuscationEnabled} />}
        {tab === "filters" && <FiltersTab projectId={activeProject.id} />}
        {tab === "files" && <FilesTab projectId={activeProject.id} />}
      </div>
    </div>
  );
}
