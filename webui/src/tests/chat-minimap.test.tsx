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
});
