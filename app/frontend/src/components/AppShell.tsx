import { NavLink, Outlet, useNavigate } from "react-router-dom";
import clsx from "clsx";
import { FileText, LogOut, MessageSquare, FlaskConical } from "lucide-react";

import { ThemeToggle } from "./ThemeToggle";
import { useColorScheme } from "../hooks/useColorScheme";
import { useAuth } from "../lib/auth";

const navItems = [
  { to: "/", label: "对话", icon: MessageSquare, end: true },
  { to: "/documents", label: "文档", icon: FileText, end: false },
  { to: "/eval", label: "评分", icon: FlaskConical, end: false },
];

export default function AppShell() {
  const { scheme, setScheme } = useColorScheme();
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const pageClass = clsx(
    "flex h-screen flex-col bg-gradient-to-br transition-colors",
    scheme === "dark"
      ? "from-slate-950 via-slate-950 to-slate-900 text-slate-100"
      : "from-slate-100 via-white to-slate-200 text-slate-900",
  );

  const handleLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className={pageClass}>
      <header className="flex shrink-0 items-center justify-between gap-4 border-b border-slate-200/80 bg-white/70 px-4 py-3 backdrop-blur dark:border-slate-800 dark:bg-slate-950/50">
        <div className="flex items-center gap-6">
          <div>
            <p className="text-lg font-semibold leading-tight tracking-tight sm:text-xl">
              个人知识库
            </p>
          </div>
          <nav className="flex items-center gap-1">
            {navItems.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  clsx(
                    "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm transition",
                    isActive
                      ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                      : "text-slate-600 hover:bg-slate-200/70 dark:text-slate-300 dark:hover:bg-slate-800",
                  )
                }
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <span className="hidden text-sm text-slate-600 dark:text-slate-300 sm:inline">
            {user?.display_name || user?.username}
          </span>
          <ThemeToggle value={scheme} onChange={setScheme} />
          <button
            type="button"
            onClick={handleLogout}
            className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white/70 px-3 py-1.5 text-sm text-slate-700 hover:bg-white dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-200"
          >
            <LogOut className="h-3.5 w-3.5" />
            退出
          </button>
        </div>
      </header>
      <main className="min-h-0 flex-1 overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
