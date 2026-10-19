import dagre from "@dagrejs/dagre";

export interface TreeNode {
  id: string;
  session_key: string;
  index: number;
  role: string | null;
  preview: string;
  fork_before_user_index: number;
  text?: string;
}

export interface TreeEdge {
  source: string;
  target: string;
  type: string;
}

export interface WorkflowNode {
  id: string;
  label: string;
  type: string;
  detail: string;
  ms?: number;
}

export interface TreePayload {
  root: string;
  nodes: TreeNode[];
  edges: TreeEdge[];
  tips: Record<string, string>;
  /** Last graph/hybrid turn: node id -> why it was used. Absent for linear chats. */
  context?: Record<string, "history" | "vector" | "summary">;
  context_strategy?: string | null;
  /** Last graph/hybrid turn's workflow steps, hung off the user message `anchor`. */
  workflow?: { anchor: string; nodes: WorkflowNode[]; edges: TreeEdge[] };
}

export interface DisplayNode {
  id: string;
  kind: "message" | "run" | "workflow";
  node?: TreeNode;
  workflow?: WorkflowNode;
  /** Folded message count for a `run` node. */
  count?: number;
  /** Ids of the messages folded into a `run` node. */
  members?: string[];
}

export interface PositionedNode extends DisplayNode {
  x: number;
  y: number;
}

export const MESSAGE_SIZE = { width: 190, height: 56 };
export const RUN_SIZE = { width: 190, height: 30 };
export const WORKFLOW_SIZE = { width: 190, height: 44 };
/** A run of linear replies shorter than this stays expanded. */
export const MIN_RUN = 3;

/**
 * Fold chains of plain REPLY nodes (one parent, one child) into a single `run` node.
 * Branch points, tips and `keep` ids always stay visible; `expanded` runs stay unfolded.
 */
export function collapseRuns(
  payload: TreePayload,
  keep: ReadonlySet<string> = new Set(),
  expanded: ReadonlySet<string> = new Set(),
): { nodes: DisplayNode[]; edges: TreeEdge[] } {
  const incoming = new Map<string, TreeEdge[]>();
  const outgoing = new Map<string, TreeEdge[]>();
  for (const e of payload.edges) {
    (incoming.get(e.target) ?? incoming.set(e.target, []).get(e.target)!).push(e);
    (outgoing.get(e.source) ?? outgoing.set(e.source, []).get(e.source)!).push(e);
  }
  const tips = new Set(Object.values(payload.tips));
  const inner = (id: string): boolean => {
    const i = incoming.get(id) ?? [];
    const o = outgoing.get(id) ?? [];
    return (
      i.length === 1 && o.length === 1 && i[0].type === "REPLY" && o[0].type === "REPLY"
      && !tips.has(id) && !keep.has(id)
    );
  };

  const runOf = new Map<string, string>();
  const runs = new Map<string, string[]>();
  for (const n of payload.nodes) {
    if (!inner(n.id)) continue;
    const parent = incoming.get(n.id)![0].source;
    if (inner(parent)) continue; // not the head of its chain
    const chain = [n.id];
    for (let next = outgoing.get(n.id)![0].target; inner(next); next = outgoing.get(next)![0].target) {
      chain.push(next);
    }
    const runId = `run:${n.id}`;
    if (chain.length < MIN_RUN || expanded.has(runId)) continue;
    runs.set(runId, chain);
    for (const id of chain) runOf.set(id, runId);
  }

  const nodes: DisplayNode[] = [];
  for (const n of payload.nodes) {
    const runId = runOf.get(n.id);
    if (runId === undefined) nodes.push({ id: n.id, kind: "message", node: n });
    else if (runs.get(runId)![0] === n.id) {
      nodes.push({
        id: runId,
        kind: "run",
        count: runs.get(runId)!.length,
        members: runs.get(runId)!,
      });
    }
  }
  const edges: TreeEdge[] = [];
  const seen = new Set<string>();
  for (const e of payload.edges) {
    const source = runOf.get(e.source) ?? e.source;
    const target = runOf.get(e.target) ?? e.target;
    if (source === target) continue;
    const key = `${source}>${target}>${e.type}`;
    if (seen.has(key)) continue;
    seen.add(key);
    edges.push({ source, target, type: e.type });
  }
  return { nodes, edges };
}

/** Append the last turn's workflow steps and edges to a (folded) tree. */
export function withWorkflow(
  folded: { nodes: DisplayNode[]; edges: TreeEdge[] },
  workflow: NonNullable<TreePayload["workflow"]>,
): { nodes: DisplayNode[]; edges: TreeEdge[] } {
  return {
    nodes: [
      ...folded.nodes,
      ...workflow.nodes.map<DisplayNode>((w) => ({ id: w.id, kind: "workflow", workflow: w })),
    ],
    edges: [...folded.edges, ...workflow.edges],
  };
}

/** Top-to-bottom tidy-tree layout; returns node centres. */
export function layoutTree(nodes: DisplayNode[], edges: TreeEdge[]): PositionedNode[] {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "TB", nodesep: 28, ranksep: 36 });
  g.setDefaultEdgeLabel(() => ({}));
  const size = (n: DisplayNode) =>
    n.kind === "run" ? RUN_SIZE : n.kind === "workflow" ? WORKFLOW_SIZE : MESSAGE_SIZE;
  for (const n of nodes) g.setNode(n.id, { ...size(n) });
  for (const e of edges) g.setEdge(e.source, e.target);
  dagre.layout(g);
  return nodes.map((n) => {
    const { x, y } = g.node(n.id);
    return { ...n, x: x - size(n).width / 2, y: y - size(n).height / 2 };
  });
}

/** Ids of `target` and everything upstream of it (the path from the root to that node). */
export function ancestorIds(edges: TreeEdge[], target: string | undefined): Set<string> {
  const parents = new Map<string, string[]>();
  for (const e of edges) (parents.get(e.target) ?? parents.set(e.target, []).get(e.target)!).push(e.source);
  const out = new Set<string>();
  const stack = target ? [target] : [];
  while (stack.length) {
    const id = stack.pop()!;
    if (out.has(id)) continue;
    out.add(id);
    stack.push(...(parents.get(id) ?? []));
  }
  return out;
}
