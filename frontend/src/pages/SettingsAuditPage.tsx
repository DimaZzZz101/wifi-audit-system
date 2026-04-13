/** Settings: Audit attack parameters - weights, times, global budget. */
import { useState, useEffect, useCallback } from "react";
import { api, type AuditSettings } from "../api/client";

export default function SettingsAuditPage() {
  const [settings, setSettings] = useState<AuditSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setSettings(await api.auditSettings.get());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleAttackChange = (idx: number, field: "weight" | "time_s", value: string) => {
    if (!settings) return;
    const attacks = [...settings.attacks];
    attacks[idx] = { ...attacks[idx], [field]: parseFloat(value) || 0 };
    setSettings({ ...settings, attacks });
  };

  const handleBudgetChange = (value: string) => {
    if (!settings) return;
    setSettings({ ...settings, time_budget_s: parseFloat(value) || 0 });
  };

  const handleSave = async () => {
    if (!settings) return;
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const updated = await api.auditSettings.update(settings);
      setSettings(updated);
      setSuccess("Settings saved");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    load();
    setSuccess("");
  };

  if (loading) return <p className="settings-loading">Loading...</p>;

  if (!settings) return <p className="error">{error || "No settings"}</p>;

  return (
    <div className="settings-audit">
      <h2 className="settings-audit-title">Audit Attack Parameters</h2>
      <p className="settings-audit-desc">
        Configure weights and estimated times for each attack type. These values are used by the Branch-and-Bound optimizer when planning audits.
      </p>

      <div className="settings-audit-budget">
        <label>
          Global Time Budget (seconds):
          <input
            type="number"
            min={0}
            step={300}
            value={settings.time_budget_s}
            onChange={(e) => handleBudgetChange(e.target.value)}
          />
        </label>
        <span className="settings-audit-budget-hint">
          = {Math.round(settings.time_budget_s / 3600)} hours
        </span>
      </div>

      <table className="settings-audit-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Attack</th>
            <th>Weight (0-1)</th>
            <th>Time (seconds)</th>
            <th>Time (human)</th>
          </tr>
        </thead>
        <tbody>
          {settings.attacks.map((atk, idx) => (
            <tr key={atk.name}>
              <td>{idx + 1}</td>
              <td>{atk.name}</td>
              <td>
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  value={atk.weight}
                  onChange={(e) => handleAttackChange(idx, "weight", e.target.value)}
                />
              </td>
              <td>
                <input
                  type="number"
                  min={0}
                  step={60}
                  value={atk.time_s}
                  onChange={(e) => handleAttackChange(idx, "time_s", e.target.value)}
                />
              </td>
              <td className="settings-audit-time-hint">
                {atk.time_s >= 3600
                  ? `${(atk.time_s / 3600).toFixed(1)}h`
                  : `${Math.round(atk.time_s / 60)}m`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="settings-audit-actions">
        <button
          type="button"
          className="settings-audit-btn settings-audit-btn--primary"
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? "Saving..." : "Save"}
        </button>
        <button
          type="button"
          className="settings-audit-btn"
          onClick={handleReset}
        >
          Reset
        </button>
      </div>

      {error && <p className="error">{error}</p>}
      {success && <p className="settings-audit-success">{success}</p>}
    </div>
  );
}
