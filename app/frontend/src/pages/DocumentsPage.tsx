import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Trash2, Upload } from "lucide-react";

import { apiFetch, ApiError } from "../lib/api";

type DocumentItem = {
  id: string;
  filename: string;
  title?: string | null;
  status: string;
  vector_doc_id?: string | null;
  error_message?: string | null;
  created_at?: string | null;
};

const STATUS_LABEL: Record<string, string> = {
  pending: "排队中",
  processing: "入库中",
  ready: "可检索",
  failed: "失败",
  deleted: "已删除",
};

const IN_FLIGHT = new Set(["pending", "processing"]);

export default function DocumentsPage() {
  const [items, setItems] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimerRef = useRef<number | null>(null);
  const prevInFlightRef = useRef(false);

  const showToast = useCallback((message: string) => {
    setToast(message);
    if (toastTimerRef.current != null) {
      window.clearTimeout(toastTimerRef.current);
    }
    toastTimerRef.current = window.setTimeout(() => {
      setToast(null);
      toastTimerRef.current = null;
    }, 2400);
  }, []);

  useEffect(() => {
    return () => {
      if (toastTimerRef.current != null) {
        window.clearTimeout(toastTimerRef.current);
      }
    };
  }, []);

  const reload = useCallback(
    async (opts?: { quiet?: boolean }) => {
      if (!opts?.quiet) setLoading(true);
      try {
        const data = await apiFetch<{ items: DocumentItem[] }>("/documents");
        const next = data.items || [];
        setItems(next);

        const inFlight = next.some((d) => IN_FLIGHT.has(d.status));
        if (prevInFlightRef.current && !inFlight) {
          const failed = next.find((d) => d.status === "failed");
          if (failed) {
            showToast(
              failed.error_message
                ? `入库失败：${failed.error_message}`
                : "有文档入库失败",
            );
          } else if (next.some((d) => d.status === "ready")) {
            showToast("文档已可检索");
          }
        }
        prevInFlightRef.current = inFlight;
      } catch (err) {
        showToast(err instanceof ApiError ? err.detail : "加载文档失败");
      } finally {
        if (!opts?.quiet) setLoading(false);
      }
    },
    [showToast],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  // 有排队/入库中的文档时轮询
  const needsPoll = items.some((d) => IN_FLIGHT.has(d.status));
  useEffect(() => {
    if (!needsPoll) return;
    const timer = window.setInterval(() => {
      void reload({ quiet: true });
    }, 2000);
    return () => window.clearInterval(timer);
  }, [needsPoll, reload]);

  const onUpload = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const input = form.elements.namedItem("file") as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) {
      showToast("请先选择文件");
      return;
    }
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      await apiFetch("/documents/upload", { method: "POST", formData: fd });
      form.reset();
      await reload({ quiet: true });
      showToast("已提交，后台入库中…");
    } catch (err) {
      showToast(err instanceof ApiError ? err.detail : "上传失败");
    } finally {
      setUploading(false);
    }
  };

  const onDelete = async (id: string) => {
    if (!window.confirm("确定删除该文档？删除后对话将无法再检索到它。")) return;
    try {
      await apiFetch(`/documents/${id}`, { method: "DELETE" });
      await reload({ quiet: true });
      showToast("文档已删除");
    } catch (err) {
      showToast(err instanceof ApiError ? err.detail : "删除失败");
    }
  };

  return (
    <div className="relative h-full overflow-y-auto px-4 py-6 sm:px-8">
      {toast ? (
        <div
          role="alert"
          className="pointer-events-none absolute left-1/2 top-4 z-50 -translate-x-1/2 rounded-xl bg-slate-900 px-4 py-2.5 text-sm text-white shadow-lg dark:bg-slate-100 dark:text-slate-900"
        >
          {toast}
        </div>
      ) : null}

      <div className="mx-auto max-w-4xl space-y-6">
        <div>
          <h2 className="text-xl font-semibold">我的文档</h2>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            上传后立即返回，后台异步解析与嵌入；状态变为「可检索」后即可在对话中提问。
          </p>
        </div>

        <form
          onSubmit={onUpload}
          className="flex flex-col gap-3 rounded-2xl bg-white/80 p-4 ring-1 ring-slate-200/70 dark:bg-slate-900/70 dark:ring-slate-800 sm:flex-row sm:items-center"
        >
          <input
            name="file"
            type="file"
            accept=".txt,.md,.pdf,.html,.htm,.docx,.csv"
            className="flex-1 text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-slate-900 file:px-3 file:py-1.5 file:text-sm file:text-white dark:file:bg-slate-100 dark:file:text-slate-900"
          />
          <button
            type="submit"
            disabled={uploading}
            className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60 dark:bg-slate-100 dark:text-slate-900"
          >
            {uploading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Upload className="h-4 w-4" />
            )}
            {uploading ? "上传中…" : "加入知识库"}
          </button>
        </form>

        <div className="overflow-hidden rounded-2xl bg-white/80 ring-1 ring-slate-200/70 dark:bg-slate-900/70 dark:ring-slate-800">
          {loading ? (
            <p className="px-4 py-8 text-sm text-slate-500">加载中…</p>
          ) : items.length === 0 ? (
            <p className="px-4 py-8 text-sm text-slate-500">还没有文档，先上传一份试试。</p>
          ) : (
            <ul className="divide-y divide-slate-200/80 dark:divide-slate-800">
              {items.map((doc) => {
                const busy = IN_FLIGHT.has(doc.status);
                return (
                  <li
                    key={doc.id}
                    className="flex items-center justify-between gap-3 px-4 py-3"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{doc.filename}</p>
                      <p className="flex items-center gap-1.5 text-xs text-slate-500">
                        {busy ? (
                          <Loader2 className="h-3 w-3 shrink-0 animate-spin" />
                        ) : null}
                        状态：{STATUS_LABEL[doc.status] || doc.status}
                        {doc.error_message ? ` · ${doc.error_message}` : ""}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => void onDelete(doc.id)}
                      className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs text-rose-600 hover:bg-rose-50 dark:text-rose-300 dark:hover:bg-rose-950/40"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      删除
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
