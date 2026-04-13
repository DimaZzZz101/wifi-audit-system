const API_BASE = "/api";
const TOKEN_KEY = "wifiaudit_token";
const ACTIVE_PROJECT_KEY = "wifiaudit_active_project";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function normalizeErrorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          const msg = (item as { msg?: unknown }).msg;
          return typeof msg === "string" ? msg : "";
        }
        return "";
      })
      .filter(Boolean);
    if (msgs.length > 0) return msgs.join("; ");
  }
  if (detail && typeof detail === "object") {
    try {
      return JSON.stringify(detail);
    } catch {
      return fallback;
    }
  }
  return fallback;
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(
  path: string,
  options: RequestInit & { token?: string | null } = {}
): Promise<T> {
  const { token = getToken(), ...init } = options;
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };
  if (token) {
    (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    const payload = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = payload?.detail ?? payload;
    const message = normalizeErrorMessage(detail, res.statusText || `HTTP ${res.status}`);
    if (res.status === 401) {
      clearToken();
      localStorage.removeItem(ACTIVE_PROJECT_KEY);
      window.dispatchEvent(new CustomEvent("wifiaudit:unauthorized"));
    }
    throw new ApiError(message, res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  setup: {
    getStatus: () => request<{ setup_completed: boolean }>("/setup/status"),
    createUser: (username: string, password: string) =>
      request<{ access_token: string; token_type: string }>("/setup/create-user", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      }),
  },
  auth: {
    login: (username: string, password: string) =>
      request<{ access_token: string; token_type: string }>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      }),
    me: (token?: string | null) =>
      request<{ id: number; username: string; is_active: boolean }>("/auth/me", {
        token,
      }),
    changePassword: (currentPassword: string, newPassword: string) =>
      request<{ message: string }>("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      }),
  },
  containers: {
    list: (all?: boolean) =>
      request<ContainerItem[]>(`/containers${all ? "?all=true" : ""}`),
    images: () => request<ImageItem[]>("/containers/images"),
    get: (id: string) => request<ContainerItem>(`/containers/${id}`),
    create: (body: ContainerCreateBody) =>
      request<ContainerCreated>("/containers", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    stop: (id: string, remove?: boolean) =>
      request<ContainerStopped>(`/containers/${id}?remove=${remove !== false}`, {
        method: "DELETE",
      }),
  },
  registry: {
    list: () => request<RegistryEntry[]>("/registry"),
  },
  metrics: {
    system: () => request<SystemMetrics>("/metrics/system"),
  },
  plugins: {
    list: (provides?: string) =>
      request<PluginDescriptor[]>(`/plugins${provides ? `?provides=${encodeURIComponent(provides)}` : ""}`),
    get: (id: string) => request<PluginDescriptor>(`/plugins/${encodeURIComponent(id)}`),
  },
  modules: {
    installed: () => request<InstalledModule[]>("/modules/installed"),
    available: () => request<AvailableModule[]>("/modules/available"),
    download: (downloadUrl: string) =>
      request<{ success: boolean; message?: string }>("/modules/download", {
        method: "POST",
        body: JSON.stringify({ download_url: downloadUrl }),
      }),
    install: (checksum?: string) =>
      request<ModuleInstallResponse>("/modules/install", {
        method: "POST",
        body: JSON.stringify({ checksum: checksum ?? null }),
      }),
    remove: (moduleId: string) =>
      request<{ success: boolean; module_id: string }>(`/modules/${encodeURIComponent(moduleId)}`, {
        method: "DELETE",
      }),
  },
  hardware: {
    summary: (wifiOnly?: boolean) =>
      request<HardwareSummary>(`/hardware/summary${wifiOnly === true ? "?wifi_only=true" : ""}`),
    usb: (wifiOnly?: boolean) =>
      request<UsbDevice[]>(`/hardware/usb${wifiOnly === true ? "?wifi_only=true" : ""}`),
    pci: (wifiOnly?: boolean) =>
      request<PciDevice[]>(`/hardware/pci${wifiOnly === true ? "?wifi_only=true" : ""}`),
    networkInterfaces: () => request<NetworkInterface[]>("/hardware/network-interfaces"),
    filesystem: () => request<FilesystemUsage[]>("/hardware/filesystem"),
    wifiAdapterState: (name: string) =>
      request<WifiAdapterState>(`/hardware/wifi-adapter/${encodeURIComponent(name)}/state`),
    wifiAdapterConfigure: (name: string, body: WifiAdapterConfigureBody) =>
      request<WifiAdapterConfigureResult>(
        `/hardware/wifi-adapter/${encodeURIComponent(name)}/configure`,
        { method: "POST", body: JSON.stringify(body) }
      ),
  },
  projects: {
    list: () => request<ProjectItem[]>("/projects"),
    get: (id: number) => request<ProjectItem>(`/projects/${id}`),
    create: (name: string) =>
      request<ProjectItem>("/projects", {
        method: "POST",
        body: JSON.stringify({ name }),
      }),
    update: (id: number, body: { status?: string; name?: string; obfuscation_enabled?: boolean }) =>
      request<ProjectItem>(`/projects/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    getMacFilter: (id: number) =>
      request<MacFilterResponse>(`/projects/${id}/mac-filter`),
    putMacFilter: (id: number, body: MacFilterBody) =>
      request<MacFilterResponse>(`/projects/${id}/mac-filter`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    downloadMacFilter: async (id: number) => {
      const res = await fetch(
        `${API_BASE}/projects/${id}/mac-filter/file`,
        { headers: { Authorization: `Bearer ${getToken()}` } }
      );
      if (!res.ok) throw new ApiError("Download error", res.status, await res.text());
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "mac_filter.txt";
      a.click();
      URL.revokeObjectURL(url);
    },
    delete: (id: number) =>
      request<void>(`/projects/${id}`, { method: "DELETE" }),
    filesList: (id: number, path?: string) =>
      request<ProjectFilesResponse>(`/projects/${id}/files${path ? `?path=${encodeURIComponent(path)}` : ""}`),
    toolsAvailable: (id: number) =>
      request<ProjectTool[]>(`/projects/${id}/tools/available`),
    toolRun: (id: number, toolId: string) =>
      request<ProjectToolResult>(`/projects/${id}/tools/run`, {
        method: "POST",
        body: JSON.stringify({ tool_id: toolId }),
      }),
    toolRuns: (id: number) =>
      request<ProjectToolRun[]>(`/projects/${id}/tools/runs`),
    fileContent: (id: number, path: string) =>
      request<string>(`/projects/${id}/files/content?path=${encodeURIComponent(path)}`),
    fileDownload: async (id: number, path: string, filename?: string) => {
      const res = await fetch(
        `${API_BASE}/projects/${id}/files/download?path=${encodeURIComponent(path)}`,
        { headers: { Authorization: `Bearer ${getToken()}` } }
      );
      if (!res.ok) throw new ApiError("Ошибка скачивания", res.status, await res.text());
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename || path.split("/").pop() || "file";
      a.click();
      URL.revokeObjectURL(url);
    },
  },
  recon: {
    start: (projectId: number, body: ReconStartBody) =>
      request<ReconStartResult>(`/projects/${projectId}/recon/start`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    stop: (projectId: number, scanId: string) =>
      request<ReconStopResult>(`/projects/${projectId}/recon/${scanId}/stop`, {
        method: "POST",
      }),
    scans: (projectId: number) =>
      request<ReconScanItem[]>(`/projects/${projectId}/recon/scans`),
    status: (projectId: number, scanId: string) =>
      request<ReconScanItem>(`/projects/${projectId}/recon/${scanId}/status`),
    aps: (projectId: number, scanId: string, params?: ReconTableParams & { band?: string }) => {
      const q = new URLSearchParams();
      if (params?.sort_by) q.set("sort_by", params.sort_by);
      if (params?.sort_dir) q.set("sort_dir", params.sort_dir);
      if (params?.limit) q.set("limit", String(params.limit));
      if (params?.offset != null) q.set("offset", String(params.offset));
      if (params?.band) q.set("band", params.band);
      const qs = q.toString();
      return request<PaginatedAP>(`/projects/${projectId}/recon/${scanId}/aps${qs ? `?${qs}` : ""}`);
    },
    stas: (projectId: number, scanId: string, params?: ReconTableParams & { bssid?: string }) => {
      const q = new URLSearchParams();
      if (params?.sort_by) q.set("sort_by", params.sort_by);
      if (params?.sort_dir) q.set("sort_dir", params.sort_dir);
      if (params?.limit) q.set("limit", String(params.limit));
      if (params?.offset != null) q.set("offset", String(params.offset));
      if (params?.bssid) q.set("bssid", params.bssid);
      const qs = q.toString();
      return request<PaginatedSTA>(`/projects/${projectId}/recon/${scanId}/stas${qs ? `?${qs}` : ""}`);
    },
    apDetail: (projectId: number, scanId: string, bssid: string) =>
      request<ReconAP>(`/projects/${projectId}/recon/${scanId}/aps/${encodeURIComponent(bssid)}`),
  },
  audit: {
    createPlan: (projectId: number, bssid: string, scanId: string) =>
      request<AuditPlanDetail>(`/projects/${projectId}/audit/plan`, {
        method: "POST",
        body: JSON.stringify({ bssid, scan_id: scanId }),
      }),
    listPlans: (projectId: number) =>
      request<AuditPlanItem[]>(`/projects/${projectId}/audit/plans`),
    getPlan: (projectId: number, planId: string) =>
      request<AuditPlanDetail>(`/projects/${projectId}/audit/plans/${planId}`),
    startPlan: (projectId: number, planId: string) =>
      request<{ plan_id: string; status: string }>(`/projects/${projectId}/audit/plans/${planId}/start`, {
        method: "POST",
      }),
    deletePlan: (projectId: number, planId: string) =>
      request<{ ok: boolean }>(`/projects/${projectId}/audit/plans/${planId}`, {
        method: "DELETE",
      }),
    getJob: (projectId: number, jobId: string) =>
      request<AuditJobItem>(`/projects/${projectId}/audit/jobs/${jobId}`),
    updateJob: (projectId: number, jobId: string, body: { config?: Record<string, unknown>; interface?: string }) =>
      request<AuditJobItem>(`/projects/${projectId}/audit/jobs/${jobId}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    startJob: (projectId: number, jobId: string) =>
      request<{ job_id: string; container_id: string; status: string }>(`/projects/${projectId}/audit/jobs/${jobId}/start`, {
        method: "POST",
      }),
    stopJob: (projectId: number, jobId: string) =>
      request<{ job_id: string; status: string }>(`/projects/${projectId}/audit/jobs/${jobId}/stop`, {
        method: "POST",
      }),
    skipJob: (projectId: number, jobId: string) =>
      request<AuditJobItem>(`/projects/${projectId}/audit/jobs/${jobId}/skip`, {
        method: "POST",
      }),
    restartJob: (projectId: number, jobId: string) =>
      request<AuditJobItem>(`/projects/${projectId}/audit/jobs/${jobId}/restart`, {
        method: "POST",
      }),
  },
  dictionaries: {
    list: () => request<DictionaryItem[]>("/dictionaries/"),
    get: (id: number) => request<DictionaryItem>(`/dictionaries/${id}`),
    upload: async (name: string, file: File, description?: string) => {
      const form = new FormData();
      form.append("name", name);
      form.append("file", file);
      if (description) form.append("description", description);
      const token = getToken();
      const res = await fetch(`${API_BASE}/dictionaries/`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });
      if (!res.ok) {
        const payload = await res.json().catch(() => ({ detail: res.statusText }));
        throw new ApiError(payload.detail || res.statusText, res.status, payload.detail);
      }
      return res.json() as Promise<DictionaryItem>;
    },
    generate: (name: string, masks: string[], description?: string) =>
      request<DictionaryItem>("/dictionaries/generate", {
        method: "POST",
        body: JSON.stringify({ name, masks, description }),
      }),
    delete: (id: number) => request<{ ok: boolean }>(`/dictionaries/${id}`, { method: "DELETE" }),
    download: async (id: number, filename: string) => {
      const res = await fetch(`${API_BASE}/dictionaries/${id}/download`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (!res.ok) throw new ApiError("Download error", res.status, await res.text());
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    },
  },
  auditSettings: {
    get: () => request<AuditSettings>("/settings/audit/"),
    update: (body: Partial<AuditSettings>) =>
      request<AuditSettings>("/settings/audit/", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
  },
};

export type ReconStartBody = {
  interface: string;
  scan_mode: "continuous" | "timed";
  scan_duration?: number;
  bands?: string;
  channels?: string;
};

export type ReconStartResult = {
  scan_id: string;
  container_id: string | null;
  container_name: string | null;
  status: string;
};

export type ReconStopResult = {
  scan_id: string;
  status: string;
  error?: string | null;
};

export type ReconScanItem = {
  scan_id: string;
  started_at: string | null;
  stopped_at: string | null;
  is_running: boolean;
  scan_mode: string;
  scan_duration?: number | null;
  interface: string;
  bands?: string;
  ap_count: number;
  sta_count: number;
  container_id?: string | null;
};

export type ReconAP = {
  bssid: string;
  essid: string | null;
  is_hidden: boolean;
  channel: number | null;
  band: string | null;
  power: number | null;
  speed: number | null;
  privacy: string | null;
  cipher: string | null;
  auth: string | null;
  beacons: number;
  data_frames: number;
  iv_count: number;
  wps: Record<string, unknown> | null;
  security_info: ReconSecurityInfo | null;
  tagged_params: Record<string, unknown> | null;
  first_seen: string | null;
  last_seen: string | null;
  client_count: number;
  clients?: ReconSTA[];
};

export type ReconSecurityInfo = {
  encryption: string;
  display_security?: string;
  cipher: string;
  akm: string;
  pmf: string;
  wps_enabled: boolean;
  wps_locked: boolean;
  vulnerabilities: string[];
};

export type ReconSTA = {
  mac: string;
  power: number | null;
  packets: number;
  probed_essids: string[];
  associated_bssid: string | null;
  first_seen: string | null;
  last_seen: string | null;
};

export type PaginatedAP = {
  total: number;
  items: ReconAP[];
};

export type PaginatedSTA = {
  total: number;
  items: ReconSTA[];
};

export type ReconTableParams = {
  sort_by?: string;
  sort_dir?: "asc" | "desc";
  limit?: number;
  offset?: number;
};

export type InstalledModule = {
  id: string;
  name: string;
  type: string;
  description?: string | null;
  version?: string | null;
  author?: string | null;
  provides: string[];
  container?: PluginContainer | null;
  frontend?: PluginFrontend | null;
  system: boolean;
  removable: boolean;
};

export type AvailableModule = {
  id: string;
  name: string;
  version: string;
  description?: string | null;
  author?: string | null;
  download_url?: string | null;
  checksum?: string | null;
};

export type ModuleInstallResponse = {
  module_id: string;
};

export type ContainerMetrics = {
  id: string;
  name: string;
  cpu_percent: number | null;
  memory_used_bytes: number;
  memory_limit_bytes: number | null;
  memory_used_mb: number;
  memory_limit_mb: number | null;
  memory_percent: number | null;
};

export type HostMetrics = {
  cpu_percent: number | null;
  memory_used_bytes: number;
  memory_limit_bytes: number | null;
  memory_used_mb: number;
  memory_limit_mb: number | null;
  memory_percent: number | null;
  disk_used_gb: number;
  disk_total_gb: number;
  disk_percent: number;
};

export type SystemMetrics = {
  host: HostMetrics;
  cpu: { percent: number; containers_count: number };
  memory: {
    used_bytes: number;
    limit_bytes: number;
    used_mb: number;
    limit_mb: number | null;
    percent: number | null;
  };
  containers: ContainerMetrics[];
  disk: { used_gb: number; total_gb: number; percent: number; path: string };
  source_ok?: boolean;
  errors?: string[];
};

export type PluginContainer = {
  image: string | null;
  type: string;
  default_command?: string | string[] | null;
};

export type PluginFrontend = {
  bundle_url?: string | null;
};

export type PluginDescriptor = {
  id: string;
  name: string;
  type: string;
  description?: string | null;
  version?: string | null;
  author?: string | null;
  provides: string[];
  container?: PluginContainer | null;
  frontend?: PluginFrontend | null;
};

export type ContainerItem = {
  id: string;
  short_id: string;
  name: string;
  image: string;
  status: string;
  created: string;
  labels?: Record<string, string>;
};

export type ContainerCreateBody = {
  image: string;
  name?: string;
  container_type?: string;
  env?: Record<string, string>;
  network_mode?: string;
  cap_add?: string[];
  volumes?: string[];
  command?: string | string[];
  detach?: boolean;
};

export type ContainerCreated = {
  id: string | null;
  short_id?: string;
  name?: string;
  image: string;
  status: string;
  created?: string;
};

export type ContainerStopped = {
  id: string;
  stopped: boolean;
  removed: boolean;
};

export type ImageItem = {
  id: string;
  tags: string[];
  created: string;
  size: number;
  registry_reference?: string | null;
};

export type RegistryEntry = {
  image_reference: string;
  tool_id: string;
  tool_name: string;
  in_docker: boolean;
  docker_id?: string;
  size?: number;
  created?: string;
};

export type UsbDevice = {
  bus: string;
  device: string;
  id: string;
  name: string;
  wifi_capable?: boolean;
};

export type PciDevice = {
  slot: string;
  class_name: string;
  name: string;
  wifi_capable?: boolean;
};

export type NetworkInterface = {
  name: string;
  flags?: string;
  wireless: boolean;
};

export type FilesystemUsage = {
  filesystem: string;
  type: string;
  size: string;
  used: string;
  available: string;
  use_percent: string;
  mounted_on: string;
};

export type HardwareSummary = {
  usb_devices: UsbDevice[];
  pci_devices: PciDevice[];
  network_interfaces: NetworkInterface[];
  filesystem: FilesystemUsage[];
};

export type SupportedChannel = {
  channel: number;
  freq: number;
  band: string;
  max_power_dbm: number | null;
  dfs: boolean;
  disabled: boolean;
};

export type WifiAdapterState = {
  mode: string;
  channel: number | null;
  freq: number | null;
  txpower: number | null;
  mac: string | null;
  phy: string;
  reg_domain: string;
  supported_channels: SupportedChannel[];
};

export type WifiAdapterConfigureBody = {
  mode: string;
  channel?: number;
  txpower?: number;
  mac?: string;
};

export type WifiAdapterConfigureResult = {
  success: boolean;
  idempotent?: boolean;
  message?: string;
  actual_mode?: string;
  actual_interface?: string;
  actual_channel?: number | null;
  actual_txpower?: number | null;
  actual_mac?: string | null;
  txpower_warning?: string;
};

export type ProjectItem = {
  id: number;
  slug: string;
  name: string;
  created_at: string;
  status: string;
  session_type: string;
  mac_filter_type: string | null;
  mac_filter_entries: string[];
  obfuscation_enabled: boolean;
};

export type ProjectFileItem = {
  name: string;
  display_name?: string;
  path: string;
  is_dir: boolean;
  size: number | null;
};

export type ProjectFilesResponse = {
  path: string;
  items: ProjectFileItem[];
};

export type ProjectTool = {
  id: string;
  name: string;
  description: string;
  image: string;
};

export type ProjectToolResult = {
  tool_id: string;
  tool_name: string;
  container_name: string;
  exit_code: number;
  stdout: string;
  stderr: string;
  saved_to: string;
};

export type ProjectToolRun = {
  file: string;
  tool_id: string;
  timestamp: string;
  exit_code: number;
};

export type MacFilterBody = {
  filter_type: string | null;
  entries: string[];
};

export type MacFilterResponse = {
  filter_type: string | null;
  entries: string[];
};

// --- Audit types ---

export type AuditPlanItem = {
  id: string;
  bssid: string;
  essid: string | null;
  status: string;
  time_budget_s: number | null;
  created_at: string | null;
  job_count: number;
};

export type AuditJobItem = {
  id: string;
  audit_plan_id: string;
  attack_type: string;
  order_index: number;
  status: string;
  config: Record<string, unknown>;
  container_id: string | null;
  interface: string | null;
  started_at: string | null;
  stopped_at: string | null;
  result: Record<string, unknown> | null;
  log_path: string | null;
  artifact_paths: Record<string, string> | null;
};

export type AuditPlanDetail = {
  id: string;
  project_id: number;
  scan_id?: string | null;
  bssid: string;
  essid: string | null;
  status: string;
  time_budget_s: number | null;
  bb_solution: Record<string, unknown> | null;
  created_at: string | null;
  updated_at: string | null;
  jobs: AuditJobItem[];
};

export type AttackParamItem = {
  name: string;
  weight: number;
  time_s: number;
};

export type AuditSettings = {
  attacks: AttackParamItem[];
  time_budget_s: number;
};

export type DictionaryItem = {
  id: number;
  name: string;
  description: string | null;
  filename: string;
  size_bytes: number;
  word_count: number;
  created_at: string | null;
};
