import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { History, Loader2, Play, Square, Trash2, Upload } from "lucide-react";

import { apiFetch, ApiError } from "../lib/api";

type Dataset = {
  id: string;
  name: string;
  item_count: number;
  created_at?: string | null;
};

type EvalResult = {
  item_id: string;
  question: string;
  correct_answer: string;
  model_answer: string;
  decision: string;
  correctness?: number | null;
  grounding?: number | null;
  rationale?: string | null;
};

type EvalRunSummary = {
  id: string;
  dataset_id: string;
  dataset_name: string;
  status: string;
  pass_rate?: number | null;
  result_count?: number;
  item_total?: number;
  created_at?: string | null;
  finished_at?: string | null;
};

type EvalRun = EvalRunSummary & {
  results: EvalResult[];
};

function formatTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("zh-CN", { hour12: false });
}

function formatPassRate(rate?: number | null): string {
  if (rate == null) return "—";
  return `${(rate * 100).toFixed(1)}%`;
}

function formatProgress(
  run: Pick<EvalRunSummary, "result_count" | "item_total" | "status">,
): string {
  const done = run.result_count ?? 0;
  const total = run.item_total ?? 0;
  if (total > 0) return `${done}/${total}`;
  return `${done} 题`;
}

export default function EvalPage() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [name, setName] = useState("测试评分");
  const [sourcePath, setSourcePath] = useState("evals/datasets/smoke_nfg.jsonl");
  const [history, setHistory] = useState<EvalRunSummary[]>([]);
  const [run, setRun] = useState<EvalRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [historyFilter, setHistoryFilter] = useState<"all" | "selected">("all");
  const pollRef = useRef<number | null>(null);

  const reloadHistory = useCallback(
    async (datasetId?: string) => {
      setHistoryLoading(true);
      try {
        const qs =
          historyFilter === "selected" && (datasetId || selectedId)
            ? `?dataset_id=${encodeURIComponent(datasetId || selectedId)}`
            : "";
        const data = await apiFetch<{ items: EvalRunSummary[] }>(`/eval/runs${qs}`);
        setHistory(data.items || []);
      } catch (err) {
        setError(err instanceof ApiError ? err.detail : "加载评分历史失败");
      } finally {
        setHistoryLoading(false);
      }
    },
    [historyFilter, selectedId],
  );

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<{ items: Dataset[] }>("/eval/datasets");
      setDatasets(data.items || []);
      if (!selectedId && data.items?.[0]) setSelectedId(data.items[0].id);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "加载题库失败");
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void reloadHistory();
  }, [reloadHistory]);

  const openRun = async (runId: string) => {
    setDetailLoading(true);
    setError(null);
    try {
      const data = await apiFetch<EvalRun>(`/eval/runs/${runId}`);
      setRun(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "加载评分详情失败");
    } finally {
      setDetailLoading(false);
    }
  };

  // 后台任务进行中：轮询详情与历史
  useEffect(() => {
    if (run?.status !== "running") {
      if (pollRef.current != null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    const tick = async () => {
      try {
        const data = await apiFetch<EvalRun>(`/eval/runs/${run.id}`);
        setRun(data);
        if (data.status !== "running") {
          await reloadHistory(data.dataset_id);
        }
      } catch {
        /* 轮询失败不打断，下一轮再试 */
      }
    };
    void tick();
    pollRef.current = window.setInterval(() => void tick(), 2500);
    return () => {
      if (pollRef.current != null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [run?.id, run?.status, reloadHistory]);

  const deleteRun = async (runId: string) => {
    if (!window.confirm("确定删除该次评分记录？")) return;
    setError(null);
    try {
      await apiFetch(`/eval/runs/${runId}`, { method: "DELETE" });
      if (run?.id === runId) setRun(null);
      await reloadHistory();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "删除失败");
    }
  };

  const deleteDataset = async () => {
    if (!selectedId) return;
    if (!window.confirm("确定删除该题库及其评分记录？")) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/eval/datasets/${selectedId}`, { method: "DELETE" });
      setSelectedId("");
      setRun(null);
      await reload();
      await reloadHistory();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "删除题库失败");
    } finally {
      setBusy(false);
    }
  };

  const onImportPath = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("name", name.trim() || "导入题库");
      fd.append("source_path", sourcePath.trim());
      const data = await apiFetch<{ dataset: Dataset }>("/eval/datasets/import", {
        method: "POST",
        formData: fd,
      });
      await reload();
      setSelectedId(data.dataset.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "导入失败");
    } finally {
      setBusy(false);
    }
  };

  const onImportFile = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const input = form.elements.namedItem("file") as HTMLInputElement | null;
    const file = input?.files?.[0];
    if (!file) {
      setError("请选择 jsonl 文件");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("name", name.trim() || file.name);
      fd.append("file", file);
      const data = await apiFetch<{ dataset: Dataset }>("/eval/datasets/import", {
        method: "POST",
        formData: fd,
      });
      form.reset();
      await reload();
      setSelectedId(data.dataset.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "导入失败");
    } finally {
      setBusy(false);
    }
  };

  const onRun = async () => {
    if (!selectedId) {
      setError("请先选择或导入题库");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const data = await apiFetch<EvalRun>("/eval/runs", {
        method: "POST",
        body: { dataset_id: selectedId },
      });
      setRun(data);
      await reloadHistory(selectedId);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "评分失败");
    } finally {
      setBusy(false);
    }
  };

  const onCancel = async () => {
    if (!run?.id || run.status !== "running") return;
    if (!window.confirm("确定取消本次评分？已完成的题目会保留。")) return;
    setBusy(true);
    setError(null);
    try {
      const data = await apiFetch<EvalRun>(`/eval/runs/${run.id}/cancel`, {
        method: "POST",
      });
      setRun(data);
      await reloadHistory(data.dataset_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "取消失败");
    } finally {
      setBusy(false);
    }
  };

  const running = run?.status === "running";
  const startDisabled = busy || !selectedId || running;

  return (
    <div className="h-full overflow-y-auto px-4 py-6 sm:px-8">
      <div className="mx-auto max-w-4xl space-y-6">
        <div>
          <h2 className="text-xl font-semibold">评分</h2>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            导入 jsonl 题库，对当前个人知识库跑本地评判；任务在后台执行，可在此查看进度与历史。
          </p>
        </div>

        {error ? (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-900/50 dark:bg-rose-950/30 dark:text-rose-200">
            {error}
          </div>
        ) : null}

        <div className="grid gap-4 md:grid-cols-2">
          <form
            onSubmit={onImportPath}
            className="space-y-3 rounded-2xl bg-white/80 p-4 ring-1 ring-slate-200/70 dark:bg-slate-900/70 dark:ring-slate-800"
          >
            <p className="text-sm font-medium">从仓库路径导入</p>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="题库名称"
              className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
            />
            <input
              value={sourcePath}
              onChange={(e) => setSourcePath(e.target.value)}
              placeholder="evals/datasets/smoke_nfg.jsonl"
              className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
            />
            <button
              type="submit"
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-xl bg-slate-900 px-3 py-2 text-sm text-white disabled:opacity-60 dark:bg-slate-100 dark:text-slate-900"
            >
              <Upload className="h-4 w-4" />
              导入路径
            </button>
          </form>

          <form
            onSubmit={onImportFile}
            className="space-y-3 rounded-2xl bg-white/80 p-4 ring-1 ring-slate-200/70 dark:bg-slate-900/70 dark:ring-slate-800"
          >
            <p className="text-sm font-medium">上传 jsonl 文件</p>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="题库名称"
              className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
            />
            <input name="file" type="file" accept=".jsonl,.json" className="w-full text-sm" />
            <button
              type="submit"
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-xl bg-slate-900 px-3 py-2 text-sm text-white disabled:opacity-60 dark:bg-slate-100 dark:text-slate-900"
            >
              <Upload className="h-4 w-4" />
              上传导入
            </button>
          </form>
        </div>

        <div className="rounded-2xl bg-white/80 p-4 ring-1 ring-slate-200/70 dark:bg-slate-900/70 dark:ring-slate-800">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <label className="block flex-1 space-y-1">
              <span className="text-xs text-slate-500">选择题库</span>
              <select
                value={selectedId}
                onChange={(e) => setSelectedId(e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
              >
                <option value="">
                  {loading ? "加载中…" : datasets.length ? "请选择" : "暂无题库"}
                </option>
                {datasets.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}（{d.item_count} 题）
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={() => void onRun()}
              disabled={startDisabled}
              className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60 dark:bg-slate-100 dark:text-slate-900"
            >
              {busy || running ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              {running ? "评分进行中…" : "开始评分"}
            </button>
            {running ? (
              <button
                type="button"
                onClick={() => void onCancel()}
                disabled={busy}
                className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-amber-300 bg-amber-50 px-4 py-2 text-sm font-medium text-amber-800 hover:bg-amber-100 disabled:opacity-60 dark:border-amber-800/60 dark:bg-amber-950/40 dark:text-amber-200 dark:hover:bg-amber-950/70"
              >
                <Square className="h-3.5 w-3.5 fill-current" />
                取消评分
              </button>
            ) : null}
            <button
              type="button"
              title="删除题库"
              onClick={() => void deleteDataset()}
              disabled={busy || !selectedId || running}
              className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-rose-200 px-3 py-2 text-sm text-rose-600 hover:bg-rose-50 disabled:opacity-50 dark:border-rose-900/60 dark:text-rose-300 dark:hover:bg-rose-950/40"
            >
              <Trash2 className="h-4 w-4" />
              删除题库
            </button>
          </div>
        </div>

        <div className="space-y-3 rounded-2xl bg-white/80 p-4 ring-1 ring-slate-200/70 dark:bg-slate-900/70 dark:ring-slate-800">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm font-medium">
              <History className="h-4 w-4" />
              评分历史
            </div>
            <div className="flex items-center gap-2 text-xs">
              <select
                value={historyFilter}
                onChange={(e) =>
                  setHistoryFilter(e.target.value === "selected" ? "selected" : "all")
                }
                className="rounded-lg border border-slate-200 bg-white px-2 py-1 dark:border-slate-700 dark:bg-slate-950"
              >
                <option value="all">全部题库</option>
                <option value="selected" disabled={!selectedId}>
                  仅当前题库
                </option>
              </select>
              <button
                type="button"
                onClick={() => void reloadHistory()}
                disabled={historyLoading}
                className="rounded-lg px-2 py-1 text-slate-600 hover:bg-slate-100 disabled:opacity-50 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                {historyLoading ? "刷新中…" : "刷新"}
              </button>
            </div>
          </div>

          {historyLoading && !history.length ? (
            <p className="text-sm text-slate-500">加载历史…</p>
          ) : !history.length ? (
            <p className="text-sm text-slate-500">还没有评分记录，先跑一次「开始评分」。</p>
          ) : (
            <ul className="divide-y divide-slate-200/70 dark:divide-slate-800">
              {history.map((h) => {
                const active = run?.id === h.id;
                return (
                  <li
                    key={h.id}
                    className={`flex items-stretch gap-1 px-1 ${
                      active ? "bg-slate-100/80 dark:bg-slate-800/80" : ""
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => void openRun(h.id)}
                      disabled={detailLoading}
                      className="flex min-w-0 flex-1 flex-col gap-1 px-2 py-3 text-left text-sm transition hover:bg-slate-50 dark:hover:bg-slate-800/60 sm:flex-row sm:items-center sm:justify-between"
                    >
                      <div className="min-w-0">
                        <p className="truncate font-medium">
                          {h.dataset_name || "未命名题库"}
                        </p>
                        <p className="text-xs text-slate-500">{formatTime(h.created_at)}</p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
                        <span>{h.status}</span>
                        <span>通过率 {formatPassRate(h.pass_rate)}</span>
                        <span>{formatProgress(h)}</span>
                      </div>
                    </button>
                    <button
                      type="button"
                      title="删除"
                      onClick={() => void deleteRun(h.id)}
                      disabled={busy || h.status === "running"}
                      className="m-2 self-center rounded-lg p-1.5 text-slate-400 hover:bg-rose-50 hover:text-rose-600 disabled:opacity-50 dark:hover:bg-rose-950/40 dark:hover:text-rose-300"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {detailLoading && !run ? (
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            加载详情…
          </div>
        ) : null}

        {run ? (
          <div className="space-y-3 rounded-2xl bg-white/80 p-4 ring-1 ring-slate-200/70 dark:bg-slate-900/70 dark:ring-slate-800">
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span className="font-medium">{run.dataset_name || "评分详情"}</span>
              <span>状态：{run.status}</span>
              <span>进度：{formatProgress(run)}</span>
              <span>通过率：{formatPassRate(run.pass_rate)}</span>
              <span className="text-xs text-slate-500">{formatTime(run.created_at)}</span>
              {running ? (
                <span className="inline-flex items-center gap-1 text-xs text-slate-500">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  后台评测中，约每 2.5s 刷新
                </span>
              ) : null}
            </div>
            {running && (run.item_total ?? 0) > 0 ? (
              <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                <div
                  className="h-full rounded-full bg-slate-800 transition-all dark:bg-slate-200"
                  style={{
                    width: `${Math.min(
                      100,
                      ((run.result_count ?? 0) / (run.item_total || 1)) * 100,
                    )}%`,
                  }}
                />
              </div>
            ) : null}
            {!run.results.length && running ? (
              <p className="text-sm text-slate-500">已启动，等待首题结果写入…</p>
            ) : null}
            <ul className="divide-y divide-slate-200/70 dark:divide-slate-800">
              {run.results.map((r) => (
                <li key={r.item_id} className="space-y-1 py-3 text-sm">
                  <p className="font-medium">{r.question}</p>
                  <p className="text-xs text-slate-500">
                    判定：{r.decision}
                    {r.correctness != null ? ` · 正确性 ${r.correctness}` : ""}
                    {r.grounding != null ? ` · 有据性 ${r.grounding}` : ""}
                  </p>
                  {r.correct_answer ? (
                    <p className="text-xs text-slate-500">标准：{r.correct_answer}</p>
                  ) : null}
                  <p className="text-slate-600 dark:text-slate-300">
                    模型：{r.model_answer || "（空）"}
                  </p>
                  {r.rationale ? (
                    <p className="text-xs text-slate-500">说明：{r.rationale}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}
