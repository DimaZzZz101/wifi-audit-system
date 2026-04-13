/** Настройки > Wi-Fi: список беспроводных интерфейсов с расширенной настройкой. */
import { useState, useEffect, useCallback, useMemo } from "react";
import {
  api,
  type HardwareSummary,
  type NetworkInterface,
  type WifiAdapterState,
  type SupportedChannel,
  type WifiAdapterConfigureBody,
  ApiError,
} from "../api/client";

/** Генерация случайного MAC (локально администрируемый, unicast). */
function randomMac(): string {
  const bytes = new Uint8Array(6);
  crypto.getRandomValues(bytes);
  bytes[0] = (bytes[0]! & 0xfe) | 0x02; // locally administered, unicast
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join(":")
    .toUpperCase();
}

// ---------------------------------------------------------------------------
// InterfaceCard - одна карточка интерфейса с информацией и формой настройки
// ---------------------------------------------------------------------------

function InterfaceCard({
  iface,
  onApplySuccess,
}: {
  iface: NetworkInterface;
  onApplySuccess?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [state, setState] = useState<WifiAdapterState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [mode, setMode] = useState("managed");
  const [band, setBand] = useState<"2.4" | "5" | "">("");
  const [channel, setChannel] = useState<string>("");
  const [txpower, setTxpower] = useState<string>("");
  const [mac, setMac] = useState<string>("");
  const [applying, setApplying] = useState(false);
  const [result, setResult] = useState<{ msg: string; isError?: boolean } | null>(null);
  const loadState = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const s = await api.hardware.wifiAdapterState(iface.name);
      setState(s);
      setMode(s.mode || "managed");
      setMac(s.mac || "");
      setTxpower(s.txpower != null ? String(Math.round(s.txpower)) : "");
      if (s.channel != null && s.freq != null) {
        setBand(s.freq < 5000 ? "2.4" : "5");
        setChannel(String(s.channel));
      } else {
        setBand("");
        setChannel("");
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Ошибка загрузки состояния");
      setState(null);
    } finally {
      setLoading(false);
    }
  }, [iface.name]);

  useEffect(() => {
    if (expanded && !state && !loading) {
      loadState();
    }
  }, [expanded, state, loading, loadState]);

  const availableChannels = useMemo(() => {
    if (!state) return [];
    let chs = state.supported_channels.filter((c) => !c.disabled);
    if (band) {
      chs = chs.filter((c) => c.band === band);
    }
    return chs;
  }, [state, band]);

  const availableBands = useMemo(() => {
    if (!state) return [];
    const bands = new Set(
      state.supported_channels
        .filter((c) => !c.disabled)
        .map((c) => c.band)
    );
    const result: string[] = [];
    if (bands.has("2.4")) result.push("2.4");
    if (bands.has("5")) result.push("5");
    return result;
  }, [state]);

  const maxTxForChannel = useMemo((): number | null => {
    if (!channel || !state) return null;
    const ch = state.supported_channels.find((c) => c.channel === parseInt(channel, 10));
    return ch?.max_power_dbm ?? null;
  }, [channel, state]);

  const effectiveMaxTxDbm = useMemo(() => {
    return maxTxForChannel ?? 30;
  }, [maxTxForChannel]);

  const handleBandChange = (newBand: string) => {
    setBand(newBand as "2.4" | "5" | "");
    setChannel("");
  };

  const handleApply = async (e: React.FormEvent) => {
    e.preventDefault();
    setApplying(true);
    setResult(null);
    try {
      const body: WifiAdapterConfigureBody = { mode };
      // Канал и мощность - только для monitor
      if (mode === "monitor") {
        if (channel) {
          const ch = parseInt(channel, 10);
          if (ch > 0) body.channel = ch;
        }
        if (txpower) {
          const tp = parseInt(txpower, 10);
          if (tp >= 0 && tp <= 30) body.txpower = tp;
        }
      }
      if (mac && mac !== state?.mac) {
        body.mac = mac;
      }
      const res = await api.hardware.wifiAdapterConfigure(iface.name, body);
      if (res.success) {
        const msg = res.idempotent
          ? "Состояние уже соответствует настройкам."
          : `Применено: ${res.actual_mode || mode}${res.actual_interface ? ` (${res.actual_interface})` : ""}${res.actual_channel != null ? `, канал ${res.actual_channel}` : ""}${res.actual_txpower != null ? `, ${res.actual_txpower} dBm` : ""}`;
        setResult({
          msg: res.txpower_warning ? `${msg} ${res.txpower_warning}` : msg,
        });
        if (res.actual_interface && res.actual_interface !== iface.name) {
          onApplySuccess?.();
        } else {
          loadState();
        }
      } else {
        setResult({ msg: res.message || "Ошибка применения", isError: true });
      }
    } catch (e) {
      setResult({ msg: e instanceof ApiError ? e.message : "Ошибка настройки", isError: true });
    } finally {
      setApplying(false);
    }
  };

  return (
    <li className="settings-wifi-item">
      <button
        type="button"
        className={`settings-wifi-item-header ${expanded ? "is-expanded" : ""}`}
        onClick={() => setExpanded((v) => !v)}
      >
        <span className="settings-wifi-item-icon">📡</span>
        <span className="settings-wifi-item-name">{iface.name}</span>
        {state && (
          <span className="settings-wifi-item-meta">
            {state.mode}{state.channel != null ? `, ch${state.channel}` : ""}
            {state.txpower != null ? `, ${state.txpower} dBm` : ""}
          </span>
        )}
        <span className="settings-wifi-item-chevron">
          {expanded ? "v" : ">"}
        </span>
      </button>

      {expanded && (
        <div className="settings-wifi-item-details">
          {loading && <p className="settings-wifi-config-loading">Загрузка состояния...</p>}
          {error && <p className="settings-wifi-config-error">{error}</p>}

          {state && (
            <>
              {/* Current state summary */}
              <dl className="settings-wifi-dl">
                <dt>Интерфейс</dt>
                <dd><code>{iface.name}</code></dd>
                <dt>Физическое устройство</dt>
                <dd><code>{state.phy || "-"}</code></dd>
                <dt>MAC-адрес</dt>
                <dd><code>{state.mac || "-"}</code></dd>
                <dt>Режим</dt>
                <dd>{state.mode || "-"}</dd>
                <dt>Канал / Частота</dt>
                <dd>
                  {state.channel != null ? `${state.channel}` : "-"}
                  {state.freq != null ? ` (${state.freq} МГц)` : ""}
                </dd>
                <dt>Мощность TX</dt>
                <dd>{state.txpower != null ? `${state.txpower} dBm` : "-"}</dd>
                <dt>Рег. домен</dt>
                <dd>{state.reg_domain || "-"}</dd>
              </dl>

              <h4 className="settings-wifi-config-title">Configuration</h4>
              <form className="settings-wifi-config-form settings-wifi-config-form--grid" onSubmit={handleApply}>
                {/* Mode */}
                <div className="settings-wifi-config-row">
                  <label htmlFor={`mode-${iface.name}`} className="settings-wifi-config-label">
                    Режим
                  </label>
                  <select
                    id={`mode-${iface.name}`}
                    name="mode"
                    className="settings-wifi-config-select"
                    value={mode}
                    onChange={(e) => setMode(e.target.value)}
                  >
                    <option value="managed">Managed</option>
                    <option value="monitor">Monitor</option>
                  </select>
                </div>

                {mode === "monitor" && (
                  <>
                    {/* Band */}
                    <div className="settings-wifi-config-row" role="group" aria-labelledby={`band-label-${iface.name}`}>
                      <span id={`band-label-${iface.name}`} className="settings-wifi-config-label">Диапазон</span>
                      <div className="settings-wifi-band-group">
                        {availableBands.map((b) => (
                          <label key={b} className={`settings-wifi-band-option ${band === b ? "is-active" : ""}`}>
                            <input
                              id={`band-${b}-${iface.name}`}
                              name={`band-${iface.name}`}
                              type="radio"
                              value={b}
                              checked={band === b}
                              onChange={() => handleBandChange(b)}
                            />
                            {b === "2.4" ? "2.4 ГГц" : "5 ГГц"}
                          </label>
                        ))}
                        {availableBands.length === 0 && (
                          <span className="settings-wifi-config-hint">Нет данных</span>
                        )}
                      </div>
                    </div>

                    {/* Channel */}
                    <div className="settings-wifi-config-row">
                      <label htmlFor={`channel-${iface.name}`} className="settings-wifi-config-label">
                        Канал
                        {maxTxForChannel != null && (
                          <span className="settings-wifi-config-hint"> (макс. {maxTxForChannel} dBm)</span>
                        )}
                      </label>
                      <select
                        id={`channel-${iface.name}`}
                        name="channel"
                        className="settings-wifi-config-select"
                        value={channel}
                        onChange={(e) => setChannel(e.target.value)}
                      >
                        <option value="">Авто</option>
                        {availableChannels.map((ch: SupportedChannel) => (
                          <option key={ch.channel} value={ch.channel}>
                            {ch.channel} ({ch.freq} МГц){ch.dfs ? " DFS" : ""}
                          </option>
                        ))}
                      </select>
                    </div>

                    {/* TX Power */}
                    <div className="settings-wifi-config-row">
                      <label htmlFor={`txpower-${iface.name}`} className="settings-wifi-config-label">
                        Мощность TX (dBm)
                        <span className="settings-wifi-config-hint"> макс. {effectiveMaxTxDbm}</span>
                      </label>
                      <input
                        id={`txpower-${iface.name}`}
                        name="txpower"
                        type="number"
                        min={0}
                        max={effectiveMaxTxDbm}
                        step={1}
                        className="settings-wifi-config-input"
                        value={txpower}
                        onChange={(e) => setTxpower(e.target.value)}
                        placeholder={String(effectiveMaxTxDbm)}
                      />
                    </div>
                  </>
                )}

                {/* MAC */}
                <div className="settings-wifi-config-row settings-wifi-config-row--wide">
                  <label htmlFor={`mac-${iface.name}`} className="settings-wifi-config-label">
                    MAC-адрес
                  </label>
                  <div className="settings-wifi-config-mac-row">
                    <input
                      id={`mac-${iface.name}`}
                      name="mac"
                      type="text"
                      className="settings-wifi-config-input settings-wifi-config-input--mac"
                      value={mac}
                      onChange={(e) => setMac(e.target.value)}
                      placeholder="XX:XX:XX:XX:XX:XX"
                    />
                    <button
                      type="button"
                      className="settings-wifi-config-btn settings-wifi-config-btn--small"
                      onClick={() => setMac(randomMac())}
                      title="Случайный MAC"
                    >
                      ⟳
                    </button>
                  </div>
                </div>

                <div className="settings-wifi-config-row settings-wifi-config-row--actions">
                  <button type="submit" className="settings-wifi-config-btn" disabled={applying}>
                    {applying ? "Применение..." : "Применить"}
                  </button>
                  <button
                    type="button"
                    className="settings-wifi-config-btn settings-wifi-config-btn--secondary"
                    onClick={loadState}
                    disabled={loading}
                  >
                    Обновить
                  </button>
                </div>
              </form>

              {result && (
                <p className={result.isError ? "settings-wifi-config-error" : "settings-wifi-config-success"}>
                  {result.msg}
                </p>
              )}
            </>
          )}
        </div>
      )}
    </li>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function SettingsWifiPage() {
  const [interfaces, setInterfaces] = useState<NetworkInterface[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const summary: HardwareSummary = await api.hardware.summary(false);
      const wireless = (summary.network_interfaces ?? []).filter((i) => i.wireless);
      setInterfaces(wireless);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <div className="panel-card">
        <p className="settings-wifi-loading">Загрузка Wi-Fi интерфейсов...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="panel-card">
        <p className="error">{error}</p>
        <button type="button" className="settings-wifi-retry" onClick={load}>
          Повторить
        </button>
      </div>
    );
  }

  return (
    <div className="panel-card settings-wifi-card">
      <h2 className="panel-card-title">Wi-Fi Interfaces</h2>
      <p className="panel-card-desc">
        Беспроводные сетевые интерфейсы хоста. Выберите интерфейс для настройки режима, канала, мощности и MAC-адреса.
      </p>
      {interfaces.length === 0 ? (
        <p className="settings-wifi-empty">
          Беспроводные интерфейсы не обнаружены. Убедитесь, что система имеет доступ к /sys хоста
          и Wi-Fi адаптеры подключены.
        </p>
      ) : (
        <ul className="settings-wifi-list">
          {interfaces.map((iface) => (
            <InterfaceCard key={iface.name} iface={iface} onApplySuccess={load} />
          ))}
        </ul>
      )}
    </div>
  );
}
