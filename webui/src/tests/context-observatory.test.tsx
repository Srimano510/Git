import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ContextObservatory from "@/components/thread/ContextObservatory";
import type { ObservatoryPayload } from "@/lib/api";

const KEY = "websocket:a";

const timing = (t: number, v: number) => ({ traversal_ms: t, vector_ms: v, total_ms: t + v });

const payload: ObservatoryPayload = {
  at: 14,
  selected: "hybrid",
  reconstructed: true,
  query: "Which database do we use?",
  strategies: {
    linear: { nodes: 3, tokens: 40, ms: 0.2, fallback: null, timing: timing(0.2, 0) },
    graph: {
      nodes: 2, tokens: 30, ms: 1.5, fallback: null, timing: timing(1.5, 0),
      pruned: 5, embedder: "model2vec",
    },
    hybrid: {
      nodes: 3, tokens: 55, ms: 3.1, fallback: "RuntimeError: boom",
      timing: timing(1.6, 1.5), recalled: 1, summaries: 0,
    },
  },
  nodes: [
    { id: `${KEY}#0`, role: "user", excerpt: "archived Postgres question", tokens: 8,
      in: { linear: true, graph: false, hybrid: true }, reason: { hybrid: "vector (score 0.42)" } },
    { id: `${KEY}#4`, role: "assistant", excerpt: "shared answer", tokens: 9,
      in: { linear: true, graph: true, hybrid: true }, reason: { graph: "reply" } },
    { id: `${KEY}#5`, role: "user", excerpt: "linear and graph only", tokens: 6,
      in: { linear: true, graph: true, hybrid: false }, reason: {} },
  ],
  only: { linear: 0, graph: 0, hybrid: 0 },
};

function stubFetch(body: unknown, status = 200) {
  const fn = vi.fn(async () => ({
    ok: status === 200,
    status,
    json: async () => body,
    text: async () => (status === 200 ? "" : "no recorded turn"),
  }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

function renderOpen(props: Partial<{ open: boolean }> = {}) {
  return render(
    <ContextObservatory open={props.open ?? true} onClose={() => {}} token="tok" sessionKey={KEY} />,
  );
}

describe("ContextObservatory", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("asks for the active chat's result with the bearer token, and not while closed", async () => {
    const fetchMock = stubFetch(payload);
    const { unmount } = renderOpen({ open: false });
    expect(fetchMock).not.toHaveBeenCalled();
    unmount();

    renderOpen();
    await screen.findByTestId("observatory-card-linear");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/sessions/websocket%3Aa/context-result");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer tok");
  });

  it("shows a card per strategy with metrics, the used strategy and a fallback", async () => {
    stubFetch(payload);
    renderOpen();
    const hybrid = await screen.findByTestId("observatory-card-hybrid");
    expect(hybrid).toHaveTextContent("55 tokens");
    expect(hybrid).toHaveTextContent("3.1 ms");
    expect(hybrid).toHaveTextContent("used for this turn");
    expect(hybrid).toHaveTextContent("RuntimeError: boom");
    expect(screen.getByTestId("observatory-card-graph")).not.toHaveTextContent("used for this turn");
    const graph = screen.getByTestId("observatory-card-graph");
    expect(graph).toHaveTextContent("5 pruned by relevance");
    expect(graph).toHaveTextContent("Embedder: model2vec");
    expect(screen.getByTestId("observatory-card-linear")).not.toHaveTextContent("pruned");
    expect(screen.getByTestId("observatory-card-linear")).not.toHaveTextContent("Embedder");
    expect(screen.getByTestId("observatory-card-linear")).toHaveTextContent("40 tokens");
    expect(screen.getByTestId("observatory-timing-hybrid")).toHaveTextContent("1.5");
    expect(screen.getByText(/Which database do we use\?/)).toBeInTheDocument();
    expect(screen.getByText(/Rebuilt from the chat as it was before the last turn/)).toBeInTheDocument();
  });

  it("lists nodes with a mark per strategy and filters to the differences", async () => {
    stubFetch(payload);
    renderOpen();
    const rows = await screen.findAllByTestId("observatory-row");
    expect(rows).toHaveLength(3);
    const vectorRow = rows[0];
    expect(vectorRow).toHaveTextContent("archived Postgres question");
    expect(vectorRow).toHaveTextContent("vector (score 0.42)");
    expect(vectorRow.querySelector('[data-strategy="graph"]')).toHaveAttribute("data-in", "false");
    expect(vectorRow.querySelector('[data-strategy="hybrid"]')).toHaveAttribute("data-in", "true");

    fireEvent.click(screen.getByLabelText("Differences only"));
    await waitFor(() => expect(screen.getAllByTestId("observatory-row")).toHaveLength(2));
    expect(screen.queryByText("shared answer")).toBeNull();
  });

  it("labels nodes of the open chat as #n and nodes of other chats with a short tag", async () => {
    const long = "websocket:ea3fffa9-f3d7-4ef1-a71e-5696c83d15da";
    stubFetch({
      ...payload,
      nodes: [
        { ...payload.nodes[0], id: `${long}#4` },
        { ...payload.nodes[0], id: "websocket:0d0d30b2e66d#2" },
      ],
    });
    render(<ContextObservatory open onClose={() => {}} token="tok" sessionKey={long} />);
    const rows = await screen.findAllByTestId("observatory-row");
    expect(rows[0].querySelector("td")).toHaveTextContent(/^#4 user$/);
    expect(rows[1].querySelector("td")).toHaveTextContent("…30b2e66d#2 user");
    expect(rows[1].querySelector("td")).toHaveAttribute("title", "websocket:0d0d30b2e66d#2");
  });

  it("keeps the fallback reason readable in dark mode", async () => {
    stubFetch(payload);
    renderOpen();
    const reason = await screen.findByText(/RuntimeError: boom/);
    expect(reason.className).toContain("dark:text-red-400");
  });

  it("explains an empty chat instead of failing, and reports other errors", async () => {
    stubFetch({}, 404);
    const { unmount } = renderOpen();
    expect(await screen.findByText(/Send a message/)).toBeInTheDocument();
    unmount();

    stubFetch({}, 500);
    renderOpen();
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load context");
  });
});
