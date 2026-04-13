/** Настройки -> Общие: тема, управление пользователем. */
import { useState } from "react";
import { useTheme } from "../contexts/ThemeContext";
import { api, ApiError } from "../api/client";

export default function SettingsGeneralPage() {
  const { theme, setTheme } = useTheme();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [repeatPassword, setRepeatPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(false);
    if (newPassword !== repeatPassword) {
      setError("Пароли не совпадают");
      return;
    }
    if (newPassword.length < 8) {
      setError("Новый пароль должен быть не менее 8 символов");
      return;
    }
    setLoading(true);
    try {
      await api.auth.changePassword(currentPassword, newPassword);
      setSuccess(true);
      setCurrentPassword("");
      setNewPassword("");
      setRepeatPassword("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Ошибка смены пароля");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="panel-card settings-general-card">
        <h2 className="settings-general-section-title">Web Interface</h2>
        <div className="settings-general-row">
          <label className="settings-general-label" htmlFor="theme-select">
            Тема
          </label>
          <select
            id="theme-select"
            name="theme"
            className="settings-general-select"
            value={theme}
            onChange={(e) => setTheme(e.target.value as "light" | "dark")}
          >
            <option value="light">Светлая</option>
            <option value="dark">Тёмная</option>
          </select>
        </div>
      </div>

      <div className="panel-card settings-general-card">
        <h2 className="settings-general-section-title">User Management</h2>
        <form onSubmit={handleChangePassword} className="settings-general-form">
          <div className="settings-general-row">
            <label className="settings-general-label" htmlFor="current-password">
              Текущий пароль
            </label>
            <input
              id="current-password"
              type="password"
              className="settings-general-input"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
          </div>
          <div className="settings-general-row">
            <label className="settings-general-label" htmlFor="new-password">
              Новый пароль
            </label>
            <input
              id="new-password"
              type="password"
              className="settings-general-input"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={8}
              autoComplete="new-password"
            />
          </div>
          <div className="settings-general-row">
            <label className="settings-general-label" htmlFor="repeat-password">
              Повторите новый пароль
            </label>
            <input
              id="repeat-password"
              type="password"
              className="settings-general-input"
              value={repeatPassword}
              onChange={(e) => setRepeatPassword(e.target.value)}
              required
              minLength={8}
              autoComplete="new-password"
            />
          </div>
          {error && <p className="settings-general-error">{error}</p>}
          {success && <p className="settings-general-success">Пароль успешно обновлён</p>}
          <button
            type="submit"
            className="settings-general-submit"
            disabled={loading}
          >
            {loading ? "Обновление..." : "Обновить пароль"}
          </button>
        </form>
      </div>
    </>
  );
}
