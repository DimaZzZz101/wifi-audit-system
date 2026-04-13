import { useState, useRef, useEffect } from "react";
import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { useActiveProject } from "../contexts/ActiveProjectContext";
import {
  IconDashboard,
  IconModules,
  IconSessions,
  IconHardware,
  IconDictionary,
  IconSettings,
  IconMenu,
  IconLogout,
  IconChevronLeft,
  IconChevronRight,
} from "./Icons";
import "./Layout.css";

const APP_VERSION = "0.1.0";

export default function Layout() {
  const { logout } = useAuth();
  const { activeProject, clearActiveProject } = useActiveProject();
  const navigate = useNavigate();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const handleLogout = () => {
    setMenuOpen(false);
    clearActiveProject();
    logout();
    navigate("/login", { replace: true });
  };

  useEffect(() => {
    if (!menuOpen) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [menuOpen]);

  return (
    <div className="app-layout">
      <header className="top-bar">
        <div className="top-bar-left">
          <div className="top-bar-logo">
            <div className="logo-text">
              <span className="logo-title">WiFi Audit</span>
              <span className="logo-version">Version {APP_VERSION}</span>
            </div>
          </div>
          <button
            type="button"
            className="top-bar-session-banner"
            title={activeProject ? `Текущий проект: ${activeProject.name}` : "Проект не выбран"}
            onClick={() => navigate(activeProject ? "/projects/workspace" : "/projects")}
          >
            {activeProject ? (
              <span className="top-bar-session-name">{activeProject.name} <span className="top-bar-session-id">#{activeProject.slug}</span></span>
            ) : (
              <span className="top-bar-session-empty">Проект не выбран</span>
            )}
          </button>
        </div>
        <div className="top-bar-right" ref={menuRef}>
          <div className="top-bar-menu">
            <button
              type="button"
              className="top-bar-icon-btn"
              title="Меню"
              aria-label="Меню"
              aria-expanded={menuOpen}
              aria-haspopup="true"
              onClick={() => setMenuOpen((v) => !v)}
            >
              <IconMenu />
            </button>
            {menuOpen && (
              <div className="top-bar-dropdown" role="menu">
                <button
                  type="button"
                  className="top-bar-dropdown-item"
                  role="menuitem"
                  onClick={handleLogout}
                >
                  <span className="top-bar-dropdown-icon"><IconLogout /></span>
                  <span>Logout</span>
                </button>
              </div>
            )}
          </div>
        </div>
      </header>
      <aside className={`sidebar ${sidebarCollapsed ? "sidebar--collapsed" : ""}`}>
        <nav className="sidebar-nav">
          <NavLink to="/" end className={({ isActive }) => "sidebar-item" + (isActive ? " is-active" : "")}>
            <span className="sidebar-icon"><IconDashboard /></span>
            <span className="sidebar-label">Dashboard</span>
          </NavLink>
          <NavLink to="/modules" className={({ isActive }) => "sidebar-item" + (isActive ? " is-active" : "")}>
            <span className="sidebar-icon"><IconModules /></span>
            <span className="sidebar-label">Modules</span>
          </NavLink>
          <NavLink to="/projects" className={({ isActive }) => "sidebar-item" + (isActive ? " is-active" : "")}>
            <span className="sidebar-icon"><IconSessions /></span>
            <span className="sidebar-label">Projects</span>
          </NavLink>
          <NavLink to="/hardware" className={({ isActive }) => "sidebar-item" + (isActive ? " is-active" : "")}>
            <span className="sidebar-icon"><IconHardware /></span>
            <span className="sidebar-label">Hardware</span>
          </NavLink>
          <NavLink to="/dictionaries" className={({ isActive }) => "sidebar-item" + (isActive ? " is-active" : "")}>
            <span className="sidebar-icon"><IconDictionary /></span>
            <span className="sidebar-label">Dictionaries</span>
          </NavLink>
        </nav>
        <div className="sidebar-footer">
          <NavLink to="/settings" className={({ isActive }) => "sidebar-item" + (isActive ? " is-active" : "")}>
            <span className="sidebar-icon"><IconSettings /></span>
            <span className="sidebar-label">Settings</span>
          </NavLink>
          <button
            type="button"
            className="sidebar-toggle"
            title={sidebarCollapsed ? "Развернуть меню" : "Свернуть меню"}
            aria-label={sidebarCollapsed ? "Развернуть меню" : "Свернуть меню"}
            onClick={() => setSidebarCollapsed((v) => !v)}
          >
            {sidebarCollapsed ? <IconChevronRight /> : <IconChevronLeft />}
          </button>
        </div>
      </aside>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
