import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../hooks/useAuth";

export default function SetupPage() {
  const navigate = useNavigate();
  const { token, login } = useAuth();
  const [status, setStatus] = useState<{ setup_completed: boolean } | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.setup.getStatus().then(setStatus).catch(() => setStatus({ setup_completed: false }));
  }, []);

  useEffect(() => {
    if (token) {
      navigate("/", { replace: true });
      return;
    }
    if (status?.setup_completed) {
      navigate("/login", { replace: true });
    }
  }, [status, token, navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!username.trim() || password.length < 8) {
      setError("Логин не пустой, пароль не менее 8 символов.");
      return;
    }
    setSubmitting(true);
    try {
      const { access_token } = await api.setup.createUser(username.trim(), password);
      login(access_token);
      navigate("/", { replace: true });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Ошибка создания пользователя");
    } finally {
      setSubmitting(false);
    }
  };

  if (status === null) {
    return (
      <div className="page setup-page">
        <div className="card">Проверка статуса...</div>
      </div>
    );
  }

  if (status.setup_completed) {
    return null;
  }

  return (
    <div className="page setup-page">
      <div className="card setup-card">
        <h1>Getting Started</h1>
        <p>Создайте учётную запись для управления системой аудита WiFi.</p>
        <form onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="setup-username">Логин</label>
            <input
              id="setup-username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="setup-password">Пароль (не менее 8 символов)</label>
            <input
              id="setup-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              minLength={8}
              required
            />
          </div>
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={submitting}>
            {submitting ? "Создание..." : "Создать пользователя"}
          </button>
        </form>
      </div>
    </div>
  );
}
