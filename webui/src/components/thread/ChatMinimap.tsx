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
import { Link2, Map as MapIcon, Maximize2, Minimize2, Workflow, X } from "lucide-react";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { fetchSessionGraph } from "@/lib/api";
import {
  ancestorIds,
  collapseRuns,
  layoutTree,
  MESSAGE_SIZE,
  RUN_SIZE,
  type TreeNode,
  type TreePayload,
  type WorkflowNode,
  WORKFLOW_SIZE,
  withWorkflow,
} from "@/lib/chat-tree";
import { cn } from "@/lib/utils";

interface ChatNodeData extends Record<string, unknown> {
  node?: TreeNode;
  workflow?: WorkflowNode;
  count?: number;
  active: boolean;
  selected: boolean;
  kind?: "history" | "vector" | "summary";
  /** A folded run whose messages were part of the last turn's context. */
  inContext?: boolean;
  /** Link mode only: can this message be linked into the open chat? */
  linkable?: boolean;
}

const KIND_COLOR = { vector: "#f59e0b", summary: "#14b8a6" } as const;
const WORKFLOW_COLOR = "#8b5cf6";

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
  const { t } = useTranslation();
  const zoom = useStore((s) => s.transform[2]);
  const { node, count, active, selected, kind, inContext, linkable } = data;
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
        {t("thread.chatTree.folded", { count })}
        {inContext ? ` · ${t("thread.chatTree.inContext")}` : ""}
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
          opacity: linkable === false ? 0.25 : active ? 1 : 0.55,
          ...(flagged ? { outline: `4px solid ${KIND_COLOR[flagged]}` } : {}),
        }}
        className={cn("rounded-md", ring, linkable && "cursor-pointer ring-2 ring-sky-500")}
      >
        {handles}
      </div>
    );
  }
  return (
    <div
      data-testid="minimap-node"
      data-linkable={linkable === undefined ? undefined : String(linkable)}
      style={MESSAGE_SIZE}
      className={cn(
        "overflow-hidden rounded-md border bg-card px-2 py-1 text-left text-[11px] leading-snug",
        active ? "" : "opacity-70",
        ring,
        linkable === false && "cursor-not-allowed opacity-30",
        linkable && "cursor-pointer ring-2 ring-sky-500",
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
            {t(flagged === "vector" ? "thread.chatTree.kindVector" : "thread.chatTree.kindSummary")}
          </span>
        ) : kind === "history" ? (
          <span data-testid="minimap-kind-history" className="ml-auto text-[9px] text-muted-foreground">
            {t("thread.chatTree.inContext")}
          </span>
        ) : null}
      </div>
      <div className={zoom < 0.6 ? "truncate" : "line-clamp-2"}>{node.preview}</div>
    </div>
  );
});

/** One step of the last turn's context workflow (not a chat message). */
const WorkflowNodeView = memo(function WorkflowNodeView({ data }: NodeProps<Node<ChatNodeData>>) {
  const w = data.workflow!;
  return (
    <div
      data-testid="minimap-workflow"
      style={{ ...WORKFLOW_SIZE, borderColor: WORKFLOW_COLOR }}
      className="overflow-hidden rounded-md border-2 bg-card px-2 py-1 text-left text-[11px] leading-snug"
    >
      {handles}
      <div className="flex items-center gap-1 font-medium" style={{ color: WORKFLOW_COLOR }}>
        <span className="truncate">{w.label}</span>
        {w.ms !== undefined ? (
          <span className="ml-auto shrink-0 text-muted-foreground">{w.ms} ms</span>
        ) : null}
      </div>
      <div className="truncate text-muted-foreground">{w.detail}</div>
    </div>
  );
});

const nodeTypes = { chat: ChatNodeView, workflow: WorkflowNodeView };

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
  /** Sends `/context link` for a node of another branch; enables the panel's link mode. */
  onLink?: (node: TreeNode) => Promise<void>;
  onClose: () => void;
}

export function ChatMinimap({
  token,
  sessionKey,
  refreshKey = 0,
  selectedNodeId = null,
  theme = "light",
  onSelectNode,
  onLink,
  onClose,
}: ChatMinimapProps) {
  const { t } = useTranslation();
  const [payload, setPayload] = useState<TreePayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const [wide, setWide] = useState(false);
  const [showOverview, setShowOverview] = useState(false);
  const [showWorkflow, setShowWorkflow] = useState(false);
  const [linkMode, setLinkMode] = useState(false);
  const [linkStatus, setLinkStatus] = useState<"ok" | "failed" | null>(null);
  const [refetchNonce, setRefetchNonce] = useState(0);
  const awaitingLink = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchSessionGraph(token, sessionKey)
      .then((p) => {
        if (cancelled) return;
        setPayload(p);
        setError(null);
        // After a link command, the refetched tree tells whether the link really exists.
        const linked = awaitingLink.current;
        if (linked) {
          awaitingLink.current = null;
          setLinkStatus(p.edges.some((e) => e.type === "CONTEXT" && e.source === linked) ? "ok" : "failed");
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [token, sessionKey, refreshKey, refetchNonce]);

  // Messages of the open chat's own history cannot be linked into it.
  const activeIds = useMemo(
    () => (payload ? ancestorIds(payload.edges, payload.tips[sessionKey]) : new Set<string>()),
    [payload, sessionKey],
  );

  const startLink = (node: TreeNode) => {
    setLinkMode(false);
    setLinkStatus(null);
    onLink?.(node).then(
      () => {
        awaitingLink.current = node.id;
        setRefetchNonce((n) => n + 1); // cancels fetches that started before the command finished
      },
      () => setLinkStatus("failed"),
    );
  };

  const { nodes, edges, focus } = useMemo(() => {
    if (!payload) {
      return { nodes: [] as Node<ChatNodeData>[], edges: [] as Edge[], focus: [] as { id: string }[] };
    }
    // Recalled nodes must stay visible, so they are never folded into a "+N messages" run.
    const keep = new Set(selectedNodeId ? [selectedNodeId] : []);
    for (const [id, kind] of Object.entries(payload.context ?? {})) {
      if (kind !== "history") keep.add(id);
    }
    const workflow = showWorkflow ? payload.workflow : undefined;
    if (workflow) keep.add(workflow.anchor);
    const base = collapseRuns(payload, keep, expanded);
    const folded = workflow ? withWorkflow(base, workflow) : base;
    const active = ancestorIds(payload.edges, payload.tips[sessionKey]);
    const flowNodes = layoutTree(folded.nodes, folded.edges).map<Node<ChatNodeData>>((n) => ({
      id: n.id,
      type: n.kind === "workflow" ? "workflow" : "chat",
      position: { x: n.x, y: n.y },
      draggable: false,
      ...(n.kind === "run" ? RUN_SIZE : n.kind === "workflow" ? WORKFLOW_SIZE : MESSAGE_SIZE),
      data: {
        node: n.node,
        workflow: n.workflow,
        count: n.count,
        active: n.members ? n.members.some((id) => active.has(id)) : active.has(n.id),
        selected: n.id === selectedNodeId,
        kind: payload.context?.[n.id],
        inContext: n.members?.some((m) => payload.context?.[m] === "history"),
        linkable: linkMode && n.node ? !activeIds.has(n.node.id) : undefined,
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
        ...(e.type === "CONTEXT" ? { strokeDasharray: "2 4", stroke: "#0ea5e9" } : {}),
        ...(e.type === "TRIGGERS" || e.type === "FEEDS" ? { stroke: WORKFLOW_COLOR } : {}),
      },
    }));
    // Start on the end of the active path at a readable zoom; the overview map shows the rest.
    const focusNodes = flowNodes
      .filter((n) => n.data.active)
      .sort((a, b) => b.position.y - a.position.y)
      .slice(0, 6)
      .map((n) => ({ id: n.id }));
    if (workflow) focusNodes.push(...workflow.nodes.map((w) => ({ id: w.id })));
    if (linkMode) focusNodes.push(...flowNodes.filter((n) => n.data.linkable).map((n) => ({ id: n.id })));
    return { nodes: flowNodes, edges: flowEdges, focus: focusNodes };
  }, [payload, expanded, selectedNodeId, sessionKey, showWorkflow, linkMode, activeIds]);

  return (
    <aside
      aria-label={t("thread.chatTree.title")}
      className={cn(
        "flex shrink-0 flex-col border-l bg-background max-md:absolute max-md:inset-y-0 max-md:right-0 max-md:z-20 max-md:shadow-xl",
        wide ? "w-[55%] min-w-[360px]" : "w-[360px] max-w-[90vw]",
      )}
    >
      <header className="flex items-center justify-between border-b px-3 py-2 text-sm font-medium">
        {t("thread.chatTree.title")}
        <span className="flex gap-1">
          <button
            type="button"
            aria-label={t(showOverview ? "thread.chatTree.hideOverview" : "thread.chatTree.showOverview")}
            aria-pressed={showOverview}
            onClick={() => setShowOverview((v) => !v)}
          >
            <MapIcon size={14} />
          </button>
          {onLink ? (
            <button
              type="button"
              aria-label={t(linkMode ? "thread.chatTree.cancelLink" : "thread.chatTree.link")}
              aria-pressed={linkMode}
              onClick={() => {
                setLinkMode((v) => !v);
                setLinkStatus(null);
              }}
            >
              <Link2 size={14} />
            </button>
          ) : null}
          {payload?.workflow ? (
            <button
              type="button"
              aria-label={t(showWorkflow ? "thread.chatTree.hideWorkflow" : "thread.chatTree.showWorkflow")}
              aria-pressed={showWorkflow}
              onClick={() => setShowWorkflow((v) => !v)}
            >
              <Workflow size={14} />
            </button>
          ) : null}
          <button
            type="button"
            aria-label={t(wide ? "thread.chatTree.shrink" : "thread.chatTree.expand")}
            onClick={() => setWide((w) => !w)}
          >
            {wide ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
          <button type="button" aria-label={t("thread.chatTree.close")} onClick={onClose}>
            <X size={14} />
          </button>
        </span>
      </header>
      {linkMode ? (
        <p className="border-b bg-sky-500/10 px-3 py-1 text-[11px]">{t("thread.chatTree.linkHint")}</p>
      ) : null}
      {linkStatus === "ok" ? (
        <p role="status" className="border-b bg-emerald-500/10 px-3 py-1 text-[11px]">
          {t("thread.chatTree.linked")}
        </p>
      ) : null}
      {linkStatus === "failed" ? (
        <p role="alert" className="border-b bg-red-500/10 px-3 py-1 text-[11px] text-red-600 dark:text-red-400">
          {t("thread.chatTree.linkFailed")}
        </p>
      ) : null}
      {payload?.context ? (
        <p data-testid="minimap-legend" className="border-b px-3 py-1 text-[11px] text-muted-foreground">
          {t("thread.chatTree.lastTurn", { strategy: payload.context_strategy ?? "graph" })}{" "}
          <span style={{ color: KIND_COLOR.vector }}>{t("thread.chatTree.kindVector")}</span>{" · "}
          <span style={{ color: KIND_COLOR.summary }}>{t("thread.chatTree.kindSummary")}</span>
          {` · ${t("thread.chatTree.inContext")}`}
          {showWorkflow && payload.workflow ? (
            <>
              {" · "}
              <span style={{ color: WORKFLOW_COLOR }}>{t("thread.chatTree.workflowStep")}</span>
            </>
          ) : null}
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
              if (data.workflow) return;
              if (linkMode && data.node) {
                if (!activeIds.has(data.node.id)) startLink(data.node);
                return;
              }
              if (data.node) {
                onSelectNode(data.node, Object.values(payload?.tips ?? {}).includes(data.node.id));
              }
              else setExpanded((prev) => new Set(prev).add(n.id));
            }}
          >
            <FocusOnLoad focus={focus} chatKey={`${sessionKey}:${wide}:${showWorkflow}:${linkMode}`} />
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
