/** Контекст активного проекта - текущий рабочий проект аудита. */
import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from "react";

const STORAGE_KEY = "wifiaudit_active_project";

export type ActiveProject = { id: number; slug: string; name: string } | null;

type ActiveProjectContextValue = {
  activeProject: ActiveProject | null;
  setActiveProject: (project: ActiveProject | null) => void;
  clearActiveProject: () => void;
};

const ActiveProjectContext = createContext<ActiveProjectContextValue | null>(null);

function loadFromStorage(): ActiveProject | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { id: number; slug: string; name: string };
    if (typeof parsed?.id === "number" && typeof parsed?.name === "string" && typeof parsed?.slug === "string") {
      return parsed;
    }
  } catch {
    // ignore
  }
  return null;
}

function saveToStorage(project: ActiveProject | null) {
  if (project) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(project));
  } else {
    localStorage.removeItem(STORAGE_KEY);
  }
}

export function ActiveProjectProvider({ children }: { children: ReactNode }) {
  const [activeProject, setState] = useState<ActiveProject | null>(loadFromStorage);

  useEffect(() => {
    const handler = () => {
      setState(null);
      saveToStorage(null);
    };
    window.addEventListener("wifiaudit:unauthorized", handler);
    return () => window.removeEventListener("wifiaudit:unauthorized", handler);
  }, []);

  const setActiveProject = useCallback((project: ActiveProject | null) => {
    setState(project);
    saveToStorage(project);
  }, []);

  const clearActiveProject = useCallback(() => {
    setState(null);
    saveToStorage(null);
  }, []);

  return (
    <ActiveProjectContext.Provider value={{ activeProject, setActiveProject, clearActiveProject }}>
      {children}
    </ActiveProjectContext.Provider>
  );
}

export function useActiveProject() {
  const ctx = useContext(ActiveProjectContext);
  if (!ctx) throw new Error("useActiveProject must be used within ActiveProjectProvider");
  return ctx;
}
