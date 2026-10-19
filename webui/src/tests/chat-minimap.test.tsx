import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatMinimap } from "@/components/thread/ChatMinimap";
import type { TreePayload } from "@/lib/chat-tree";

const KEY = "websocket:m";
const id = (i: number) => `${KEY}#${i}`;

function chain(length: number): TreePayload {
  const nodes = Array.from({ length }, (_, i) => ({
    id: id(i),
    session_key: KEY,
    index: i,
    role: i % 2 ? "assistant" : "user",
    preview: `message ${i}`,
    fork_before_user_index: Math.ceil(i / 2),
  }));
  return {
    root: KEY,
    nodes,
    edges: nodes.slice(1).map((n, i) => ({ source: id(i), target: n.id, type: "REPLY" })),
    tips: { [KEY]: id(length - 1) },
  };
}

function stubGraph(payload: TreePayload) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, status: 200, json: async () => payload, text: async () => "" })),
  );
}

describe("ChatMinimap", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("folds a long linear run, expands it on click, and reports node selection", async () => {
    stubGraph(chain(7));
    const onSelectNode = vi.fn();
    render(<ChatMinimap token="t" sessionKey={KEY} onSelectNode={onSelectNode} onClose={() => {}} />);

    const run = await screen.findByTestId("minimap-run");
    expect(run).toHaveTextContent("+5 messages");
    expect(document.querySelector(`[data-id="${id(3)}"]`)).toBeNull();

    fireEvent.click(document.querySelector(`[data-id^="run:"]`) as HTMLElement);
    await waitFor(() => expect(document.querySelector(`[data-id="${id(3)}"]`)).not.toBeNull());
    expect(screen.queryByTestId("minimap-run")).toBeNull();

    fireEvent.click(document.querySelector(`[data-id="${id(3)}"]`) as HTMLElement);
    expect(onSelectNode).toHaveBeenCalledWith(expect.objectContaining({ id: id(3) }), false);

    fireEvent.click(document.querySelector(`[data-id="${id(6)}"]`) as HTMLElement);
    expect(onSelectNode).toHaveBeenLastCalledWith(expect.objectContaining({ id: id(6) }), true);
  });

  it("draws the last turn's workflow only while the Workflow toggle is on", async () => {
    const payload: TreePayload = {
      ...chain(2),
      workflow: {
        anchor: id(0),
        nodes: [
          { id: "workflow#0", label: "ContextStrategySelection", type: "intent", detail: "graph" },
          { id: "workflow#1", label: "GraphTraversal", type: "tool", detail: "visited 2", ms: 1.5 },
        ],
        edges: [
          { source: id(0), target: "workflow#0", type: "TRIGGERS" },
          { source: "workflow#0", target: "workflow#1", type: "TRIGGERS" },
        ],
      },
    };
    stubGraph(payload);
    render(<ChatMinimap token="t" sessionKey={KEY} onSelectNode={() => {}} onClose={() => {}} />);

    const toggle = await screen.findByRole("button", { name: "Show workflow" });
    expect(screen.queryAllByTestId("minimap-workflow")).toHaveLength(0);

    fireEvent.click(toggle);
    await waitFor(() => expect(screen.getAllByTestId("minimap-workflow")).toHaveLength(2));
    expect(screen.getByText("GraphTraversal")).toBeInTheDocument();
    expect(screen.getByText(/1\.5 ms/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Hide workflow" }));
    await waitFor(() => expect(screen.queryAllByTestId("minimap-workflow")).toHaveLength(0));
  });

  it("offers no Workflow toggle when the last turn left no trace", async () => {
    stubGraph(chain(2));
    render(<ChatMinimap token="t" sessionKey={KEY} onSelectNode={() => {}} onClose={() => {}} />);
    await screen.findAllByTestId("minimap-node");
    expect(screen.queryByRole("button", { name: /workflow/i })).toBeNull();
  });

  it("shows an error when the graph cannot be loaded", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}), text: async () => "" })));
    render(<ChatMinimap token="t" sessionKey={KEY} onSelectNode={() => {}} onClose={() => {}} />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("toggles the wide layout and closes", async () => {
    stubGraph(chain(2));
    const onClose = vi.fn();
    render(<ChatMinimap token="t" sessionKey={KEY} onSelectNode={() => {}} onClose={onClose} />);
    await screen.findAllByTestId("minimap-node");
    fireEvent.click(screen.getByLabelText("Expand chat tree"));
    expect(screen.getByLabelText("Shrink chat tree")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Close chat tree"));
    expect(onClose).toHaveBeenCalled();
  });

  it("hides the overview map by default and toggles it", async () => {
    stubGraph(chain(3));
    render(<ChatMinimap token="t" sessionKey={KEY} onSelectNode={() => {}} onClose={() => {}} />);
    await screen.findAllByTestId("minimap-node");
    expect(document.querySelector(".react-flow__minimap")).toBeNull();
    fireEvent.click(screen.getByLabelText("Show overview map"));
    expect(document.querySelector(".react-flow__minimap")).not.toBeNull();
    fireEvent.click(screen.getByLabelText("Hide overview map"));
    expect(document.querySelector(".react-flow__minimap")).toBeNull();
  });

  it("marks recalled nodes, shows a legend, and keeps them out of folded runs", async () => {
    const payload = chain(9);
    payload.context = { [id(4)]: "vector", [id(6)]: "history", [id(8)]: "history", [id(0)]: "summary" };
    payload.context_strategy = "hybrid";
    stubGraph(payload);
    render(<ChatMinimap token="t" sessionKey={KEY} onSelectNode={() => {}} onClose={() => {}} />);

    expect(await screen.findByTestId("minimap-legend")).toHaveTextContent("hybrid");
    // node 4 sits in the middle of a linear run but is recalled, so it stays visible
    await waitFor(() => expect(document.querySelector(`[data-id="${id(4)}"]`)).not.toBeNull());
    expect(screen.getByTestId("minimap-kind-vector")).toHaveTextContent("vector");
    expect(screen.getByTestId("minimap-kind-summary")).toBeInTheDocument();
    expect(screen.getByTestId("minimap-kind-history")).toBeInTheDocument();
    // the folded stretches around them are history that was in context
    expect(screen.getAllByTestId("minimap-run").some((r) => r.textContent?.includes("in context"))).toBe(true);
  });

  it("shows no legend or markers for chats without a recorded context", async () => {
    stubGraph(chain(3));
    render(<ChatMinimap token="t" sessionKey={KEY} onSelectNode={() => {}} onClose={() => {}} />);
    await screen.findAllByTestId("minimap-node");
    expect(screen.queryByTestId("minimap-legend")).toBeNull();
    expect(screen.queryByTestId("minimap-kind-vector")).toBeNull();
  });
});
