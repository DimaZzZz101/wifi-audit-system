/** Modules page: installed and available modules with install/remove actions. */
import { useState, useEffect, useCallback } from "react";
import {
  api,
  type InstalledModule,
  type AvailableModule,
  type PluginContainer,
} from "../api/client";

function isRunnable(container: PluginContainer | null | undefined): boolean {
  return Boolean(container?.image);
}

export default function ModulesPage() {
  const [installed, setInstalled] = useState<InstalledModule[]>([]);
  const [available, setAvailable] = useState<AvailableModule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [running, setRunning] = useState<string | null>(null);
  const [installing, setInstalling] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);

  const loadModules = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [inst, av] = await Promise.all([
        api.modules.installed(),
        api.modules.available(),
      ]);
      setInstalled(inst);
      setAvailable(av);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки модулей");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadModules();
  }, [loadModules]);

  async function handleRun(module: InstalledModule) {
    const image = module.container?.image;
    if (!image) return;
    setRunning(module.id);
    try {
      await api.containers.create({
        image,
        name: `module-${module.id}-${Date.now().toString(36)}`,
        container_type: module.container?.type ?? "instrumental",
        command: module.container?.default_command ?? undefined,
        detach: true,
      });
      setRunning(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка запуска контейнера");
      setRunning(null);
    }
  }

  async function handleInstall(av: AvailableModule) {
    const url = av.download_url;
    if (!url) {
      setError("У модуля нет ссылки на скачивание");
      return;
    }
    setInstalling(av.id);
    setError("");
    try {
      await api.modules.download(url);
      await api.modules.install(av.checksum ?? undefined);
      await loadModules();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка установки модуля");
    } finally {
      setInstalling(null);
    }
  }

  async function handleRemove(module: InstalledModule) {
    if (!module.removable) return;
    setRemoving(module.id);
    setError("");
    try {
      await api.modules.remove(module.id);
      await loadModules();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка удаления модуля");
    } finally {
      setRemoving(null);
    }
  }

  if (loading) {
    return (
      <div className="panel-page">
        <p>Загрузка модулей...</p>
      </div>
    );
  }

  return (
    <div className="panel-page">
      <div className="panel-card">
        <h2 className="panel-card-title">Modules</h2>
        <p className="panel-card-desc">
          Здесь отображаются установленные модули и каталог доступных для установки. Можно скачать, установить
          или удалить модуль (кроме встроенных). Для модулей с контейнером доступен быстрый запуск.
          Образ контейнера должен присутствовать в реестре WiFi Audit (Containers -&gt; Registry).
        </p>
      </div>
      {error && <p className="error">{error}</p>}

      <h3 className="dashboard-section-title">Installed Modules</h3>
      <div className="panel-cards module-cards">
        {installed.map((module) => (
          <div key={module.id} className="panel-card module-card">
            <h3 className="panel-card-title">
              {module.name}
              {module.system && <span className="module-badge module-badge-system">system</span>}
            </h3>
            {module.version && <span className="module-version">v{module.version}</span>}
            {module.description && (
              <p className="panel-card-desc">{module.description}</p>
            )}
            {module.provides.length > 0 && (
              <p className="module-provides">Возможности: {module.provides.join(", ")}</p>
            )}
            <div className="module-actions">
              {isRunnable(module.container) && (
                <button
                  type="button"
                  className="panel-btn panel-btn-primary"
                  disabled={running === module.id}
                  onClick={() => handleRun(module)}
                >
                  {running === module.id ? "Запуск..." : "Запустить контейнер"}
                </button>
              )}
              {module.container?.image && (
                <span className="module-image">{module.container.image}</span>
              )}
              {module.removable && (
                <button
                  type="button"
                  className="panel-btn panel-btn-danger"
                  disabled={removing === module.id}
                  onClick={() => handleRemove(module)}
                >
                  {removing === module.id ? "Удаление..." : "Удалить модуль"}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {available.length > 0 && (
        <>
          <h3 className="dashboard-section-title">Available Modules</h3>
          <p className="panel-card-desc">
            Модули из удаленного каталога (<code>MODULES_INDEX_URL</code>). Нажмите "Установить" для скачивания и установки.
          </p>
          <div className="panel-cards module-cards">
            {available.map((av) => {
              const alreadyInstalled = installed.some((m) => m.id === av.id);
              return (
                <div key={av.id} className="panel-card module-card">
                  <h3 className="panel-card-title">{av.name}</h3>
                  {av.version && <span className="module-version">v{av.version}</span>}
                  {av.description && <p className="panel-card-desc">{av.description}</p>}
                  {av.author && <p className="module-author">Автор: {av.author}</p>}
                  <div className="module-actions">
                    <button
                      type="button"
                      className="panel-btn panel-btn-primary"
                      disabled={alreadyInstalled || installing === av.id || !av.download_url}
                      onClick={() => handleInstall(av)}
                    >
                      {installing === av.id
                        ? "Установка..."
                        : alreadyInstalled
                          ? "Установлен"
                          : "Установить"}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {available.length === 0 && (
        <p className="dashboard-note">
          Каталог доступных модулей пуст. Укажите <code>MODULES_INDEX_URL</code> в настройках API,
          чтобы загружать список модулей для установки.
        </p>
      )}
    </div>
  );
}
