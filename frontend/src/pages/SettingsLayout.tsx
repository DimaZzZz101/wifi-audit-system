/** Layout настроек: вкладки Общие / Wi-Fi. */
import { Outlet, NavLink } from "react-router-dom";

export default function SettingsLayout() {
  return (
    <div className="panel-page settings-page">
      <h1 className="settings-page-title">Settings</h1>
      <div className="settings-tabs">
        <NavLink
          to="/settings"
          end
          className={({ isActive }) => "settings-tab" + (isActive ? " is-active" : "")}
        >
          General
        </NavLink>
        <NavLink
          to="/settings/wifi"
          className={({ isActive }) => "settings-tab" + (isActive ? " is-active" : "")}
        >
          Wi-Fi
        </NavLink>
        <NavLink
          to="/settings/audit"
          className={({ isActive }) => "settings-tab" + (isActive ? " is-active" : "")}
        >
          Audit
        </NavLink>
      </div>
      <Outlet />
    </div>
  );
}
