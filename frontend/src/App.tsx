import { Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./hooks/useAuth";
import { ActiveProjectProvider } from "./contexts/ActiveProjectContext";
import Layout from "./components/Layout";
import SetupPage from "./pages/SetupPage";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import ModulesPage from "./pages/ModulesPage";
import ProjectsPage from "./pages/ProjectsPage";
import ProjectWorkspacePage from "./pages/ProjectWorkspacePage";
import HardwarePage from "./pages/HardwarePage";
import SettingsLayout from "./pages/SettingsLayout";
import SettingsGeneralPage from "./pages/SettingsGeneralPage";
import SettingsWifiPage from "./pages/SettingsWifiPage";
import SettingsAuditPage from "./pages/SettingsAuditPage";
import DictionariesPage from "./pages/DictionariesPage";
import "./App.css";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { token, loading } = useAuth();
  if (loading) return <div className="app-loading">Загрузка...</div>;
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/setup" element={<SetupPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<ProtectedRoute><ActiveProjectProvider><Layout /></ActiveProjectProvider></ProtectedRoute>}>
        <Route index element={<DashboardPage />} />
        <Route path="modules" element={<ModulesPage />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/workspace" element={<ProjectWorkspacePage />} />
        <Route path="hardware" element={<HardwarePage />} />
        <Route path="dictionaries" element={<DictionariesPage />} />
        <Route path="settings" element={<SettingsLayout />}>
          <Route index element={<SettingsGeneralPage />} />
          <Route path="wifi" element={<SettingsWifiPage />} />
          <Route path="audit" element={<SettingsAuditPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
