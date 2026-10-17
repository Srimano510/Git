import "@xyflow/react/dist/style.css";

import {
  Background,
  Controls,
  Handle,
  MiniMap,
  PanOnScrollMode,
  Position,
  ReactFlow,
  useReactFlow,
  useStore,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { Map as MapIcon, Maximize2, Minimize2, X } from "lucide-react";
import { memo, useEffect, useMemo, useRef, useState } from "react";

import { fetchSessionGraph } from "@/lib/api";
import {
  ancestorIds,
  collapseRuns,
  layoutTree,
  MESSAGE_SIZE,
  RUN_SIZE,
  type TreeNode,
  type TreePayload,
} from "@/lib/chat-tree";
import { cn } from "@/lib/utils";

interface ChatNodeData extends Record<string, unknown> {
  node?: TreeNode;
  count?: number;
  active: boolean;
  selected: boolean;
  kind?: "history" | "vector" | "summary";
  /** A folded run whose messages were part of the last turn's context. */
  inContext?: boolean;
}

const KIND_COLOR = { vector: "#f59e0b", summary: "#14b8a6" } as const;

const ROLE_COLOR: Record<string, string> = {
  user: "#3b82f6",
  assistant: "#10b981",
  tool: "#a3a3a3",
};
const roleColor = (role: string | null | undefined) => ROLE_COLOR[role ?? ""] ?? "#a3a3a3";

const handles = (
  <>
    <Handle type="target" position={Position.Top} className="!opacity-0" isConnectable={false} />
    <Handle type="source" position={Position.Bottom} className="!opacity-0" isConnectable={false} />
  </>
);

/** Level of detail: dot when zoomed out, one line at mid zoom, full text when zoomed in. */
const ChatNodeView = memo(function ChatNodeView({ data }: NodeProps<Node<ChatNodeData>>) {
  const zoom = useStore((s) => s.transform[2]);
  const { node, count, active, selected, kind, inContext } = data;
  const flagged = kind === "vector" || kind === "summary" ? kind : null;
  const ring = selected
    ? "ring-2 ring-amber-500"
    : active
      ? "ring-2 ring-foreground/40"
      : "";
  if (!node) {
    return (
      <div
        data-testid="minimap-run"
        style={RUN_SIZE}
        className="flex items-center justify-center rounded-full border border-dashed bg-muted text-[11px] text-muted-foreground"
      >
        {handles}
        +{count} messages{inContext ? " · in context" : ""}
      </div>
    );
  }
  if (zoom < 0.3) {
    return (
      <div
        data-testid="minimap-node"
        style={{
          ...MESSAGE_SIZE,
          background: roleColor(node.role),
          opacity: active ? 1 : 0.55,
          ...(flagged ? { outline: `4px solid ${KIND_COLOR[flagged]}` } : {}),
        }}
        className={cn("rounded-md", ring)}
      >
        {handles}
      </div>
    );
  }
  return (
    <div
      data-testid="minimap-node"
      style={MESSAGE_SIZE}
      className={cn(
        "overflow-hidden rounded-md border bg-card px-2 py-1 text-left text-[11px] leading-snug",
        active ? "" : "opacity-70",
        ring,
      )}
    >
      {handles}
      <div className="flex items-center gap-1 font-medium">
        <span
          className="inline-block h-2 w-2 rounded-full"
          style={{ background: roleColor(node.role) }}
        />
        {node.role}
        <span className="text-muted-foreground">#{node.index}</span>
        {flagged ? (
          <span
            data-testid={`minimap-kind-${flagged}`}
            className="ml-auto rounded px-1 text-[9px] font-semibold text-white"
            style={{ background: KIND_COLOR[flagged] }}
          >
            {flagged}
          </span>
        ) : kind === "history" ? (
          <span data-testid="minimap-kind-history" className="ml-auto text-[9px] text-muted-foreground">
            in context
          </span>
        ) : null}
      </div>
      <div className={zoom < 0.6 ? "truncate" : "line-clamp-2"}>{node.preview}</div>
    </div>
  );
});

const nodeTypes = { chat: ChatNodeView };

/** Frames the end of the active path once per chat; later refetches never move the view. */
function FocusOnLoad({ focus, chatKey }: { focus: { id: string }[]; chatKey: string }) {
  const { fitView } = useReactFlow();
  const framed = useRef<string | null>(null);
  useEffect(() => {
    if (focus.length === 0 || framed.current === chatKey) return;
    framed.current = chatKey;
    const id = requestAnimationFrame(() =>
      fitView({ nodes: focus, padding: 0.15, minZoom: 0.3, maxZoom: 1, duration: 0 }),
    );
    return () => cancelAnimationFrame(id);
  }, [focus, chatKey, fitView]);
  return null;
}

interface ChatMinimapProps {
  token: string;
  sessionKey: string;
  /** Changes whenever the open chat gains messages, so the tree refetches. */
  refreshKey?: number;
  selectedNodeId?: string | null;
  theme?: "light" | "dark";
  /** `isTip` is true for the last message of any chat (nothing to branch from). */
  onSelectNode: (node: TreeNode, isTip: boolean) => void;
  onClose: () => void;
}

export function ChatMinimap({
  token,
  sessionKey,
  refreshKey = 0,
  selectedNodeId = null,
  theme = "light",
  onSelectNode,
  onClose,
}: ChatMinimapProps) {
  const [payload, setPayload] = useState<TreePayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const [wide, setWide] = useState(false);
  const [showOverview, setShowOverview] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchSessionGraph(token, sessionKey)
      .then((p) => {
        if (cancelled) return;
        setPayload(p);
        setError(null);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [token, sessionKey, refreshKey]);

  const { nodes, edges, focus } = useMemo(() => {
    if (!payload) {
      return { nodes: [] as Node<ChatNodeData>[], edges: [] as Edge[], focus: [] as { id: string }[] };
    }
    // Recalled nodes must stay visible, so they are never folded into a "+N messages" run.
    const keep = new Set(selectedNodeId ? [selectedNodeId] : []);
    for (const [id, kind] of Object.entries(payload.context ?? {})) {
      if (kind !== "history") keep.add(id);
    }
    const folded = collapseRuns(payload, keep, expanded);
    const active = ancestorIds(payload.edges, payload.tips[sessionKey]);
    const flowNodes = layoutTree(folded.nodes, folded.edges).map<Node<ChatNodeData>>((n) => ({
      id: n.id,
      type: "chat",
      position: { x: n.x, y: n.y },
      draggable: false,
      ...(n.kind === "run" ? RUN_SIZE : MESSAGE_SIZE),
      data: {
        node: n.node,
        count: n.count,
        active: n.members ? n.members.some((id) => active.has(id)) : active.has(n.id),
        selected: n.id === selectedNodeId,
        kind: payload.context?.[n.id],
        inContext: n.members?.some((m) => payload.context?.[m] === "history"),
      },
    }));
    const flowEdges = folded.edges.map<Edge>((e) => ({
      id: `${e.source}>${e.target}>${e.type}`,
      source: e.source,
      target: e.target,
      type: "smoothstep",
      style: {
        stroke: "#94a3b8",
        strokeWidth: 1.5,
        ...(e.type === "BRANCH" ? { strokeDasharray: "5 4" } : {}),
      },
    }));
    // Start on the end of the active path at a readable zoom; the overview map shows the rest.
    const focusNodes = flowNodes
      .filter((n) => n.data.active)
      .sort((a, b) => b.position.y - a.position.y)
      .slice(0, 6)
      .map((n) => ({ id: n.id }));
    return { nodes: flowNodes, edges: flowEdges, focus: focusNodes };
  }, [payload, expanded, selectedNodeId, sessionKey]);

  return (
    <aside
      aria-label="Chat tree"
      className={cn(
        "flex shrink-0 flex-col border-l bg-background max-md:absolute max-md:inset-y-0 max-md:right-0 max-md:z-20 max-md:shadow-xl",
        wide ? "w-[55%] min-w-[360px]" : "w-[360px] max-w-[90vw]",
      )}
    >
      <header className="flex items-center justify-between border-b px-3 py-2 text-sm font-medium">
        Chat tree
        <span className="flex gap-1">
          <button
            type="button"
            aria-label={showOverview ? "Hide overview map" : "Show overview map"}
            aria-pressed={showOverview}
            onClick={() => setShowOverview((v) => !v)}
          >
            <MapIcon size={14} />
          </button>
          <button
            type="button"
            aria-label={wide ? "Shrink chat tree" : "Expand chat tree"}
            onClick={() => setWide((w) => !w)}
          >
            {wide ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
          <button type="button" aria-label="Close chat tree" onClick={onClose}>
            <X size={14} />
          </button>
        </span>
      </header>
      {payload?.context ? (
        <p data-testid="minimap-legend" className="border-b px-3 py-1 text-[11px] text-muted-foreground">
          Last turn ({payload.context_strategy ?? "graph"}):{" "}
          <span style={{ color: KIND_COLOR.vector }}>vector</span>{" · "}
          <span style={{ color: KIND_COLOR.summary }}>summary</span>{" · in context"}
        </p>
      ) : null}
      <div className="relative min-h-0 flex-1">
        {error ? (
          <p role="alert" className="p-3 text-xs text-destructive">{error}</p>
        ) : (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            colorMode={theme}
            panOnScroll
            panOnScrollMode={PanOnScrollMode.Free}
            zoomOnScroll={false}
            zoomActivationKeyCode={["Control", "Meta"]}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            minZoom={0.1}
            maxZoom={2}
            proOptions={{ hideAttribution: true }}
            onNodeClick={(_, n) => {
              const data = n.data as ChatNodeData;
              if (data.node) {
                onSelectNode(data.node, Object.values(payload?.tips ?? {}).includes(data.node.id));
              }
              else setExpanded((prev) => new Set(prev).add(n.id));
            }}
          >
            <FocusOnLoad focus={focus} chatKey={`${sessionKey}:${wide}`} />
            <Background />
            <Controls showInteractive={false} />
            {showOverview ? (
              <MiniMap
                position="bottom-right"
                style={{ width: 110, height: 80 }}
                pannable
                zoomable
                nodeColor={(n) => roleColor((n.data as ChatNodeData).node?.role)}
              />
            ) : null}
          </ReactFlow>
        )}
      </div>
    </aside>
  );
}
