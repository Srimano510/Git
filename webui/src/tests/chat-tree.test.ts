import { describe, expect, it } from "vitest";

import {
  ancestorIds,
  collapseRuns,
  layoutTree,
  type TreeNode,
  type TreePayload,
} from "@/lib/chat-tree";

const node = (id: string, role = "user"): TreeNode => ({
  id,
  session_key: id.split("#")[0],
  index: Number(id.split("#")[1]),
  role,
  preview: id,
  fork_before_user_index: 0,
});

/** s#0..s#7 chain; s#3 branches to k#4 -> k#5. */
function payload(): TreePayload {
  const ids = Array.from({ length: 8 }, (_, i) => `s#${i}`);
  const edges = ids.slice(1).map((id, i) => ({ source: ids[i], target: id, type: "REPLY" }));
  return {
    root: "s",
    nodes: [...ids, "k#4", "k#5"].map((id) => node(id)),
    edges: [
      ...edges,
      { source: "s#3", target: "k#4", type: "BRANCH" },
      { source: "k#4", target: "k#5", type: "REPLY" },
    ],
    tips: { s: "s#7", k: "k#5" },
  };
}

describe("collapseRuns", () => {
  it("folds linear stretches but keeps branch points and tips", () => {
    const { nodes, edges } = collapseRuns(payload());
    const ids = nodes.map((n) => n.id);
    // s#1,s#2 is a run of 2 (< MIN_RUN) so it stays; s#4..s#6 folds
    expect(ids).toContain("s#3");
    expect(ids).toContain("s#7");
    expect(ids).toContain("run:s#4");
    expect(ids).not.toContain("s#5");
    expect(nodes.find((n) => n.id === "run:s#4")?.count).toBe(3);
    expect(nodes.find((n) => n.id === "run:s#4")?.members).toEqual(["s#4", "s#5", "s#6"]);
    expect(edges).toContainEqual({ source: "s#3", target: "run:s#4", type: "REPLY" });
    expect(edges).toContainEqual({ source: "run:s#4", target: "s#7", type: "REPLY" });
    expect(edges).toContainEqual({ source: "s#3", target: "k#4", type: "BRANCH" });
  });

  it("keeps requested ids visible and splits the run around them", () => {
    const { nodes } = collapseRuns(payload(), new Set(["s#5"]));
    expect(nodes.map((n) => n.id)).toContain("s#5");
    expect(nodes.some((n) => n.kind === "run")).toBe(false);
  });

  it("leaves an expanded run unfolded", () => {
    const { nodes } = collapseRuns(payload(), new Set(), new Set(["run:s#4"]));
    expect(nodes.map((n) => n.id)).toEqual(expect.arrayContaining(["s#4", "s#5", "s#6"]));
    expect(nodes.some((n) => n.kind === "run")).toBe(false);
  });
});

describe("layoutTree", () => {
  it("is deterministic and places children below parents", () => {
    const { nodes, edges } = collapseRuns(payload());
    const a = layoutTree(nodes, edges);
    const b = layoutTree(nodes, edges);
    expect(a).toEqual(b);
    const y = (id: string) => a.find((n) => n.id === id)!.y;
    expect(y("s#3")).toBeLessThan(y("k#4"));
    expect(y("s#3")).toBeLessThan(y("run:s#4"));
    const x = (id: string) => a.find((n) => n.id === id)!.x;
    expect(x("k#4")).not.toBe(x("run:s#4"));
  });
});

describe("ancestorIds", () => {
  it("returns the path from the root, excluding other branches", () => {
    const path = ancestorIds(payload().edges, "k#5");
    expect([...path].sort()).toEqual(["k#4", "k#5", "s#0", "s#1", "s#2", "s#3"]);
    expect(ancestorIds(payload().edges, undefined).size).toBe(0);
  });
});
