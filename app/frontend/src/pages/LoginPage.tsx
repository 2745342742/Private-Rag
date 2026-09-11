import { FormEvent, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import clsx from "clsx";
import { Lock, User } from "lucide-react";

import { ThemeToggle } from "../components/ThemeToggle";
import { useColorScheme } from "../hooks/useColorScheme";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";

type Mode = "login" | "register";

export default function LoginPage() {
  const { scheme, setScheme } = useColorScheme();
  const { token, loading, login, register } = useAuth();
  const location = useLocation();
  const from =
    (location.state as { from?: string } | null)?.from &&
    (location.state as { from: string }).from !== "/login"
      ? (location.state as { from: string }).from
      : "/";

  const [mode, setMode] = useState<Mode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (!loading && token) {
    return <Navigate to={from} replace />;
  }

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (mode === "register") {
      if (password !== confirm) {
        setError("两次输入的密码不一致");
        return;
      }
      if (username.trim().length < 3) {
        setError("用户名至少 3 个字符");
        return;
      }
      if (password.length < 6) {
        setError("密码至少 6 个字符");
        return;
      }
    }
    setSubmitting(true);
    try {
      if (mode === "login") {
        await login(username.trim(), password);
      } else {
        await register(username.trim(), password, displayName.trim() || undefined);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "请求失败，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  };

  const pageClass = clsx(
    "relative min-h-screen bg-gradient-to-br transition-colors",
    scheme === "dark"
      ? "from-slate-950 via-slate-950 to-slate-900 text-slate-100"
      : "from-slate-100 via-white to-slate-200 text-slate-900",
  );

  const inputClass = clsx(
    "w-full rounded-xl border bg-white/80 px-3 py-2.5 text-sm outline-none transition",
    "focus-visible:ring-2 focus-visible:ring-slate-400 dark:bg-slate-950/60",
    "border-slate-200 dark:border-slate-700",
  );

  return (
    <div className={pageClass}>
      <div className="absolute right-6 top-6">
        <ThemeToggle value={scheme} onChange={setScheme} />
      </div>

      <div className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-6 py-12">
        <div className="rounded-3xl bg-white/80 p-8 shadow-[0_45px_90px_-45px_rgba(15,23,42,0.55)] ring-1 ring-slate-200/70 backdrop-blur dark:bg-slate-900/75 dark:ring-slate-800/70">
          <div className="mb-8 space-y-2 text-center">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">
              知识检索
            </p>
            <h1 className="text-2xl font-semibold tracking-tight">
              {mode === "login" ? "登录你的知识库" : "创建账号"}
            </h1>
            <p className="text-sm text-slate-600 dark:text-slate-300">
              个人文档、对话检索与评分，登录后即可使用。
            </p>
          </div>

          <div className="mb-6 grid grid-cols-2 gap-1 rounded-full bg-slate-100 p-1 dark:bg-slate-800/80">
            {(["login", "register"] as Mode[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => {
                  setMode(m);
                  setError(null);
                }}
                className={clsx(
                  "rounded-full px-3 py-2 text-sm font-medium transition",
                  mode === m
                    ? "bg-white text-slate-900 shadow-sm dark:bg-slate-950 dark:text-slate-50"
                    : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100",
                )}
              >
                {m === "login" ? "登录" : "注册"}
              </button>
            ))}
          </div>

          <form className="space-y-4" onSubmit={onSubmit}>
            {error ? (
              <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-200">
                {error}
              </div>
            ) : null}

            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
                用户名
              </span>
              <div className="relative">
                <User className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  className={clsx(inputClass, "pl-9")}
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                  required
                />
              </div>
            </label>

            {mode === "register" ? (
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
                  显示名（可选）
                </span>
                <input
                  className={inputClass}
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  autoComplete="nickname"
                />
              </label>
            ) : null}

            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
                密码
              </span>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  type="password"
                  className={clsx(inputClass, "pl-9")}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  required
                />
              </div>
            </label>

            {mode === "register" ? (
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
                  确认密码
                </span>
                <input
                  type="password"
                  className={inputClass}
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  autoComplete="new-password"
                  required
                />
              </label>
            ) : null}

            <button
              type="submit"
              disabled={submitting}
              className="mt-2 w-full rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:opacity-60 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
            >
              {submitting
                ? "提交中…"
                : mode === "login"
                  ? "登录"
                  : "注册并进入"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
