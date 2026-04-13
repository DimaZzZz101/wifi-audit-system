import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../hooks/useAuth";

export default function LoginPage() {
  const navigate = useNavigate();
  const { token, login } = useAuth();
  const [setupCompleted, setSetupCompleted] = useState<boolean | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.setup.getStatus().then((s) => setSetupCompleted(s.setup_completed)).catch(() => setSetupCompleted(false));
  }, []);

  useEffect(() => {
    if (token) navigate("/", { replace: true });
  }, [token, navigate]);

  useEffect(() => {
    if (setupCompleted === false) navigate("/setup", { replace: true });
  }, [setupCompleted, navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const { access_token } = await api.auth.login(username, password);
      login(access_token);
      navigate("/", { replace: true });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Ошибка входа");
    } finally {
      setSubmitting(false);
    }
  };

  if (setupCompleted === null) {
    return (
      <div className="page login-page">
        <div className="card">Загрузка...</div>
      </div>
    );
  }

  if (!setupCompleted) return null;

  return (
    <div className="page login-page">
      <div className="card login-card">
        <h1>Login</h1>
        <form onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="login-username">Логин</label>
            <input
              id="login-username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="login-password">Пароль</label>
            <input
              id="login-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={submitting}>
            {submitting ? "Вход..." : "Войти"}
          </button>
        </form>
      </div>
    </div>
  );
}
