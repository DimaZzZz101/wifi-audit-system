/** Dashboard (Статус): плитки по системным контейнерам (CPU, RAM) и хосту (CPU, RAM, DISK). Данные - cAdvisor. */
import { useState, useEffect, useCallback } from "react";
import { api, type SystemMetrics, type ContainerMetrics } from "../api/client";

const METRICS_INTERVAL_MS = 10000;

function formatPercent(value: number | null): string {
  if (value == null) return "-";
  return `${value.toFixed(1)}%`;
}

function formatMb(value: number | null): string {
  if (value == null) return "-";
  return `${value.toFixed(0)} MB`;
}

/** Короткое отображаемое имя системного контейнера (db, api, frontend, tool-manager). */
function containerDisplayName(name: string): string {
  const n = name.toLowerCase();
  if (n.includes("db") || n.includes("-db")) return "DB";
  if (n.includes("api")) return "API";
  if (n.includes("frontend")) return "Frontend";
  if (n.includes("tool-manager") || n.includes("tool_manager")) return "Tool Manager";
  return name;
}

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadMetrics = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api.metrics.system();
      setMetrics(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки метрик");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadMetrics();
    const interval = setInterval(loadMetrics, METRICS_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [loadMetrics]);

  if (loading && !metrics) {
    return (
      <div className="panel-page dashboard-page">
        <p>Загрузка метрик...</p>
      </div>
    );
  }

  if (error && !metrics) {
    return (
      <div className="panel-page dashboard-page">
        <p className="error">{error}</p>
        <button type="button" onClick={loadMetrics}>Повторить</button>
      </div>
    );
  }

  const containers = metrics?.containers ?? [];
  const host = metrics?.host;

  return (
    <div className="panel-page dashboard-page">
      <h1 className="dashboard-page-title">Dashboard</h1>
      <p className="dashboard-page-desc">
        Метрики системных контейнеров и хоста. Данные собираются cAdvisor, обновление каждые {METRICS_INTERVAL_MS / 1000} с.
      </p>

      {/* Плитка хоста: CPU, RAM, DISK */}
      <h2 className="dashboard-section-title">Host</h2>
      <div className="dashboard-tiles dashboard-tiles-single">
        <div className="dashboard-tile dashboard-tile-host">
          <h3 className="dashboard-tile-title">Host System</h3>
          <p className="dashboard-tile-desc">CPU, RAM и диск всей машины</p>
          <div className="dashboard-tile-metrics">
            <div className="dashboard-metric">
              <span className="dashboard-metric-value">{host ? formatPercent(host.cpu_percent) : "-"}</span>
              <span className="dashboard-metric-label">CPU</span>
            </div>
            <div className="dashboard-metric">
              <span className="dashboard-metric-value">{host ? formatPercent(host.memory_percent) : "-"}</span>
              <span className="dashboard-metric-label">MEM %</span>
            </div>
            <div className="dashboard-metric">
              <span className="dashboard-metric-value">
                {host ? `${formatMb(host.memory_used_mb)} / ${formatMb(host.memory_limit_mb ?? null)}` : "-"}
              </span>
              <span className="dashboard-metric-label">RAM</span>
            </div>
            <div className="dashboard-metric">
              <span className="dashboard-metric-value">{host ? formatPercent(host.disk_percent) : "-"}</span>
              <span className="dashboard-metric-label">DISK %</span>
            </div>
            <div className="dashboard-metric">
              <span className="dashboard-metric-value">
                {host ? `${host.disk_used_gb.toFixed(1)} / ${host.disk_total_gb.toFixed(1)} GB` : "-"}
              </span>
              <span className="dashboard-metric-label">DISK</span>
            </div>
          </div>
        </div>
      </div>

      {/* Плитки по каждому системному контейнеру: CPU, RAM */}
      <h2 className="dashboard-section-title">System Containers</h2>
      {containers.length > 0 ? (
        <div className="dashboard-tiles dashboard-tiles-containers">
          {containers.map((c: ContainerMetrics) => (
            <div key={c.id} className="dashboard-tile dashboard-tile-container">
              <h3 className="dashboard-tile-title">{containerDisplayName(c.name)}</h3>
              <p className="dashboard-tile-desc">{c.name}</p>
              <div className="dashboard-tile-metrics">
                <div className="dashboard-metric">
                  <span className="dashboard-metric-value">{formatPercent(c.cpu_percent)}</span>
                  <span className="dashboard-metric-label">CPU</span>
                </div>
                <div className="dashboard-metric">
                  <span className="dashboard-metric-value">{formatPercent(c.memory_percent)}</span>
                  <span className="dashboard-metric-label">MEM %</span>
                </div>
                <div className="dashboard-metric">
                  <span className="dashboard-metric-value">
                    {formatMb(c.memory_used_mb)} / {formatMb(c.memory_limit_mb ?? null)}
                  </span>
                  <span className="dashboard-metric-label">RAM</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="dashboard-note dashboard-note-warning">
          Список системных контейнеров (db, api, frontend, tool-manager) пуст. Проверьте cAdvisor и <code>CADVISOR_URL</code>.
        </p>
      )}

      <p className="dashboard-note">
        Отображение реализовано плагином <strong>System Metrics</strong> (capability: status_tiles). Метрики по контейнерам - только CPU и RAM; диск - на уровне хоста.
      </p>
    </div>
  );
}
