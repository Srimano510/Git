import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  ApiError,
  fetchContextResult,
  type ObservatoryPayload,
  type ObservatoryStrategy,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const STRATEGIES: ObservatoryStrategy[] = ["linear", "graph", "hybrid"];
const BAR: Record<ObservatoryStrategy, string> = {
  linear: "bg-red-500",
  graph: "bg-green-500",
  hybrid: "bg-amber-500",
};

/** `#4` for a message of the open chat; a short chat tag plus `#4` for another chat of the family. */
function nodeLabel(id: string, sessionKey: string): string {
  const at = id.lastIndexOf("#");
  if (id.slice(0, at) === sessionKey) return id.slice(at);
  return `…${id.slice(Math.max(0, at - 8), at)}${id.slice(at)}`;
}

interface Props {
  open: boolean;
  onClose: () => void;
  token: string;
  /** The active chat's key; the result is scoped to it. */
  sessionKey: string;
  /** Changes whenever the chat gains messages, so the result refetches. */
  refreshKey?: number;
}

/** Side-by-side view of what linear, graph and hybrid put in the context for the last turn. */
export default function ContextObservatory({
  open,
  onClose,
  token,
  sessionKey,
  refreshKey = 0,
}: Props) {
  const { t } = useTranslation();
  const [data, setData] = useState<ObservatoryPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [diffOnly, setDiffOnly] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    fetchContextResult(token, sessionKey)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setData(null);
        // 404 just means no turn has been recorded for this chat yet.
        setError(
          e instanceof ApiError && e.status === 404 ? null : e instanceof Error ? e.message : String(e),
        );
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [open, token, sessionKey, refreshKey]);

  const maxTokens = data ? Math.max(1, ...STRATEGIES.map((s) => data.strategies[s].tokens)) : 1;
  const rows = data?.nodes.filter((n) => !diffOnly || !STRATEGIES.every((s) => n.in[s])) ?? [];

  return (
    <>
      {open && <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />}
      <aside
        role="dialog"
        aria-label={t("thread.observatory.title")}
        aria-hidden={!open}
        className={cn(
          "fixed right-0 top-0 z-50 flex h-full w-full max-w-2xl flex-col border-l bg-background text-foreground shadow-xl transition-transform duration-200",
          open ? "translate-x-0" : "invisible translate-x-full",
        )}
      >
        <header className="flex items-center justify-between border-b px-4 py-3">
          <h2 className="text-base font-semibold">{t("thread.observatory.title")}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("thread.observatory.close")}
            className="rounded px-2 py-1 hover:bg-muted"
          >
            ✕
          </button>
        </header>

        {loading && !data && <p className="p-4 text-sm">{t("thread.observatory.loading")}</p>}
        {error && (
          <p role="alert" className="p-4 text-sm text-red-600 dark:text-red-400">
            {t("thread.observatory.error", { message: error })}
          </p>
        )}
        {!loading && !error && !data && (
          <p className="p-4 text-sm text-muted-foreground">{t("thread.observatory.empty")}</p>
        )}

        {data && (
          <div className="flex-1 overflow-y-auto">
            <p className="border-b px-4 py-2 text-xs text-muted-foreground">
              {t("thread.observatory.query", { text: data.query })}
              <br />
              {t("thread.observatory.reconstructed")}
            </p>

            <section className="grid gap-3 border-b p-4 sm:grid-cols-3">
              {STRATEGIES.map((s) => {
                const info = data.strategies[s];
                return (
                  <div key={s} data-testid={`observatory-card-${s}`} className="rounded border p-2 text-xs">
                    <div className="mb-1 flex items-center justify-between font-medium">
                      {t(`thread.observatory.strategy.${s}`)}
                      {data.selected === s ? (
                        <span className="rounded bg-foreground px-1 text-[10px] text-background">
                          {t("thread.observatory.used")}
                        </span>
                      ) : null}
                    </div>
                    <div>{t("thread.observatory.nodes", { count: info.nodes })}</div>
                    <div>{t("thread.observatory.tokens", { count: info.tokens })}</div>
                    <div>{t("thread.observatory.ms", { value: info.ms })}</div>
                    <div className="mt-1 h-2 rounded bg-muted">
                      <div
                        className={cn("h-2 rounded", BAR[s])}
                        style={{ width: `${(info.tokens / maxTokens) * 100}%` }}
                      />
                    </div>
                    {s === "hybrid" && info.recalled !== undefined ? (
                      <div className="mt-1 text-muted-foreground">
                        {t("thread.observatory.recalled", { count: info.recalled })}
                      </div>
                    ) : null}
                    <div className="text-muted-foreground">
                      {t("thread.observatory.onlyIn", { count: data.only[s] })}
                    </div>
                    {info.fallback ? (
                      <div className="mt-1 text-red-600 dark:text-red-400">
                        {t("thread.observatory.fallback", { reason: info.fallback })}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </section>

            <section className="space-y-2 border-b p-4">
              <h3 className="text-xs font-medium">{t("thread.observatory.timing")}</h3>
              {STRATEGIES.map((s) => {
                const tm = data.strategies[s].timing;
                const scale = Math.max(tm.total_ms, 0.001);
                return (
                  <div key={s} data-testid={`observatory-timing-${s}`} className="text-xs">
                    <div className="flex flex-wrap justify-between gap-x-2">
                      <span>{t(`thread.observatory.strategy.${s}`)}</span>
                      <span>
                        {t("thread.observatory.traversal")} {tm.traversal_ms} ·{" "}
                        {t("thread.observatory.vector")} {tm.vector_ms} · {t("thread.observatory.total")}{" "}
                        {tm.total_ms} ms
                      </span>
                    </div>
                    <div className="flex h-2 rounded bg-muted">
                      <div
                        className={cn("h-2 rounded-l", BAR[s])}
                        style={{ width: `${(tm.traversal_ms / scale) * 100}%` }}
                      />
                      <div className="h-2 bg-blue-500" style={{ width: `${(tm.vector_ms / scale) * 100}%` }} />
                    </div>
                  </div>
                );
              })}
            </section>

            <section className="p-4">
              <label className="mb-2 flex items-center gap-2 text-xs">
                <input type="checkbox" checked={diffOnly} onChange={(e) => setDiffOnly(e.target.checked)} />
                {t("thread.observatory.diffOnly")}
              </label>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b">
                      <th className="py-1 pr-2">{t("thread.observatory.colNode")}</th>
                      <th className="pr-2">{t("thread.observatory.colExcerpt")}</th>
                      <th className="pr-2">{t("thread.observatory.colTokens")}</th>
                      {STRATEGIES.map((s) => (
                        <th key={s} className="pr-2" title={t(`thread.observatory.strategy.${s}`)}>
                          {s[0].toUpperCase()}
                        </th>
                      ))}
                      <th>{t("thread.observatory.colReason")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((n) => (
                      <tr key={n.id} data-testid="observatory-row" className="border-b align-top">
                        <td className="py-1 pr-2 font-mono" title={n.id}>
                          {nodeLabel(n.id, sessionKey)} {n.role}
                        </td>
                        <td className="pr-2">{n.excerpt}</td>
                        <td className="pr-2">{n.tokens}</td>
                        {STRATEGIES.map((s) => (
                          <td
                            key={s}
                            data-strategy={s}
                            data-in={String(n.in[s])}
                            aria-label={`${t(`thread.observatory.strategy.${s}`)}: ${n.in[s] ? "✓" : "–"}`}
                            className="pr-2"
                          >
                            <span
                              className={cn("inline-block h-2 w-2 rounded-full", n.in[s] ? BAR[s] : "bg-muted")}
                            />
                          </td>
                        ))}
                        <td>
                          {(Object.entries(n.reason) as [ObservatoryStrategy, string][])
                            .map(([s, r]) => `${s}: ${r}`)
                            .join(" · ") || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        )}
      </aside>
    </>
  );
}
