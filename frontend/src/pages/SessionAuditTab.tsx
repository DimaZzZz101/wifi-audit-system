/** Audit tab: plan list, pipeline view, job config/start/stop/skip/restart, status polling. */
import { useState, useEffect, useCallback, useRef } from "react";
import {
  api,
  type AuditPlanItem,
  type AuditPlanDetail,
  type AuditJobItem,
  type DictionaryItem,
  type NetworkInterface,
  type ReconSTA,
} from "../api/client";

const POLL_INTERVAL = 3000;

const ATTACK_LABELS: Record<string, string> = {
  handshake_capture: "Handshake Capture",
  pmkid_capture: "PMKID Capture",
  wps_pixie: "WPS Pixie-Dust",
  dragonshift: "DragonShift",
  psk_crack: "PSK Crack",
  dos: "DoS (Bl0ck)",
  deauth: "Deauthentication",
};

const ATTACK_DESCRIPTIONS: Record<string, string> = {
  handshake_capture: "Captures WPA/WPA2 4-way handshake via deauthentication",
  pmkid_capture: "Captures PMKID from AP without client deauthentication",
  wps_pixie: "WPS Pixie-Dust offline brute-force attack",
  dragonshift: "WPA2/WPA3 transition mode downgrade (requires 2 interfaces)",
  psk_crack: "Cracks captured handshake/PMKID using wordlist",
  dos: "Denial of Service via mdk4 beacon flood",
  deauth: "Sends deauthentication frames to disconnect clients",
};

const NEEDS_INTERFACE = new Set([
  "handshake_capture", "pmkid_capture", "wps_pixie",
  "dragonshift", "dos", "deauth",
]);

const NEEDS_DICTIONARY = new Set(["psk_crack"]);

const NEEDS_CLIENT_TARGET = new Set(["handshake_capture", "deauth", "dragonshift"]);

const MDK4_MODES: { value: string; label: string }[] = [
  { value: "d", label: "d - Deauth / Disassociation" },
  { value: "a", label: "a - Authentication flood" },
  { value: "b", label: "b - Beacon flood" },
  { value: "f", label: "f - Packet fuzzer" },
  { value: "m", label: "m - Michael (TKIP) shutdown" },
  { value: "s", label: "s - Probe request flood" },
  { value: "w", label: "w - WIDS confusion" },
];

type JobVisualState = "pending" | "running" | "success" | "warning";

function formatDate(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("ru-RU");
  } catch {
    return iso;
  }
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function obfMac(mac: string): string {
  const p = mac.split(":");
  if (p.length !== 6) return mac;
  return `${p[0]}:${p[1]}:**:**:**:${p[5]}`;
}

function obfSsid(ssid: string): string {
  if (!ssid) return ssid;
  return ssid.slice(0, 2) + "*****";
}

function hasExpectedResult(job: AuditJobItem): boolean {
  const result = (job.result || {}) as Record<string, unknown>;
  switch (job.attack_type) {
    case "handshake_capture":
    case "dragonshift":
      return result.handshake_found === true;
    case "pmkid_capture":
      return result.pmkid_found === true;
    case "psk_crack":
      return result.success === true || Boolean(result.password);
    case "wps_pixie":
      return result.success === true || Boolean(result.wpa_psk) || Boolean(result.wps_pin);
    case "deauth":
    case "dos":
      return !result.exit_code || Number(result.exit_code) === 0;
    default:
      return job.status === "completed";
  }
}

function getJobVisualState(job: AuditJobItem): JobVisualState {
  if (job.status === "pending" || job.status === "queued") return "pending";
  if (job.status === "running" || job.status === "stopping") return "running";
  if (job.status === "completed" && hasExpectedResult(job)) return "success";
  return "warning";
}

interface Props {
  projectId: number;
  obfuscationEnabled?: boolean;
}

export default function SessionAuditTab({ projectId, obfuscationEnabled = false }: Props) {
  const [plans, setPlans] = useState<AuditPlanItem[]>([]);
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);
  const [planDetail, setPlanDetail] = useState<AuditPlanDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [dictionaries, setDictionaries] = useState<DictionaryItem[]>([]);
  const [wifiInterfaces, setWifiInterfaces] = useState<NetworkInterface[]>([]);
  const [knownClients, setKnownClients] = useState<ReconSTA[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval>>();

  const obf = obfuscationEnabled;

  const loadPlans = useCallback(async () => {
    try {
      const data = await api.audit.listPlans(projectId);
      setPlans(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    loadPlans();
    api.dictionaries.list().then(setDictionaries).catch(() => {});
    api.hardware.networkInterfaces().then((ifaces) =>
      setWifiInterfaces(ifaces.filter((i) => i.wireless))
    ).catch(() => {});
  }, [loadPlans]);

  const loadPlanDetail = useCallback(async (planId: string) => {
    try {
      const data = await api.audit.getPlan(projectId, planId);
      setPlanDetail(data);
      const bb = (data.bb_solution || {}) as Record<string, unknown>;
      const scanId = (data.scan_id || (bb.scan_id as string | undefined)) || undefined;
      if (scanId && data.bssid) {
        api.recon.stas(projectId, scanId, { bssid: data.bssid }).then((r) => {
          setKnownClients((r as { items?: ReconSTA[] }).items || []);
        }).catch(() => {
          setKnownClients([]);
        });
      } else {
        setKnownClients([]);
      }
    } catch {
      setPlanDetail(null);
      setKnownClients([]);
    }
  }, [projectId]);

  useEffect(() => {
    if (!selectedPlanId) { setPlanDetail(null); return; }
    loadPlanDetail(selectedPlanId);

    pollRef.current = setInterval(() => loadPlanDetail(selectedPlanId), POLL_INTERVAL);
    return () => clearInterval(pollRef.current);
  }, [selectedPlanId, loadPlanDetail]);

  const handleDeletePlan = async (planId: string) => {
    if (!confirm("Delete this audit plan?")) return;
    try {
      await api.audit.deletePlan(projectId, planId);
      if (selectedPlanId === planId) {
        setSelectedPlanId(null);
        setPlanDetail(null);
      }
      loadPlans();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  };

  const handleStartPlan = async (planId: string) => {
    try {
      await api.audit.startPlan(projectId, planId);
      loadPlanDetail(planId);
      loadPlans();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Start failed");
    }
  };

  const handleStartJob = async (jobId: string) => {
    try {
      await api.audit.startJob(projectId, jobId);
      if (selectedPlanId) loadPlanDetail(selectedPlanId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Start failed");
    }
  };

  const handleStopJob = async (jobId: string) => {
    try {
      await api.audit.stopJob(projectId, jobId);
      if (selectedPlanId) loadPlanDetail(selectedPlanId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Stop failed");
    }
  };

  const handleSkipJob = async (jobId: string) => {
    try {
      await api.audit.skipJob(projectId, jobId);
      if (selectedPlanId) loadPlanDetail(selectedPlanId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Skip failed");
    }
  };

  const handleRestartJob = async (jobId: string) => {
    try {
      await api.audit.restartJob(projectId, jobId);
      if (selectedPlanId) loadPlanDetail(selectedPlanId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Restart failed");
    }
  };

  const handleUpdateJob = async (jobId: string, body: { config?: Record<string, unknown>; interface?: string }) => {
    try {
      await api.audit.updateJob(projectId, jobId, body);
      if (selectedPlanId) loadPlanDetail(selectedPlanId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Update failed");
    }
  };

  return (
    <div className="audit-tab">
      {error && (
        <p className="error" style={{ cursor: "pointer" }} onClick={() => setError("")}>
          {error} <span style={{ opacity: 0.5, fontSize: "0.8em" }}>(click to dismiss)</span>
        </p>
      )}

      <div className="audit-layout">
        <div className="audit-sidebar">
          <h4 className="audit-sidebar-title">Audit Plans</h4>
          {loading ? (
            <p className="audit-loading">Loading...</p>
          ) : plans.length === 0 ? (
            <p className="audit-empty">No audit plans yet. Use "Plan Audit" from the AP detail panel.</p>
          ) : (
            <div className="audit-plan-list">
              {plans.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className={`audit-plan-item ${p.id === selectedPlanId ? "audit-plan-item--active" : ""}`}
                  onClick={() => setSelectedPlanId(p.id)}
                >
                  <span className="audit-plan-bssid">{obf ? obfMac(p.bssid) : p.bssid}</span>
                  <span className="audit-plan-essid">{obf ? obfSsid(p.essid || "") : (p.essid || "<Hidden>")}</span>
                  <span className="audit-plan-meta">
                    <span className={`audit-status audit-status--${p.status}`}>{p.status}</span>
                    <span className="audit-plan-date">{formatDate(p.created_at)}</span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="audit-main">
          {!planDetail ? (
            <div className="audit-placeholder">
              <p>Select an audit plan from the sidebar to view its pipeline.</p>
            </div>
          ) : (
            <PipelineView
              plan={planDetail}
              dictionaries={dictionaries}
              wifiInterfaces={wifiInterfaces}
              knownClients={knownClients}
              obf={obf}
              onStartPlan={() => handleStartPlan(planDetail.id)}
              onDeletePlan={() => handleDeletePlan(planDetail.id)}
              onStartJob={handleStartJob}
              onStopJob={handleStopJob}
              onSkipJob={handleSkipJob}
              onRestartJob={handleRestartJob}
              onUpdateJob={handleUpdateJob}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function PipelineView({
  plan,
  dictionaries,
  wifiInterfaces,
  knownClients,
  obf,
  onStartPlan,
  onDeletePlan,
  onStartJob,
  onStopJob,
  onSkipJob,
  onRestartJob,
  onUpdateJob,
}: {
  plan: AuditPlanDetail;
  dictionaries: DictionaryItem[];
  wifiInterfaces: NetworkInterface[];
  knownClients: ReconSTA[];
  obf: boolean;
  onStartPlan: () => void;
  onDeletePlan: () => void;
  onStartJob: (jobId: string) => void;
  onStopJob: (jobId: string) => void;
  onSkipJob: (jobId: string) => void;
  onRestartJob: (jobId: string) => void;
  onUpdateJob: (jobId: string, body: { config?: Record<string, unknown>; interface?: string }) => void;
}) {
  const bbSol = plan.bb_solution as Record<string, unknown> | null;
  const bssidDisplay = obf ? obfMac(plan.bssid) : plan.bssid;
  const essidDisplay = obf ? obfSsid(plan.essid || "") : (plan.essid || "<Hidden>");

  return (
    <div className="audit-pipeline">
      <div className="audit-pipeline-header">
        <div className="audit-pipeline-info">
          <h3>{essidDisplay} ({bssidDisplay})</h3>
          <span className={`audit-status audit-status--${plan.status}`}>{plan.status}</span>
          {plan.time_budget_s && (
            <span className="audit-pipeline-budget">Budget: {formatDuration(plan.time_budget_s)}</span>
          )}
          {bbSol && (
            <span className="audit-pipeline-score">F* = {Number(bbSol.f_star ?? 0).toFixed(2)}</span>
          )}
        </div>
        <div className="audit-pipeline-actions">
          {plan.status === "pending" && (
            <div className="audit-activate-wrap">
              <button type="button" className="audit-btn audit-btn--primary" onClick={onStartPlan}>
                Activate Plan
              </button>
              <span className="audit-activate-hint">
                Activates the plan. Jobs are launched individually.
              </span>
            </div>
          )}
          <button type="button" className="audit-btn audit-btn--danger" onClick={onDeletePlan}>
            Delete
          </button>
        </div>
      </div>

      <div className="audit-pipeline-flow">
        {plan.jobs.map((job, idx) => (
          <div key={job.id} className="audit-pipeline-step-wrap">
            {idx > 0 && <div className="audit-pipeline-arrow" />}
            <JobBlock
              job={job}
              planStatus={plan.status}
              dictionaries={dictionaries}
              wifiInterfaces={wifiInterfaces}
              knownClients={knownClients}
              obf={obf}
              onStart={() => onStartJob(job.id)}
              onStop={() => onStopJob(job.id)}
              onSkip={() => onSkipJob(job.id)}
              onRestart={() => onRestartJob(job.id)}
              onUpdate={(body) => onUpdateJob(job.id, body)}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function EditableNumberField({
  value,
  min,
  step,
  placeholder,
  canEdit,
  onCommit,
}: {
  value: number | undefined;
  min: number;
  step: number;
  placeholder?: string;
  canEdit: boolean;
  onCommit: (value: number | undefined) => void;
}) {
  const [draft, setDraft] = useState(value == null ? "" : String(value));
  const [focused, setFocused] = useState(false);

  useEffect(() => {
    if (!focused) {
      setDraft(value == null ? "" : String(value));
    }
  }, [value, focused]);

  const commit = () => {
    const raw = draft.trim();
    if (raw === "") {
      onCommit(undefined);
      return;
    }
    const parsed = parseInt(raw, 10);
    if (Number.isNaN(parsed) || parsed < min) {
      setDraft(value == null ? "" : String(value));
      return;
    }
    onCommit(parsed);
    setDraft(String(parsed));
  };

  if (!canEdit) {
    return (
      <input
        type="text"
        value={value == null ? (placeholder || "(not set)") : String(value)}
        readOnly
        className="audit-job-input audit-job-input--ro"
      />
    );
  }

  return (
    <input
      type="number"
      min={min}
      step={step}
      placeholder={placeholder}
      value={draft}
      onFocus={() => setFocused(true)}
      onBlur={() => {
        setFocused(false);
        commit();
      }}
      onChange={(e) => setDraft(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          (e.currentTarget as HTMLInputElement).blur();
        }
      }}
      className="audit-job-input"
    />
  );
}

function JobBlock({
  job,
  planStatus,
  dictionaries,
  wifiInterfaces,
  knownClients,
  obf,
  onStart,
  onStop,
  onSkip,
  onRestart,
  onUpdate,
}: {
  job: AuditJobItem;
  planStatus: string;
  dictionaries: DictionaryItem[];
  wifiInterfaces: NetworkInterface[];
  knownClients: ReconSTA[];
  obf: boolean;
  onStart: () => void;
  onStop: () => void;
  onSkip: () => void;
  onRestart: () => void;
  onUpdate: (body: { config?: Record<string, unknown>; interface?: string }) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const label = ATTACK_LABELS[job.attack_type] || job.attack_type;
  const description = ATTACK_DESCRIPTIONS[job.attack_type] || "";
  const visualState = getJobVisualState(job);
  const cfg = job.config || {};
  const timeout = cfg.timeout ? Number(cfg.timeout) : 0;
  const canEdit = job.status === "pending";
  const canRun = planStatus !== "pending" && job.status === "pending";
  const canRestart = ["completed", "failed", "stopped", "skipped"].includes(job.status);
  const runCount = Number(cfg._run_count || 0);

  const handleInterfaceChange = (iface: string) => {
    onUpdate({ interface: iface || undefined });
  };

  const handleTimeoutChange = (seconds: number | undefined) => {
    if (seconds == null || seconds <= 0) return;
    onUpdate({ config: { ...cfg, timeout: seconds } });
  };

  const handleDictionaryChange = (path: string) => {
    onUpdate({ config: { ...cfg, wordlist: path } });
  };

  const handleToolChange = (tool: string) => {
    onUpdate({ config: { ...cfg, tool } });
  };

  const handleClientMacChange = (mac: string) => {
    onUpdate({ config: { ...cfg, client_mac: mac || undefined } });
  };

  const timeoutValue = cfg.timeout != null && cfg.timeout !== "" ? Number(cfg.timeout) : undefined;
  const deauthIntervalValue =
    cfg.deauth_interval != null && cfg.deauth_interval !== "" ? Number(cfg.deauth_interval) : 30;
  const deauthCountDefault = job.attack_type === "dragonshift" ? 10 : 50;
  const deauthCountValue =
    cfg.deauth_count != null && cfg.deauth_count !== "" ? Number(cfg.deauth_count) : deauthCountDefault;
  const speedValue = cfg.speed != null && cfg.speed !== "" ? Number(cfg.speed) : undefined;

  const bssidDisplay = obf ? obfMac(String(cfg.bssid || "")) : String(cfg.bssid || "");
  const isActiveRun = job.status === "running" || job.status === "stopping";
  const startedAtMs = job.started_at ? Date.parse(job.started_at) : NaN;
  const elapsedSec = Number.isFinite(startedAtMs) ? Math.max(0, (Date.now() - startedAtMs) / 1000) : 0;
  const progressPct =
    isActiveRun && timeout > 0 ? Math.min(100, Math.round((elapsedSec / timeout) * 100)) : 0;
  const etaSec = isActiveRun && timeout > 0 ? Math.max(0, Math.ceil(timeout - elapsedSec)) : 0;

  return (
    <div className={`audit-job-block audit-job-block--state-${visualState}`}>
      <div className="audit-job-header" onClick={() => setExpanded(!expanded)} style={{ cursor: "pointer" }}>
        <span className="audit-job-name">{label}</span>
        {runCount > 0 && <span className="audit-job-run-count">#{runCount + 1}</span>}
        {timeout > 0 && <span className="audit-job-time">{formatDuration(timeout)}</span>}
        <span className={`audit-job-expand ${expanded ? "audit-job-expand--open" : ""}`}>
          {expanded ? "\u25B2" : "\u25BC"}
        </span>
      </div>
      <div className="audit-job-status">{job.status}</div>
      {isActiveRun && timeout > 0 && (
        <div className="audit-job-progress">
          <div className="audit-job-progress-meta">
            <span>{progressPct}%</span>
            <span>{Math.ceil(elapsedSec)}s / {timeout}s</span>
            <span>ETA: {etaSec}s</span>
          </div>
          <div className="audit-job-progress-bar">
            <div className="audit-job-progress-fill" style={{ width: `${progressPct}%` }} />
          </div>
        </div>
      )}

      {expanded && (
        <div className="audit-job-config">
          {description && <p className="audit-job-desc">{description}</p>}

          {!!cfg._capture_ready && job.attack_type === "psk_crack" && (
            <p className="audit-job-dep-ready">
              Handshake/PMKID available from capture job.
            </p>
          )}

          <div className="audit-job-config-grid">
            {!!cfg.bssid && (
              <div className="audit-job-field">
                <label>BSSID</label>
                <input type="text" value={bssidDisplay} readOnly className="audit-job-input audit-job-input--ro" />
              </div>
            )}

            {cfg.channel != null && (
              <div className="audit-job-field">
                <label>Channel</label>
                <input type="text" value={String(cfg.channel)} readOnly className="audit-job-input audit-job-input--ro" />
              </div>
            )}

            {NEEDS_INTERFACE.has(job.attack_type) && (
              <div className="audit-job-field">
                <label>{job.attack_type === "dragonshift" ? "Monitor Interface" : "Interface"}</label>
                {canEdit ? (
                  <select
                    value={job.interface || ""}
                    onChange={(e) => handleInterfaceChange(e.target.value)}
                    className="audit-job-input"
                  >
                    <option value="">-- select interface --</option>
                    {wifiInterfaces.map((iface) => (
                      <option key={iface.name} value={iface.name}>
                        {iface.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input type="text" value={job.interface || "(not set)"} readOnly className="audit-job-input audit-job-input--ro" />
                )}
              </div>
            )}

            {NEEDS_CLIENT_TARGET.has(job.attack_type) && (
              <div className="audit-job-field">
                <label>Target Client</label>
                {canEdit ? (
                  <select
                    value={String(cfg.client_mac || "")}
                    onChange={(e) => handleClientMacChange(e.target.value)}
                    className="audit-job-input"
                  >
                    <option value="">Broadcast (all clients)</option>
                    {knownClients.map((sta) => (
                      <option key={sta.mac} value={sta.mac}>
                        {obf ? obfMac(sta.mac) : sta.mac}
                        {sta.probed_essids?.length ? ` (${sta.probed_essids[0]})` : ""}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={cfg.client_mac ? (obf ? obfMac(String(cfg.client_mac)) : String(cfg.client_mac)) : "Broadcast"}
                    readOnly
                    className="audit-job-input audit-job-input--ro"
                  />
                )}
              </div>
            )}

            <div className="audit-job-field">
              <label>Timeout (sec)</label>
              <EditableNumberField
                value={timeoutValue}
                min={10}
                step={60}
                canEdit={canEdit}
                onCommit={handleTimeoutChange}
              />
            </div>

            {NEEDS_DICTIONARY.has(job.attack_type) && (
              <>
                <div className="audit-job-field">
                  <label>Wordlist</label>
                  {canEdit ? (
                    <select
                      value={String(cfg.wordlist || "")}
                      onChange={(e) => handleDictionaryChange(e.target.value)}
                      className="audit-job-input"
                    >
                      <option value="">-- select dictionary --</option>
                      {dictionaries.map((d) => (
                        <option key={d.id} value={`/data/dictionaries/${d.filename}`}>
                          {d.name} ({(d.size_bytes / 1024).toFixed(0)} KB)
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input type="text" value={String(cfg.wordlist || "(not set)")} readOnly className="audit-job-input audit-job-input--ro" />
                  )}
                </div>
                <div className="audit-job-field">
                  <label>Tool</label>
                  {canEdit ? (
                    <select
                      value={String(cfg.tool || "aircrack-ng")}
                      onChange={(e) => handleToolChange(e.target.value)}
                      className="audit-job-input"
                    >
                      <option value="aircrack-ng">aircrack-ng (CPU)</option>
                      <option value="hashcat">hashcat (CPU)</option>
                    </select>
                  ) : (
                    <input type="text" value={String(cfg.tool || "aircrack-ng")} readOnly className="audit-job-input audit-job-input--ro" />
                  )}
                </div>
              </>
            )}

            {(job.attack_type === "handshake_capture" || job.attack_type === "dragonshift") && (
              <>
                <div className="audit-job-field">
                  <label>Deauth interval (sec)</label>
                  <EditableNumberField
                    value={deauthIntervalValue}
                    min={5}
                    step={5}
                    canEdit={canEdit}
                    onCommit={(v) => {
                      if (v == null || v < 5) return;
                      onUpdate({ config: { ...cfg, deauth_interval: v } });
                    }}
                  />
                </div>
                <div className="audit-job-field">
                  <label>Deauth packets</label>
                  <EditableNumberField
                    value={deauthCountValue}
                    min={1}
                    step={10}
                    canEdit={canEdit}
                    onCommit={(v) => {
                      if (v == null || v < 1) return;
                      onUpdate({ config: { ...cfg, deauth_count: v } });
                    }}
                  />
                </div>
              </>
            )}

            {job.attack_type === "dragonshift" && (
              <div className="audit-job-field">
                <label>AP Interface</label>
                {canEdit ? (
                  <select
                    value={String(cfg.interface2 || "")}
                    onChange={(e) => onUpdate({ config: { ...cfg, interface2: e.target.value } })}
                    className="audit-job-input"
                  >
                    <option value="">-- select interface --</option>
                    {wifiInterfaces
                      .filter((i) => i.name !== job.interface)
                      .map((iface) => (
                        <option key={iface.name} value={iface.name}>{iface.name}</option>
                      ))}
                  </select>
                ) : (
                  <input type="text" value={String(cfg.interface2 || "(not set)")} readOnly className="audit-job-input audit-job-input--ro" />
                )}
              </div>
            )}

            {job.attack_type === "dos" && (
              <>
                <div className="audit-job-field">
                  <label>mdk4 Mode</label>
                  {canEdit ? (
                    <select
                      value={String(cfg.mode || "d")}
                      onChange={(e) => onUpdate({ config: { ...cfg, mode: e.target.value } })}
                      className="audit-job-input"
                    >
                      {MDK4_MODES.map((m) => (
                        <option key={m.value} value={m.value}>{m.label}</option>
                      ))}
                    </select>
                  ) : (
                    <input type="text" value={String(cfg.mode || "d")} readOnly className="audit-job-input audit-job-input--ro" />
                  )}
                </div>
                <div className="audit-job-field">
                  <label>Packets/sec</label>
                  <EditableNumberField
                    value={speedValue}
                    min={1}
                    step={50}
                    placeholder="default"
                    canEdit={canEdit}
                    onCommit={(v) => onUpdate({ config: { ...cfg, speed: v } })}
                  />
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {job.result && (
        <div className="audit-job-result">
          {Object.entries(job.result)
            .filter(([k]) => !k.startsWith("_"))
            .map(([k, v]) => (
              <span key={k} className="audit-job-result-item">
                <strong>{k}:</strong> {String(v)}
              </span>
            ))}
        </div>
      )}

      <div className="audit-job-actions">
        {canRun && (
          <>
            <button type="button" className="audit-btn audit-btn--small audit-btn--primary" onClick={onStart}>
              Start
            </button>
            <button type="button" className="audit-btn audit-btn--small" onClick={onSkip}>
              Skip
            </button>
          </>
        )}
        {job.status === "pending" && planStatus === "pending" && (
          <span className="audit-job-hint">Activate plan to enable</span>
        )}
        {(job.status === "running" || job.status === "stopping") && (
          <button
            type="button"
            className="audit-btn audit-btn--small audit-btn--danger"
            onClick={onStop}
            disabled={job.status === "stopping"}
          >
            {job.status === "stopping" ? "Stopping..." : "Stop"}
          </button>
        )}
        {canRestart && (
          <button type="button" className="audit-btn audit-btn--small audit-btn--warning" onClick={onRestart}>
            Restart
          </button>
        )}
      </div>
    </div>
  );
}
