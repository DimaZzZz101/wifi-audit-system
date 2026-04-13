/**
 * SessionReconTab  -  вкладка сканирования в сессии.
 * AP table with expandable clients, detail panel, STA table, search, settings, polling.
 */
import { useState, useEffect, useCallback, useRef, Fragment } from "react";
import {
  api,
  type ReconAP,
  type ReconSTA,
  type ReconScanItem,
  type NetworkInterface,
} from "../api/client";

const POLL_INTERVAL = 3000;
const RECON_CONTROLS_STORAGE_PREFIX = "recon.controls";

type ScanFormState = {
  selectedIface: string;
  scanMode: "continuous" | "timed";
  duration: number;
  bands: string;
};

const WPS_COLUMN_TITLE =
  "WPS: версия из IE (как в beacon). 0x10 = WPS 1.0, 0x20 = 2.0. On/Off - состояние из кадров; locked - блокировка PIN.";

const AP_COLUMNS: {
  key: keyof ReconAP | "security" | "wps";
  label: string;
  sortable: boolean;
  defaultVisible: boolean;
  columnTitle?: string;
}[] = [
  { key: "essid", label: "ESSID", sortable: true, defaultVisible: true },
  { key: "bssid", label: "BSSID", sortable: true, defaultVisible: true },
  { key: "channel", label: "CH", sortable: true, defaultVisible: true },
  { key: "band", label: "Band", sortable: true, defaultVisible: true },
  { key: "power", label: "PWR", sortable: true, defaultVisible: true },
  { key: "security", label: "Security", sortable: false, defaultVisible: true },
  { key: "wps", label: "WPS", sortable: false, defaultVisible: true, columnTitle: WPS_COLUMN_TITLE },
  { key: "client_count", label: "Clients", sortable: true, defaultVisible: true },
  { key: "beacons", label: "Beacons", sortable: true, defaultVisible: false },
  { key: "speed", label: "Speed", sortable: true, defaultVisible: false },
  { key: "first_seen", label: "First Seen", sortable: true, defaultVisible: false },
  { key: "last_seen", label: "Last Seen", sortable: true, defaultVisible: true },
];

function formatDateShort(iso: string | null): string {
  if (!iso) return "-";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return iso;
  }
}

function formatDateFull(iso: string | null): string {
  if (!iso) return "-";
  try {
    const d = new Date(iso);
    return d.toLocaleString("ru-RU");
  } catch {
    return iso;
  }
}

function signalStrength(power: number | null): { label: string; cls: string } {
  if (power == null) return { label: "?", cls: "recon-signal--unknown" };
  if (power >= -50) return { label: "Excellent", cls: "recon-signal--excellent" };
  if (power >= -60) return { label: "Good", cls: "recon-signal--good" };
  if (power >= -70) return { label: "Fair", cls: "recon-signal--fair" };
  return { label: "Weak", cls: "recon-signal--weak" };
}

function maskMac(mac: string): string {
  const parts = mac.split(":");
  if (parts.length !== 6) return mac;
  return `${parts[0]}:${parts[1]}:**:**:**:${parts[5]}`;
}

function maskSsid(ssid: string): string {
  if (ssid.length <= 2) return ssid[0] + "*****";
  return ssid.slice(0, 2) + "*****";
}

function displayEssid(ap: ReconAP, obfuscate = false): string {
  if (!ap.essid) return "<Hidden>";
  if (obfuscate) return maskSsid(ap.essid);
  return ap.essid;
}

function securityBadge(ap: ReconAP): string {
  return (
    ap.security_info?.display_security ??
    ap.security_info?.encryption ??
    "Open"
  );
}

/** WPS IE version: 0x10 -> 1.0, 0x20 -> 2.0 (BCD в поле версии Wi-Fi Alliance). */
function formatWpsVersionLabel(raw: string): string {
  const s = raw.trim().replace(/^v/i, "");
  const m = /^0x([0-9a-f]+)$/i.exec(s);
  if (m) {
    const n = parseInt(m[1], 16);
    if (n === 0x10) return "1.0";
    if (n === 0x20) return "2.0";
    const major = (n >> 4) & 0xf;
    const minor = n & 0xf;
    if (major <= 9 && minor <= 9) return `${major}.${minor}`;
    return `0x${m[1]}`;
  }
  if (/^\d+\.\d+$/.test(s)) return s;
  return raw.trim();
}

function formatWpsColumn(ap: ReconAP): string {
  const w = ap.wps;
  if (!w || typeof w !== "object") return "-";
  const enabled = Boolean(w.enabled);
  const versionRaw = w.version != null ? String(w.version) : "";
  const versionLabel = versionRaw ? formatWpsVersionLabel(versionRaw) : "";
  const locked = Boolean(w.locked);
  const sources = Array.isArray(w.enrichment_sources) ? (w.enrichment_sources as string[]) : [];
  const fromBeacon = sources.includes("tshark") || sources.includes("wash");
  if (!fromBeacon && !enabled && !versionRaw) return "-";
  if (!enabled && !versionRaw) return "Off";
  const parts: string[] = [];
  parts.push(enabled ? "On" : "Off");
  if (versionLabel) parts.push(`WPS ${versionLabel}`);
  parts.push(locked ? "locked" : "unlocked");
  return parts.join(", ");
}

function vulnerabilityLabel(v: string): string {
  const map: Record<string, string> = {
    pmkid_possible: "PMKID",
    deauth_possible: "Deauth",
    downgrade_possible: "Downgrade",
    legacy_wpa: "Legacy WPA",
    wep_crackable: "WEP",
    wps_brute_force: "WPS Brute",
  };
  return map[v] || v;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ScanControls({
  projectId,
  activeScan,
  form,
  onFormChange,
  onScanStarted,
  onScanStopped,
}: {
  projectId: number;
  activeScan: ReconScanItem | null;
  form: ScanFormState;
  onFormChange: (patch: Partial<ScanFormState>) => void;
  onScanStarted: (scan: ReconScanItem) => void;
  onScanStopped: () => void;
}) {
  const [interfaces, setInterfaces] = useState<NetworkInterface[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.hardware.networkInterfaces().then((ifaces) => {
      const wireless = ifaces.filter((i) => i.wireless);
      setInterfaces(wireless);
      if (wireless.length > 0 && !form.selectedIface) {
        onFormChange({ selectedIface: wireless[0].name });
      }
    });
  }, [form.selectedIface, onFormChange]);

  const handleStart = async () => {
    if (!form.selectedIface) {
      setError("Select an interface");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const result = await api.recon.start(projectId, {
        interface: form.selectedIface,
        scan_mode: form.scanMode,
        scan_duration: form.scanMode === "timed" ? form.duration : undefined,
        bands: form.bands,
      });
      onScanStarted({
        scan_id: result.scan_id,
        started_at: new Date().toISOString(),
        stopped_at: null,
        is_running: true,
        scan_mode: form.scanMode,
        scan_duration: form.scanMode === "timed" ? form.duration : null,
        interface: form.selectedIface,
        bands: form.bands,
        ap_count: 0,
        sta_count: 0,
        container_id: result.container_id,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start scan");
    } finally {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    if (!activeScan) return;
    setLoading(true);
    setError("");
    try {
      await api.recon.stop(projectId, activeScan.scan_id);
      onScanStopped();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to stop scan");
    } finally {
      setLoading(false);
    }
  };

  const isRunning = activeScan?.is_running ?? false;
  const timedDuration =
    activeScan?.scan_mode === "timed"
      ? Number(activeScan.scan_duration ?? form.duration ?? 0)
      : 0;
  const startedAtMs = activeScan?.started_at ? Date.parse(activeScan.started_at) : NaN;
  const elapsedSec = Number.isFinite(startedAtMs) ? Math.max(0, (Date.now() - startedAtMs) / 1000) : 0;
  const progressPct =
    timedDuration > 0 ? Math.min(100, Math.round((elapsedSec / timedDuration) * 100)) : 0;
  const etaSec = timedDuration > 0 ? Math.max(0, Math.ceil(timedDuration - elapsedSec)) : 0;

  return (
    <div className="recon-controls">
      <div className="recon-controls-row">
        <label className="recon-label">
          Interface
          <select
            className="recon-select"
            value={form.selectedIface}
            onChange={(e) => onFormChange({ selectedIface: e.target.value })}
            disabled={isRunning}
          >
            {interfaces.length === 0 && <option value="">No wireless interfaces</option>}
            {interfaces.map((i) => (
              <option key={i.name} value={i.name}>
                {i.name}
              </option>
            ))}
          </select>
        </label>
        <label className="recon-label">
          Mode
          <select
            className="recon-select"
            value={form.scanMode}
            onChange={(e) => onFormChange({ scanMode: e.target.value as "continuous" | "timed" })}
            disabled={isRunning}
          >
            <option value="continuous">Continuous</option>
            <option value="timed">Timed</option>
          </select>
        </label>
        {form.scanMode === "timed" && (
          <label className="recon-label">
            Duration (s)
            <input
              className="recon-input"
              type="number"
              min={5}
              max={3600}
              value={form.duration}
              onChange={(e) => onFormChange({ duration: Number(e.target.value) })}
              disabled={isRunning}
            />
          </label>
        )}
        <label className="recon-label">
          Bands
          <select
            className="recon-select"
            value={form.bands}
            onChange={(e) => onFormChange({ bands: e.target.value })}
            disabled={isRunning}
          >
            <option value="abg">All (2.4 + 5 GHz)</option>
            <option value="bg">2.4 GHz</option>
            <option value="a">5 GHz</option>
          </select>
        </label>
        <button
          type="button"
          className={`recon-btn ${isRunning ? "recon-btn--stop" : "recon-btn--start"}`}
          onClick={isRunning ? handleStop : handleStart}
          disabled={loading}
        >
          {loading ? "..." : isRunning ? "Stop Scan" : "Start Scan"}
        </button>
      </div>
      {error && <p className="recon-error">{error}</p>}
      {isRunning && (
        <>
          <div className="recon-status-bar">
            <span className="recon-status-dot recon-status-dot--active" />
            Scanning on <strong>{activeScan?.interface}</strong>
            {activeScan && ` | ${activeScan.ap_count} APs, ${activeScan.sta_count} STAs`}
          </div>
          {activeScan?.scan_mode === "timed" && timedDuration > 0 && (
            <div className="recon-progress-wrap">
              <div className="recon-progress-meta">
                <span>{progressPct}%</span>
                <span>{Math.ceil(elapsedSec)}s / {timedDuration}s</span>
                <span>ETA: {etaSec}s</span>
              </div>
              <div className="recon-progress-bar">
                <div className="recon-progress-fill" style={{ width: `${progressPct}%` }} />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function bandFilterFromScanBands(bands?: string): string | undefined {
  if (!bands || bands === "abg") return undefined;
  if (bands === "a") return "5";
  if (bands === "bg") return "2.4";
  return undefined;
}

function APTable({
  projectId,
  scanId,
  isRunning,
  search,
  visibleColumns,
  pageSize,
  onSelectAP,
  selectedBssid,
  scanBands,
  obfuscate,
}: {
  projectId: number;
  scanId: string;
  isRunning: boolean;
  search: string;
  visibleColumns: Set<string>;
  pageSize: number;
  onSelectAP: (ap: ReconAP) => void;
  selectedBssid: string | null;
  scanBands?: string;
  obfuscate?: boolean;
}) {
  const [aps, setAps] = useState<ReconAP[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [sortBy, setSortBy] = useState("power");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [expandedBssids, setExpandedBssids] = useState<Set<string>>(new Set());
  const [clientsCache, setClientsCache] = useState<Record<string, ReconSTA[]>>({});
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fetchClientsByBssid = useCallback(async (bssid: string) => {
    try {
      const data = await api.recon.stas(projectId, scanId, { bssid, limit: 200 });
      setClientsCache((prev) => ({ ...prev, [bssid]: data.items }));
    } catch {
      /* ignore */
    }
  }, [projectId, scanId]);


  const band = bandFilterFromScanBands(scanBands);

  const fetchAps = useCallback(async () => {
    try {
      const data = await api.recon.aps(projectId, scanId, {
        sort_by: sortBy,
        sort_dir: sortDir,
        limit: pageSize,
        offset: page * pageSize,
        band,
      });
      setAps(data.items);
      setTotal(data.total);
    } catch {
      /* ignore polling errors */
    }
  }, [projectId, scanId, sortBy, sortDir, page, pageSize, band]);

  useEffect(() => {
    fetchAps();
    if (isRunning) {
      pollRef.current = setInterval(fetchAps, POLL_INTERVAL);
      return () => {
        if (pollRef.current) clearInterval(pollRef.current);
      };
    }
  }, [fetchAps, isRunning]);

  const handleSort = (col: string) => {
    if (sortBy === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(col);
      setSortDir("desc");
    }
  };

  const toggleExpand = async (bssid: string) => {
    const next = new Set(expandedBssids);
    if (next.has(bssid)) {
      next.delete(bssid);
    } else {
      next.add(bssid);
      if (!clientsCache[bssid]) {
        await fetchClientsByBssid(bssid);
      }
    }
    setExpandedBssids(next);
  };

  useEffect(() => {
    if (!isRunning || expandedBssids.size === 0) return;
    const timer = setInterval(() => {
      for (const bssid of expandedBssids) {
        fetchClientsByBssid(bssid);
      }
    }, POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [isRunning, expandedBssids, fetchClientsByBssid]);

  const lowerSearch = search.toLowerCase();
  const filtered = search
    ? aps.filter(
        (ap) =>
          (ap.essid?.toLowerCase().includes(lowerSearch) ?? false) ||
          ap.bssid.toLowerCase().includes(lowerSearch) ||
          (ap.privacy?.toLowerCase().includes(lowerSearch) ?? false) ||
          (ap.security_info?.display_security?.toLowerCase().includes(lowerSearch) ?? false) ||
          (ap.security_info?.encryption?.toLowerCase().includes(lowerSearch) ?? false) ||
          formatWpsColumn(ap).toLowerCase().includes(lowerSearch)
      )
    : aps;

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const cols = AP_COLUMNS.filter((c) => visibleColumns.has(c.key));

  return (
    <div className="recon-table-wrap">
      <table className="recon-table">
        <thead>
          <tr>
            <th className="recon-th recon-th--expand" />
            {cols.map((col) => (
              <th
                key={col.key}
                className={`recon-th ${col.sortable ? "recon-th--sortable" : ""}`}
                onClick={col.sortable ? () => handleSort(col.key) : undefined}
                title={col.columnTitle}
              >
                {col.label}
                {sortBy === col.key && (
                  <span className="recon-sort-arrow">{sortDir === "asc" ? " \u25B2" : " \u25BC"}</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filtered.map((ap) => {
            const sig = signalStrength(ap.power);
            const isExpanded = expandedBssids.has(ap.bssid);
            const isSelected = selectedBssid === ap.bssid;
            return (
              <Fragment key={ap.bssid}>
                <tr
                  className={`recon-tr ${isSelected ? "recon-tr--selected" : ""}`}
                  onClick={() => onSelectAP(ap)}
                >
                  <td className="recon-td recon-td--expand">
                    {ap.client_count > 0 && (
                      <button
                        type="button"
                        className="recon-expand-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleExpand(ap.bssid);
                        }}
                      >
                        {isExpanded ? "\u25BC" : "\u25B6"}
                      </button>
                    )}
                  </td>
                  {cols.map((col) => (
                    <td key={col.key} className="recon-td">
                      {col.key === "essid" ? (
                        <span className={ap.is_hidden || !ap.essid ? "recon-hidden-ssid" : ""}>
                          {displayEssid(ap, obfuscate)}
                        </span>
                      ) : col.key === "bssid" ? (
                        <span className="recon-mono">{obfuscate ? maskMac(ap.bssid) : ap.bssid}</span>
                      ) : col.key === "power" ? (
                        <span className={`recon-signal ${sig.cls}`} title={sig.label}>
                          {ap.power ?? "-"} dBm
                        </span>
                      ) : col.key === "security" ? (
                        <span className="recon-security-badge">{securityBadge(ap)}</span>
                      ) : col.key === "wps" ? (
                        formatWpsColumn(ap)
                      ) : col.key === "first_seen" || col.key === "last_seen" ? (
                        formatDateShort(ap[col.key] as string | null)
                      ) : (
                        String(ap[col.key as keyof ReconAP] ?? "-")
                      )}
                    </td>
                  ))}
                </tr>
                {isExpanded && (clientsCache[ap.bssid] ?? []).length > 0 && (
                  <tr className="recon-tr--clients">
                    <td colSpan={cols.length + 1} className="recon-td--clients-wrap">
                      <table className="recon-clients-table">
                        <thead>
                          <tr>
                            <th>MAC</th>
                            <th>Power</th>
                            <th>Packets</th>
                            <th>Probed</th>
                            <th>Last Seen</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(clientsCache[ap.bssid] ?? []).map((sta) => (
                            <tr key={sta.mac}>
                              <td className="recon-mono">{obfuscate ? maskMac(sta.mac) : sta.mac}</td>
                              <td>{sta.power ?? "-"} dBm</td>
                              <td>{sta.packets}</td>
                              <td>
                                {obfuscate
                                  ? (sta.probed_essids.map((s) => maskSsid(s)).join(", ") || "-")
                                  : (sta.probed_essids.join(", ") || "-")}
                              </td>
                              <td>{formatDateShort(sta.last_seen)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
          {filtered.length === 0 && (
            <tr>
              <td colSpan={cols.length + 1} className="recon-td--empty">
                {isRunning ? "Scanning..." : "No access points found"}
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <div className="recon-pagination">
        <button
          type="button"
          className="recon-page-btn"
          disabled={page === 0}
          onClick={() => setPage((p) => Math.max(0, p - 1))}
        >
          Prev
        </button>
        <span className="recon-page-info">
          Page {page + 1} of {totalPages} ({total} APs)
        </span>
        <button
          type="button"
          className="recon-page-btn"
          disabled={page >= totalPages - 1}
          onClick={() => setPage((p) => p + 1)}
        >
          Next
        </button>
      </div>
    </div>
  );
}

function APDetailPanel({
  projectId,
  scanId,
  bssid,
  onClose,
  obfuscate,
  onPlanAudit,
}: {
  projectId: number;
  scanId: string;
  bssid: string;
  onClose: () => void;
  obfuscate?: boolean;
  onPlanAudit?: () => void;
}) {
  const [ap, setAp] = useState<ReconAP | null>(null);
  const [loading, setLoading] = useState(true);
  const [planningAudit, setPlanningAudit] = useState(false);

  useEffect(() => {
    setLoading(true);
    api.recon
      .apDetail(projectId, scanId, bssid)
      .then(setAp)
      .catch(() => setAp(null))
      .finally(() => setLoading(false));
  }, [projectId, scanId, bssid]);

  const handlePlanAudit = async () => {
    setPlanningAudit(true);
    try {
      await api.audit.createPlan(projectId, bssid, scanId);
      if (onPlanAudit) onPlanAudit();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to create audit plan");
    } finally {
      setPlanningAudit(false);
    }
  };

  if (loading) return <div className="recon-detail-panel"><p>Loading...</p></div>;
  if (!ap) return <div className="recon-detail-panel"><p>AP not found</p></div>;

  const vulns = ap.security_info?.vulnerabilities ?? [];
  const tagged = ap.tagged_params ?? {};
  const wps = ap.wps as Record<string, unknown> | null;

  return (
    <div className="recon-detail-panel">
      <div className="recon-detail-header">
        <h3>{displayEssid(ap, obfuscate)}</h3>
        <button type="button" className="recon-detail-close" onClick={onClose}>
          &times;
        </button>
      </div>
      <div className="recon-detail-body">
        <div className="recon-detail-section">
          <h4>General</h4>
          <dl className="recon-dl">
            <dt>BSSID</dt><dd className="recon-mono">{obfuscate ? maskMac(ap.bssid) : ap.bssid}</dd>
            <dt>Channel</dt><dd>{ap.channel ?? "-"}</dd>
            <dt>Band</dt><dd>{ap.band ?? "-"} GHz</dd>
            <dt>Power</dt><dd>{ap.power ?? "-"} dBm</dd>
            <dt>Speed</dt><dd>{ap.speed ?? "-"} Mbps</dd>
            <dt>Beacons</dt><dd>{ap.beacons}</dd>
            <dt>First Seen</dt><dd>{formatDateFull(ap.first_seen)}</dd>
            <dt>Last Seen</dt><dd>{formatDateFull(ap.last_seen)}</dd>
          </dl>
        </div>

        <div className="recon-detail-section">
          <h4>Security</h4>
          <dl className="recon-dl">
            <dt>Encryption</dt><dd>{ap.security_info?.display_security ?? ap.security_info?.encryption ?? ap.privacy ?? "Open"}</dd>
            <dt>Cipher</dt><dd>{ap.security_info?.cipher ?? ap.cipher ?? "-"}</dd>
            <dt>AKM</dt><dd>{ap.security_info?.akm ?? ap.auth ?? "-"}</dd>
            <dt>PMF</dt><dd>{ap.security_info?.pmf ?? "-"}</dd>
          </dl>
          {vulns.length > 0 && (
            <div className="recon-vulns">
              <strong>Potential vectors:</strong>
              <div className="recon-vuln-badges">
                {vulns.map((v) => (
                  <span key={v} className="recon-vuln-badge">{vulnerabilityLabel(v)}</span>
                ))}
              </div>
            </div>
          )}
          <button
            type="button"
            className="recon-plan-audit-btn"
            onClick={handlePlanAudit}
            disabled={planningAudit}
          >
            {planningAudit ? "Planning..." : "Plan Audit"}
          </button>
        </div>

        {wps && (
          <div className="recon-detail-section">
            <h4>WPS</h4>
            <dl className="recon-dl">
              <dt>Enabled</dt><dd>{(wps.enabled as boolean) ? "Yes" : "No"}</dd>
              <dt>Locked</dt><dd>{(wps.locked as boolean) ? "Yes" : "No"}</dd>
              {wps.version != null && String(wps.version) !== "" ? (
                <>
                  <dt>Version</dt>
                  <dd title="WPS version octet from beacon (0x10 = 1.0, 0x20 = 2.0)">
                    {formatWpsVersionLabel(String(wps.version))}
                    <span style={{ opacity: 0.75 }}> ({String(wps.version)})</span>
                  </dd>
                </>
              ) : null}
              {wps.device_name ? <><dt>Device</dt><dd>{String(wps.device_name)}</dd></> : null}
              {wps.manufacturer ? <><dt>Manufacturer</dt><dd>{String(wps.manufacturer)}</dd></> : null}
              {wps.model_name ? <><dt>Model</dt><dd>{String(wps.model_name)}</dd></> : null}
            </dl>
          </div>
        )}

        {Object.keys(tagged).length > 0 && (
          <div className="recon-detail-section">
            <h4>Tagged Parameters</h4>
            <pre className="recon-detail-json">{JSON.stringify(tagged, null, 2)}</pre>
          </div>
        )}

        {ap.clients && ap.clients.length > 0 && (
          <div className="recon-detail-section">
            <h4>Connected Clients ({ap.clients.length})</h4>
            <table className="recon-clients-table">
              <thead>
                <tr>
                  <th>MAC</th>
                  <th>Power</th>
                  <th>Packets</th>
                  <th>Last Seen</th>
                </tr>
              </thead>
              <tbody>
                {ap.clients.map((sta) => (
                  <tr key={sta.mac}>
                    <td className="recon-mono">{obfuscate ? maskMac(sta.mac) : sta.mac}</td>
                    <td>{sta.power ?? "-"} dBm</td>
                    <td>{sta.packets}</td>
                    <td>{formatDateShort(sta.last_seen)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function ScanHistory({
  scans,
  activeScanId,
  onSelect,
}: {
  scans: ReconScanItem[];
  activeScanId: string | null;
  onSelect: (scan: ReconScanItem) => void;
}) {
  if (scans.length === 0) return null;
  return (
    <div className="recon-history">
      <h4 className="recon-history-title">Scan History</h4>
      <div className="recon-history-list">
        {scans.map((s) => (
          <button
            key={s.scan_id}
            type="button"
            className={`recon-history-item ${s.scan_id === activeScanId ? "recon-history-item--active" : ""}`}
            onClick={() => onSelect(s)}
          >
            <span className="recon-history-mode">{s.scan_mode}</span>
            <span className="recon-history-time">{formatDateFull(s.started_at)}</span>
            <span className="recon-history-stats">{s.ap_count} AP / {s.sta_count} STA</span>
            {s.is_running && <span className="recon-status-dot recon-status-dot--active" />}
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main ReconTab
// ---------------------------------------------------------------------------

export default function SessionReconTab({ projectId, obfuscationEnabled = false, onPlanAudit }: { projectId: number; obfuscationEnabled?: boolean; onPlanAudit?: () => void }) {
  const [activeScan, setActiveScan] = useState<ReconScanItem | null>(null);
  const [scans, setScans] = useState<ReconScanItem[]>([]);
  const [scanForm, setScanForm] = useState<ScanFormState>({
    selectedIface: "",
    scanMode: "continuous",
    duration: 60,
    bands: "abg",
  });
  const [search, setSearch] = useState("");
  const [pageSize, setPageSize] = useState(25);
  const [showSettings, setShowSettings] = useState(false);
  const [selectedAP, setSelectedAP] = useState<ReconAP | null>(null);
  const [visibleColumns, setVisibleColumns] = useState<Set<string>>(
    new Set(AP_COLUMNS.filter((c) => c.defaultVisible).map((c) => c.key))
  );
  const pollStatusRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const storageKey = `${RECON_CONTROLS_STORAGE_PREFIX}.${projectId}`;

  const updateScanForm = useCallback((patch: Partial<ScanFormState>) => {
    setScanForm((prev) => ({ ...prev, ...patch }));
  }, []);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) return;
      const parsed = JSON.parse(raw) as Partial<ScanFormState>;
      setScanForm((prev) => ({
        selectedIface: typeof parsed.selectedIface === "string" ? parsed.selectedIface : prev.selectedIface,
        scanMode: parsed.scanMode === "timed" || parsed.scanMode === "continuous" ? parsed.scanMode : prev.scanMode,
        duration: typeof parsed.duration === "number" && parsed.duration >= 5 ? parsed.duration : prev.duration,
        bands: typeof parsed.bands === "string" ? parsed.bands : prev.bands,
      }));
    } catch {
      /* ignore malformed storage */
    }
  }, [storageKey]);

  useEffect(() => {
    localStorage.setItem(storageKey, JSON.stringify(scanForm));
  }, [storageKey, scanForm]);

  useEffect(() => {
    api.recon.scans(projectId).then((scansList) => {
      setScans(scansList);
      const running = scansList.find((s) => s.is_running);
      if (running) {
        setActiveScan(running);
        setScanForm((prev) => ({
          ...prev,
          selectedIface: running.interface || prev.selectedIface,
          scanMode: running.scan_mode === "timed" ? "timed" : "continuous",
          bands: running.bands || prev.bands,
          duration: running.scan_mode === "timed" && typeof running.scan_duration === "number"
            ? running.scan_duration
            : prev.duration,
        }));
      } else if (scansList.length > 0) {
        setActiveScan(scansList[0]);
      }
    });
  }, [projectId]);

  useEffect(() => {
    if (!activeScan?.is_running || !activeScan?.scan_id) {
      if (pollStatusRef.current) clearInterval(pollStatusRef.current);
      return;
    }
    pollStatusRef.current = setInterval(async () => {
      try {
        const status = await api.recon.status(projectId, activeScan.scan_id);
        setActiveScan(status);
        setScanForm((prev) => ({
          ...prev,
          selectedIface: status.interface || prev.selectedIface,
          scanMode: status.scan_mode === "timed" ? "timed" : "continuous",
          bands: status.bands || prev.bands,
          duration: status.scan_mode === "timed" && typeof status.scan_duration === "number"
            ? status.scan_duration
            : prev.duration,
        }));
        if (!status.is_running) {
          if (pollStatusRef.current) clearInterval(pollStatusRef.current);
          const updated = await api.recon.scans(projectId);
          setScans(updated);
        }
      } catch {
        /* ignore */
      }
    }, POLL_INTERVAL);
    return () => {
      if (pollStatusRef.current) clearInterval(pollStatusRef.current);
    };
  }, [projectId, activeScan?.scan_id, activeScan?.is_running]);

  const handleScanStarted = (scan: ReconScanItem) => {
    setActiveScan(scan);
    setScans((prev) => [scan, ...prev]);
    setScanForm((prev) => ({
      ...prev,
      selectedIface: scan.interface || prev.selectedIface,
      scanMode: scan.scan_mode === "timed" ? "timed" : "continuous",
      bands: scan.bands || prev.bands,
      duration: scan.scan_mode === "timed" && typeof scan.scan_duration === "number"
        ? scan.scan_duration
        : prev.duration,
    }));
    setSelectedAP(null);
  };

  const handleScanStopped = async () => {
    if (activeScan) {
      setActiveScan({ ...activeScan, is_running: false });
    }
    const updated = await api.recon.scans(projectId);
    setScans(updated);
  };

  const handleSelectScan = (scan: ReconScanItem) => {
    setActiveScan(scan);
    setSelectedAP(null);
  };

  const toggleColumn = (key: string) => {
    setVisibleColumns((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  return (
    <div className="recon-tab">
      <ScanControls
        projectId={projectId}
        activeScan={activeScan}
        form={scanForm}
        onFormChange={updateScanForm}
        onScanStarted={handleScanStarted}
        onScanStopped={handleScanStopped}
      />

      <div className="recon-toolbar">
        <input
          type="text"
          className="recon-search"
          placeholder="Search ESSID, BSSID, security..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div className="recon-toolbar-right">
          <label className="recon-label recon-label--inline">
            Rows:
            <select
              className="recon-select recon-select--sm"
              value={pageSize}
              onChange={(e) => setPageSize(Number(e.target.value))}
            >
              {[10, 25, 50, 100].map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="recon-btn recon-btn--settings"
            onClick={() => setShowSettings(!showSettings)}
          >
            Columns
          </button>
        </div>
      </div>

      {showSettings && (
        <div className="recon-settings-dropdown">
          {AP_COLUMNS.map((col) => (
            <label key={col.key} className="recon-column-toggle">
              <input
                type="checkbox"
                checked={visibleColumns.has(col.key)}
                onChange={() => toggleColumn(col.key)}
              />
              {col.label}
            </label>
          ))}
        </div>
      )}

      <div className="recon-content">
        <div className="recon-main">
          {activeScan ? (
            <APTable
              projectId={projectId}
              scanId={activeScan.scan_id}
              isRunning={activeScan.is_running}
              search={search}
              visibleColumns={visibleColumns}
              pageSize={pageSize}
              onSelectAP={(ap) => setSelectedAP(ap)}
              selectedBssid={selectedAP?.bssid ?? null}
              scanBands={activeScan.bands}
              obfuscate={obfuscationEnabled}
            />
          ) : (
            <div className="recon-empty">
              <p>No scans yet. Configure and start a scan above.</p>
            </div>
          )}
        </div>
      </div>

      {selectedAP && activeScan && (
        <>
          <div className="recon-detail-backdrop" onClick={() => setSelectedAP(null)} />
          <div className="recon-detail-overlay">
            <APDetailPanel
              projectId={projectId}
              scanId={activeScan.scan_id}
              bssid={selectedAP.bssid}
              onClose={() => setSelectedAP(null)}
              obfuscate={obfuscationEnabled}
              onPlanAudit={onPlanAudit}
            />
          </div>
        </>
      )}

      <ScanHistory
        scans={scans}
        activeScanId={activeScan?.scan_id ?? null}
        onSelect={handleSelectScan}
      />
    </div>
  );
}
