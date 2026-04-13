/** Проекты аудита Wi-Fi  -  логическая группировка сессий и задач. */
import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { api, type ProjectItem } from "../api/client";
import { useActiveProject } from "../contexts/ActiveProjectContext";

type ProjectsTab = "manage" | "reports";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function statusLabel(status: string): string {
  if (status === "active") return "Активен";
  if (status === "inactive") return "Неактивен";
  if (status === "archived") return "Архив";
  return status;
}

export default function ProjectsPage() {
  const [activeTab, setActiveTab] = useState<ProjectsTab>("manage");
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [createName, setCreateName] = useState("");
  const [creating, setCreating] = useState(false);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [activatingId, setActivatingId] = useState<number | null>(null);
  const [menuOpenId, setMenuOpenId] = useState<number | null>(null);
  const [menuPosition, setMenuPosition] = useState<{ top: number; right: number } | null>(null);
  const { activeProject, setActiveProject } = useActiveProject();
  const navigate = useNavigate();

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const list = await api.projects.list();
      setProjects(list);
      if (activeProject && !list.some((p) => p.id === activeProject.id)) {
        setActiveProject(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки проектов");
    } finally {
      setLoading(false);
    }
  }, [activeProject, setActiveProject]);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    const name = createName.trim();
    if (!name) return;
    setCreating(true);
    setError("");
    try {
      await api.projects.create(name);
      setCreateName("");
      setShowCreateForm(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка создания проекта");
    } finally {
      setCreating(false);
    }
  };

  const handleOpen = async (p: ProjectItem) => {
    setMenuOpenId(null);
    setMenuPosition(null);
    setError("");
    try {
      if (p.status === "inactive") {
        setActivatingId(p.id);
        await api.projects.update(p.id, { status: "active" });
        setActivatingId(null);
      }
      setActiveProject({ id: p.id, slug: p.slug, name: p.name });
      navigate("/projects/workspace");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
      setActivatingId(null);
    }
  };

  const handleActivate = async (p: ProjectItem) => {
    setMenuOpenId(null);
    setMenuPosition(null);
    setActivatingId(p.id);
    setError("");
    try {
      await api.projects.update(p.id, { status: "active" });
      setActiveProject({ id: p.id, slug: p.slug, name: p.name });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка активации проекта");
    } finally {
      setActivatingId(null);
    }
  };

  const handleDeactivate = async (p: ProjectItem) => {
    setMenuOpenId(null);
    setMenuPosition(null);
    setActivatingId(p.id);
    setError("");
    try {
      await api.projects.update(p.id, { status: "inactive" });
      if (activeProject?.id === p.id) {
        setActiveProject(null);
      }
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка деактивации проекта");
    } finally {
      setActivatingId(null);
    }
  };

  const handleDelete = async (id: number) => {
    setMenuOpenId(null);
    setMenuPosition(null);
    setDeletingId(id);
    setError("");
    try {
      await api.projects.delete(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка удаления проекта");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="panel-page sessions-page">
      <div className="sessions-tabs">
        <button
          type="button"
          className={`sessions-tab ${activeTab === "manage" ? "is-active" : ""}`}
          onClick={() => setActiveTab("manage")}
        >
          Manage
        </button>
        <button
          type="button"
          className={`sessions-tab ${activeTab === "reports" ? "is-active" : ""}`}
          onClick={() => setActiveTab("reports")}
        >
          Reports
        </button>
      </div>

      {activeTab === "manage" && (
        <>
          <div className="panel-card sessions-tile sessions-tile-header">
            <div className="sessions-tile-header-content">
              <div>
                <h2 className="sessions-title">Audit Projects</h2>
                <p className="sessions-desc">
                  Проект аудита - контейнер для проведения аудита Wi-Fi. В рамках проекта собираются дампы трафика, handshake/PMKID, логи и результаты. В дальнейшем из проекта можно сформировать отчёт.
                </p>
              </div>
              <div className="sessions-tile-actions">
                <button
                  type="button"
                  className="sessions-btn-create"
                  onClick={() => setShowCreateForm(true)}
                >
                  Создать проект
                </button>
                <button
                  type="button"
                  className="sessions-btn-refresh"
                  onClick={() => load()}
                  disabled={loading}
                >
                  Обновить
                </button>
              </div>
            </div>

            {showCreateForm && (
              <form className="sessions-create-form" onSubmit={handleCreate}>
                <input
                  id="sessions-create-name"
                  name="projectName"
                  type="text"
                  placeholder="Название проекта"
                  value={createName}
                  onChange={(e) => setCreateName(e.target.value)}
                  autoFocus
                  maxLength={256}
                />
                <div className="sessions-create-actions">
                  <button type="submit" disabled={creating || !createName.trim()}>
                    {creating ? "Создание..." : "Создать"}
                  </button>
                  <button
                    type="button"
                    className="sessions-btn-cancel"
                    onClick={() => {
                      setShowCreateForm(false);
                      setCreateName("");
                    }}
                  >
                    Отмена
                  </button>
                </div>
              </form>
            )}

            {error && <p className="error">{error}</p>}

            {loading && <p className="sessions-loading">Загрузка...</p>}
            {!loading && projects.length === 0 && (
              <p className="sessions-empty">
                Нет проектов. Нажмите "Создать проект", чтобы начать аудит.
              </p>
            )}
          </div>

          {!loading && projects.length > 0 && (
            <div className="panel-card sessions-tile sessions-tile-list">
              <div className="sessions-table-wrap">
                <table className="sessions-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Status</th>
                      <th>Name</th>
                      <th>Created</th>
                      <th>Type</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {projects.map((p) => (
                      <tr key={p.id}>
                        <td className="sessions-id">{p.slug}</td>
                        <td className="sessions-status">
                          <span className="sessions-status-inner">
                            <span
                              className={`sessions-status-dot sessions-status-dot--${p.status}`}
                              title={statusLabel(p.status)}
                            />
                            <span className="sessions-status-text">{statusLabel(p.status)}</span>
                          </span>
                        </td>
                        <td className="sessions-name">{p.name}</td>
                        <td className="sessions-created">{formatDate(p.created_at)}</td>
                        <td className="sessions-type">{p.session_type}</td>
                        <td className="sessions-actions">
                          <div className="sessions-actions-wrap">
                            <button
                              type="button"
                              className="sessions-btn-open"
                              onClick={() => handleOpen(p)}
                              disabled={activatingId === p.id}
                            >
                              {activatingId === p.id ? "..." : "Открыть"}
                            </button>
                            <button
                              type="button"
                              className="sessions-btn-menu"
                              aria-label="Действия"
                              aria-expanded={menuOpenId === p.id}
                              onClick={(e) => {
                                if (menuOpenId === p.id) {
                                  setMenuOpenId(null);
                                  setMenuPosition(null);
                                } else {
                                  const rect = (e.currentTarget as HTMLButtonElement).getBoundingClientRect();
                                  setMenuPosition({
                                    top: rect.bottom + 4,
                                    right: window.innerWidth - rect.right,
                                  });
                                  setMenuOpenId(p.id);
                                }
                              }}
                            >
                              ...
                            </button>
                            {menuOpenId === p.id && menuPosition && (
                              <>
                                <div
                                  className="sessions-menu-backdrop"
                                  onClick={() => {
                                    setMenuOpenId(null);
                                    setMenuPosition(null);
                                  }}
                                  aria-hidden
                                />
                                <div
                                  className="sessions-menu"
                                  style={{
                                    top: menuPosition.top,
                                    right: menuPosition.right,
                                  }}
                                >
                                  {p.status === "inactive" ? (
                                    <button
                                      type="button"
                                      className="sessions-menu-item"
                                      onClick={() => handleActivate(p)}
                                      disabled={activatingId === p.id}
                                    >
                                      {activatingId === p.id ? "Активация..." : "Активировать"}
                                    </button>
                                  ) : p.status === "active" ? (
                                    <>
                                      {activeProject?.id !== p.id && (
                                        <button
                                          type="button"
                                          className="sessions-menu-item"
                                          onClick={() => {
                                            setMenuOpenId(null);
                                            setMenuPosition(null);
                                            setActiveProject({ id: p.id, slug: p.slug, name: p.name });
                                          }}
                                        >
                                          Выбрать
                                        </button>
                                      )}
                                      <button
                                        type="button"
                                        className="sessions-menu-item"
                                        onClick={() => handleDeactivate(p)}
                                        disabled={activatingId === p.id}
                                      >
                                        {activatingId === p.id ? "Деактивация..." : "Деактивировать"}
                                      </button>
                                    </>
                                  ) : null}
                                  <button
                                    type="button"
                                    className="sessions-menu-item sessions-menu-item--danger"
                                    onClick={() => handleDelete(p.id)}
                                    disabled={deletingId === p.id}
                                  >
                                    {deletingId === p.id ? "Удаление..." : "Удалить"}
                                  </button>
                                </div>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {activeTab === "reports" && (
        <div className="panel-card sessions-tile sessions-tile-reports">
          <h2 className="sessions-title">Reports</h2>
          <p className="sessions-desc sessions-desc-placeholder">
            Раздел отчётов будет доступен в следующих версиях. Здесь можно будет формировать отчёты по проектам аудита.
          </p>
        </div>
      )}
    </div>
  );
}
