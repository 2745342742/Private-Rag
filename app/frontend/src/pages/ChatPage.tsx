import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { Check, Loader2, Pencil, Plus, Send, Trash2, X } from "lucide-react";

import { apiFetch, apiSseChat, ApiError } from "../lib/api";

type Conversation = {
  id: string;
  title?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

type Citation = {
  document_id?: string;
  filename?: string;
  title?: string;
  score?: number;
};

type Message = {
  id: string;
  role: string;
  content: string;
  citations?: Citation[];
  latency_ms?: number | null;
  created_at?: string | null;
};

export default function ChatPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loadingList, setLoadingList] = useState(true);
  const [loadingMsgs, setLoadingMsgs] = useState(false);
  const [sending, setSending] = useState(false);
  const [streamStage, setStreamStage] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const toastTimerRef = useRef<number | null>(null);

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

  const loadConversations = useCallback(async () => {
    setLoadingList(true);
    try {
      const data = await apiFetch<{ items: Conversation[] }>("/conversations");
      setConversations(data.items || []);
    } catch (err) {
      showToast(err instanceof ApiError ? err.detail : "加载会话失败");
    } finally {
      setLoadingList(false);
    }
  }, [showToast]);

  const loadMessages = useCallback(
    async (id: string) => {
      setLoadingMsgs(true);
      try {
        const data = await apiFetch<{ items: Message[] }>(
          `/conversations/${id}/messages`,
        );
        setMessages(data.items || []);
      } catch (err) {
        showToast(err instanceof ApiError ? err.detail : "加载消息失败");
      } finally {
        setLoadingMsgs(false);
      }
    },
    [showToast],
  );

  useEffect(() => {
    void loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    if (activeId) void loadMessages(activeId);
    else setMessages([]);
  }, [activeId, loadMessages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending, streamStage]);

  const createConversation = async () => {
    try {
      const conv = await apiFetch<Conversation>("/conversations", {
        method: "POST",
        body: {},
      });
      setConversations((prev) => [conv, ...prev]);
      setActiveId(conv.id);
      setMessages([]);
    } catch (err) {
      showToast(err instanceof ApiError ? err.detail : "创建会话失败");
    }
  };

  const startRename = (c: Conversation) => {
    setRenamingId(c.id);
    setRenameDraft(c.title || "");
  };

  const cancelRename = () => {
    setRenamingId(null);
    setRenameDraft("");
  };

  const commitRename = async (id: string) => {
    const title = renameDraft.trim();
    if (!title) {
      showToast("标题不能为空");
      return;
    }
    try {
      const updated = await apiFetch<Conversation>(`/conversations/${id}`, {
        method: "PATCH",
        body: { title },
      });
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? { ...c, ...updated } : c)),
      );
      cancelRename();
    } catch (err) {
      showToast(err instanceof ApiError ? err.detail : "重命名失败");
    }
  };

  const deleteConversation = async (id: string) => {
    if (!window.confirm("确定删除该对话？消息也会一并删除。")) return;
    try {
      await apiFetch(`/conversations/${id}`, { method: "DELETE" });
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (activeId === id) {
        setActiveId(null);
        setMessages([]);
      }
      if (renamingId === id) cancelRename();
    } catch (err) {
      showToast(err instanceof ApiError ? err.detail : "删除失败");
    }
  };

  const onSend = async (e: FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;

    setSending(true);
    setStreamStage(null);
    setInput("");

    const tmpUserId = `tmp-user-${Date.now()}`;
    const tmpAsstId = `tmp-asst-${Date.now()}`;

    try {
      let convId = activeId;
      if (!convId) {
        const conv = await apiFetch<Conversation>("/conversations", {
          method: "POST",
          body: {},
        });
        convId = conv.id;
        setConversations((prev) => [conv, ...prev]);
        setActiveId(conv.id);
      }

      setMessages((prev) => [
        ...prev,
        { id: tmpUserId, role: "user", content: text },
        { id: tmpAsstId, role: "assistant", content: "" },
      ]);
      setStreamStage("retrieving");

      let streamError: string | null = null;

      await apiSseChat(
        `/conversations/${convId}/messages/stream`,
        { content: text },
        (event) => {
          if (event.type === "user_message") {
            const msg = event.message as Message;
            setMessages((prev) =>
              prev.map((m) => (m.id === tmpUserId ? msg : m)),
            );
          } else if (event.type === "status") {
            setStreamStage(event.stage || null);
          } else if (event.type === "token") {
            setStreamStage("generating");
            setMessages((prev) =>
              prev.map((m) =>
                m.id === tmpAsstId
                  ? { ...m, content: m.content + (event.text || "") }
                  : m,
              ),
            );
          } else if (event.type === "done") {
            const msg = event.assistant_message as Message;
            setMessages((prev) =>
              prev.map((m) => (m.id === tmpAsstId ? msg : m)),
            );
            setStreamStage(null);
          } else if (event.type === "error") {
            streamError = event.detail || "流式问答失败";
          }
        },
      );

      if (streamError) {
        throw new ApiError(500, streamError);
      }

      void loadConversations();
    } catch (err) {
      setMessages((prev) =>
        prev.filter((m) => m.id !== tmpUserId && m.id !== tmpAsstId),
      );
      showToast(err instanceof ApiError ? err.detail : "发送失败");
    } finally {
      setSending(false);
      setStreamStage(null);
    }
  };

  const stageLabel =
    streamStage === "retrieving"
      ? "正在检索知识库…"
      : streamStage === "generating"
        ? "正在生成…"
        : sending
          ? "处理中…"
          : null;

  return (
    <div className="relative flex h-full min-h-0">
      {toast ? (
        <div
          role="alert"
          className="pointer-events-none absolute left-1/2 top-4 z-50 -translate-x-1/2 rounded-xl bg-slate-900 px-4 py-2.5 text-sm text-white shadow-lg dark:bg-slate-100 dark:text-slate-900"
        >
          {toast}
        </div>
      ) : null}
      <aside className="flex w-64 shrink-0 flex-col border-r border-slate-200/80 bg-white/60 dark:border-slate-800 dark:bg-slate-950/40">
        <div className="p-3">
          <button
            type="button"
            onClick={() => void createConversation()}
            className="flex w-full items-center justify-center gap-1.5 rounded-xl bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900"
          >
            <Plus className="h-4 w-4" />
            新对话
          </button>
        </div>
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto px-2 pb-3">
          {loadingList ? (
            <p className="px-2 py-3 text-xs text-slate-500">加载中…</p>
          ) : conversations.length === 0 ? (
            <p className="px-2 py-3 text-xs text-slate-500">暂无会话</p>
          ) : (
            conversations.map((c) => (
              <div
                key={c.id}
                className={clsx(
                  "group flex items-center gap-1 rounded-lg px-1.5 py-1 transition",
                  activeId === c.id
                    ? "bg-slate-200/90 text-slate-900 dark:bg-slate-800 dark:text-slate-50"
                    : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-900",
                )}
              >
                {renamingId === c.id ? (
                  <>
                    <input
                      autoFocus
                      value={renameDraft}
                      onChange={(e) => setRenameDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          void commitRename(c.id);
                        } else if (e.key === "Escape") {
                          cancelRename();
                        }
                      }}
                      className="min-w-0 flex-1 rounded-md border border-slate-300 bg-white px-2 py-1 text-sm outline-none dark:border-slate-600 dark:bg-slate-950"
                    />
                    <button
                      type="button"
                      title="保存"
                      onClick={() => void commitRename(c.id)}
                      className="rounded p-1 text-emerald-600 hover:bg-white/70 dark:hover:bg-slate-950/60"
                    >
                      <Check className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      title="取消"
                      onClick={cancelRename}
                      className="rounded p-1 text-slate-500 hover:bg-white/70 dark:hover:bg-slate-950/60"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => setActiveId(c.id)}
                      className="min-w-0 flex-1 truncate px-1.5 py-1 text-left text-sm"
                    >
                      {c.title || "未命名对话"}
                    </button>
                    <button
                      type="button"
                      title="重命名"
                      onClick={() => startRename(c)}
                      className="rounded p-1 text-slate-500 opacity-100 hover:bg-white/70 hover:text-slate-800 sm:opacity-0 sm:group-hover:opacity-100 dark:hover:bg-slate-950/60 dark:hover:text-slate-100"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      title="删除"
                      onClick={() => void deleteConversation(c.id)}
                      className="rounded p-1 text-rose-500 opacity-100 hover:bg-rose-50 sm:opacity-0 sm:group-hover:opacity-100 dark:hover:bg-rose-950/40"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </>
                )}
              </div>
            ))
          )}
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-6 sm:px-8">
          {!activeId && messages.length === 0 ? (
            <div className="mx-auto mt-24 max-w-lg text-center">
              <h2 className="text-xl font-semibold">向你的知识库提问</h2>
              <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                先在「文档」页上传资料，再回到这里提问。回答会基于你的个人文档检索生成。
              </p>
            </div>
          ) : null}

          {loadingMsgs ? (
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载消息…
            </div>
          ) : null}

          {messages.map((m) => (
            <div
              key={m.id}
              className={clsx(
                "mx-auto max-w-3xl rounded-2xl px-4 py-3 text-sm leading-relaxed",
                m.role === "user"
                  ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                  : "bg-white/80 ring-1 ring-slate-200/70 dark:bg-slate-900/70 dark:ring-slate-800",
              )}
            >
              <div className="mb-1 text-[11px] uppercase tracking-wide opacity-60">
                {m.role === "user" ? "你" : "助手"}
                {m.latency_ms != null ? ` · ${m.latency_ms} ms` : ""}
              </div>
              <div className="whitespace-pre-wrap">
                {m.content ||
                  (m.role === "assistant" &&
                  sending &&
                  m.id.startsWith("tmp-asst")
                    ? "…"
                    : "")}
              </div>
              {m.role === "assistant" && m.citations && m.citations.length > 0 ? (
                <div className="mt-3 flex flex-wrap gap-1.5 border-t border-slate-200/60 pt-2 dark:border-slate-700/60">
                  {m.citations.map((cit, idx) => (
                    <span
                      key={`${cit.document_id}-${idx}`}
                      className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300"
                    >
                      {cit.filename || cit.title || cit.document_id || "引用"}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          ))}

          {stageLabel ? (
            <div className="mx-auto flex max-w-3xl items-center gap-2 text-sm text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              {stageLabel}
            </div>
          ) : null}
          <div ref={bottomRef} />
        </div>

        <form
          onSubmit={onSend}
          className="border-t border-slate-200/80 bg-white/70 px-4 py-3 backdrop-blur dark:border-slate-800 dark:bg-slate-950/50 sm:px-8"
        >
          <div className="mx-auto flex max-w-3xl gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="向知识库提问…"
              disabled={sending}
              className="flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-slate-400 dark:border-slate-700 dark:bg-slate-900"
            />
            <button
              type="submit"
              disabled={sending || !input.trim()}
              className="inline-flex items-center gap-1 rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
            >
              <Send className="h-4 w-4" />
              发送
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
