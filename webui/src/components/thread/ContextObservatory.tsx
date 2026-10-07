import { useEffect, useMemo, useState } from "react";

export interface ContextNodeInfo {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  source?: "ancestor" | "summary" | "vector" | "linear";
}

export interface ContextResult {
  strategy: "linear" | "graph";
  nodes: ContextNodeInfo[];
  node_ids: string[];
  reasons: Record<string, string>;
  token_count: number;
  retrieval_ms: number;
}

export interface ContextComparison {
  linear: ContextResult;
  graph: ContextResult;
}

export async function fetchContextComparison(
  sessionKey: string,
): Promise<ContextComparison> {
  const res = await fetch(
    `/api/sessions/${encodeURIComponent(sessionKey)}/context-result`,
  );
  if (!res.ok) throw new Error(`Failed to load context (${res.status})`);
  return res.json();
}

type DiffKind = "graph-only" | "linear-only" | "shared";

const DIFF_STYLE: Record<DiffKind, { dot: string; row: string; label: string }> = {
  "graph-only": { dot: "bg-green-500", row: "bg-green-500/10", label: "Graph only" },
  "linear-only": { dot: "bg-red-500", row: "bg-red-500/10", label: "Linear only" },
  shared: { dot: "bg-gray-400", row: "", label: "Shared" },
};

const snippet = (s: string, n = 80) => (s.length > n ? s.slice(0, n) + "…" : s);

interface Props {
  open: boolean;
  onClose: () => void;
  sessionKey: string;
  refreshKey?: number;
}

export default function ContextObservatory({
  open,
  onClose,
  sessionKey,
  refreshKey = 0,
}: Props) {
  const [data, setData] = useState<ContextComparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<"table" | "diff">("table");

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchContextComparison(sessionKey)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [open, sessionKey, refreshKey]);

  const diff = useMemo(() => {
    if (!data) return [];
    const linearIds = new Set(data.linear.node_ids);
    const graphIds = new Set(data.graph.node_ids);
    const byId = new Map<string, ContextNodeInfo>();
    [...data.linear.nodes, ...data.graph.nodes].forEach((n) => byId.set(n.id, n));
    return [...new Set([...data.linear.node_ids, ...data.graph.node_ids])].map(
      (id) => {
        const kind: DiffKind =
          linearIds.has(id) && graphIds.has(id)
            ? "shared"
            : graphIds.has(id)
              ? "graph-only"
              : "linear-only";
        return { id, kind, node: byId.get(id) };
      },
    );
  }, [data]);

  const maxTokens = data
    ? Math.max(data.linear.token_count, data.graph.token_count, 1)
    : 1;
  const saved = data ? data.linear.token_count - data.graph.token_count : 0;
  const savedPct =
    data && data.linear.token_count
      ? Math.round((saved / data.linear.token_count) * 100)
      : 0;

  return (
    <>
      {open && (
        <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />
      )}
      <aside
        role="dialog"
        aria-label="Context Observatory"
        className={`fixed right-0 top-0 z-50 flex h-full w-full max-w-xl flex-col border-l bg-white shadow-xl transition-transform duration-200 dark:bg-neutral-900 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <header className="flex items-center justify-between border-b px-4 py-3">
          <h2 className="text-base font-semibold">Context Observatory</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded px-2 py-1 hover:bg-black/5"
          >
            ✕
          </button>
        </header>

        {loading && <p className="p-4 text-sm">Loading context…</p>}
        {error && (
          <p className="p-4 text-sm text-red-600">
            Could not load context: {error}
          </p>
        )}
        {!loading && !error && !data && (
          <p className="p-4 text-sm">Send a message to see context data.</p>
        )}

        {data && (
          <div className="flex-1 overflow-y-auto">
            <section className="space-y-3 border-b p-4">
              {(["linear", "graph"] as const).map((k) => (
                <div key={k}>
                  <div className="mb-1 flex justify-between text-xs">
                    <span className="font-medium capitalize">{k}</span>
                    <span>
                      {data[k].token_count} tokens ·{" "}
                      {data[k].retrieval_ms.toFixed(1)} ms
                    </span>
                  </div>
                  <div className="h-2 rounded bg-black/10">
                    <div
                      className={`h-2 rounded ${
                        k === "graph" ? "bg-green-500" : "bg-red-500"
                      }`}
                      style={{
                        width: `${(data[k].token_count / maxTokens) * 100}%`,
                      }}
                    />
                  </div>
                </div>
              ))}
              <p className="text-xs">
                Tokens saved by Graph: <b>{saved}</b> ({savedPct}%)
              </p>
            </section>

            <div className="flex gap-2 border-b px-4 pt-2">
              {(["table", "diff"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={`px-3 py-2 text-sm ${
                    tab === t ? "border-b-2 border-blue-600 font-medium" : ""
                  }`}
                >
                  {t === "table" ? "Node table" : "Linear vs Graph"}
                </button>
              ))}
            </div>

            {tab === "table" && (
              <div className="overflow-x-auto p-4">
                <p className="mb-2 text-xs">
                  Active strategy: <b>{data.graph.strategy}</b>
                </p>
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b">
                      <th className="py-1 pr-2">Node</th>
                      <th className="pr-2">Role</th>
                      <th className="pr-2">Content</th>
                      <th className="pr-2">Source</th>
                      <th>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.graph.nodes.map((n) => (
                      <tr key={n.id} className="border-b align-top">
                        <td className="py-1 pr-2 font-mono">{n.id.slice(0, 13)}</td>
                        <td className="pr-2">{n.role}</td>
                        <td className="pr-2">{snippet(n.content)}</td>
                        <td className="pr-2">{n.source ?? "ancestor"}</td>
                        <td>{data.graph.reasons[n.id] ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {tab === "diff" && (
              <div className="space-y-1 p-4">
                <div className="mb-2 flex gap-3 text-xs">
                  {(Object.keys(DIFF_STYLE) as DiffKind[]).map((k) => (
                    <span key={k} className="flex items-center gap-1">
                      <span className={`h-2 w-2 rounded-full ${DIFF_STYLE[k].dot}`} />
                      {DIFF_STYLE[k].label}
                    </span>
                  ))}
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs font-medium">
                  <span>Linear</span>
                  <span>Graph</span>
                </div>
                {diff.map(({ id, kind, node }) => (
                  <div key={id} className="grid grid-cols-2 gap-2">
                    {(["linear", "graph"] as const).map((side) => {
                      const present =
                        kind === "shared" ||
                        (side === "graph"
                          ? kind === "graph-only"
                          : kind === "linear-only");
                      return (
                        <div
                          key={side}
                          className={`rounded p-2 text-xs ${
                            present ? DIFF_STYLE[kind].row : "opacity-20"
                          }`}
                        >
                          {present && node ? (
                            <>
                              <span className="font-medium">{node.role}: </span>
                              {snippet(node.content, 60)}
                            </>
                          ) : (
                            "—"
                          )}
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </aside>
    </>
  );
}