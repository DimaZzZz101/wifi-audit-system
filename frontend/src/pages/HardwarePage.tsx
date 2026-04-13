/** Hardware: по умолчанию только Wi-Fi модули; кнопка "Показать все". Опрос раз в 10 с. */
import { useState, useEffect, useCallback } from "react";
import { api, type HardwareSummary, type UsbDevice, type PciDevice } from "../api/client";

const POLL_INTERVAL_MS = 10000;

export default function HardwarePage() {
  const [data, setData] = useState<HardwareSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [wifiOnly, setWifiOnly] = useState(true);

  const load = useCallback(async (silent = false) => {
    if (!silent) {
      setLoading(true);
      setError("");
    }
    try {
      const summary = await api.hardware.summary(wifiOnly);
      setData(summary);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки данных");
    } finally {
      if (!silent) setLoading(false);
    }
  }, [wifiOnly]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const id = setInterval(() => load(true), POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [load]);

  if (loading && !data) {
    return (
      <div className="panel-page hardware-page">
        <p>Загрузка данных о хосте...</p>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="panel-page hardware-page">
        <p className="error">{error}</p>
        <button type="button" onClick={() => load()}>Повторить</button>
      </div>
    );
  }

  const usb = data?.usb_devices ?? [];
  const pci = data?.pci_devices ?? [];
  const fs = data?.filesystem ?? [];

  return (
    <div className="panel-page hardware-page">
      <h1 className="hardware-page-title">Hardware</h1>
      <p className="hardware-page-desc">
        Информация о хосте для аудита Wi-Fi: USB и PCI устройства (в т.ч. Wi-Fi модули), файловые системы.
      </p>

      <div className="hardware-filter">
        <button
          type="button"
          className="hardware-filter-btn"
          onClick={() => setWifiOnly((v) => !v)}
        >
          {wifiOnly ? "Показать все устройства" : "Только Wi-Fi модули"}
        </button>
        <span className="hardware-filter-hint">
          {wifiOnly ? "Сейчас: только Wi-Fi (USB и PCI)" : "Сейчас: все USB и PCI"}
        </span>
      </div>

      {wifiOnly ? (
        <section className="hardware-section">
          <h2 className="hardware-section-title">Wi-Fi Modules (USB & PCI)</h2>
          {usb.length === 0 && pci.length === 0 ? (
            <p className="hardware-empty">Нет Wi-Fi устройств (USB/PCI) или нет доступа к хосту.</p>
          ) : (
            <ul className="hardware-list">
              {usb.map((d: UsbDevice, i: number) => (
                <li key={`usb-${i}`} className="hardware-item hardware-item-wireless">
                  <span className="hardware-item-bus">USB</span>
                  <span className="hardware-item-id">{d.bus}:{d.device}</span>
                  <span className="hardware-item-id-vendor">{d.id}</span>
                  <span className="hardware-item-name">{d.name}</span>
                  <span className="hardware-badge">Wi-Fi</span>
                </li>
              ))}
              {pci.map((d: PciDevice, i: number) => (
                <li key={`pci-${i}`} className="hardware-item hardware-item-wireless">
                  <span className="hardware-item-bus">PCI</span>
                  <span className="hardware-item-id">{d.slot}</span>
                  <span className="hardware-item-name">{d.name}</span>
                  <span className="hardware-badge">Wi-Fi</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : (
        <>
          <section className="hardware-section">
            <h2 className="hardware-section-title">USB Devices</h2>
            {usb.length === 0 ? (
              <p className="hardware-empty">Нет данных (в Docker без доступа к хосту список может быть пустым).</p>
            ) : (
              <ul className="hardware-list">
                {usb.map((d: UsbDevice, i: number) => (
                  <li key={i} className={`hardware-item ${d.wifi_capable ? "hardware-item-wireless" : ""}`}>
                    <span className="hardware-item-id">{d.bus}:{d.device}</span>
                    <span className="hardware-item-id-vendor">{d.id}</span>
                    <span className="hardware-item-name">{d.name}</span>
                    {d.wifi_capable && <span className="hardware-badge">Wi-Fi</span>}
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="hardware-section">
            <h2 className="hardware-section-title">PCI Devices</h2>
            {pci.length === 0 ? (
              <p className="hardware-empty">Нет данных (lspci недоступен или пусто).</p>
            ) : (
              <ul className="hardware-list">
                {pci.map((d: PciDevice, i: number) => (
                  <li key={i} className={`hardware-item ${d.wifi_capable ? "hardware-item-wireless" : ""}`}>
                    <span className="hardware-item-id">{d.slot}</span>
                    <span className="hardware-item-name">{d.name}</span>
                    <span className="hardware-item-class">{d.class_name}</span>
                    {d.wifi_capable && <span className="hardware-badge">Wi-Fi</span>}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}

      <section className="hardware-section">
        <h2 className="hardware-section-title">File Systems</h2>
        {fs.length === 0 ? (
          <p className="hardware-empty">Нет данных.</p>
        ) : (
          <div className="hardware-fs-table-wrap">
            <table className="hardware-fs-table">
              <thead>
                <tr>
                  <th>Filesystem</th>
                  <th>Type</th>
                  <th>Size</th>
                  <th>Used</th>
                  <th>Available</th>
                  <th>Usage</th>
                  <th>Mount Point</th>
                </tr>
              </thead>
              <tbody>
                {fs.map((row, i) => (
                  <tr key={i}>
                    <td>{row.filesystem}</td>
                    <td>{row.type}</td>
                    <td>{row.size}</td>
                    <td>{row.used}</td>
                    <td>{row.available}</td>
                    <td>{row.use_percent}</td>
                    <td>{row.mounted_on}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
