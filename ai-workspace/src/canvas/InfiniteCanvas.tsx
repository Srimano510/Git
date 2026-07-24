import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
} from "@xyflow/react";

import type {
  Node,
  Edge,
} from "@xyflow/react";

import "@xyflow/react/dist/style.css";

const initialNodes: Node[] = [
  {
    id: "1",
    position: { x: 250, y: 100 },
    data: {
      label: "💬 Start Conversation",
    },
  },
];

const initialEdges: Edge[] = [];

export default function InfiniteCanvas() {
  return (
    <div style={{ width: "100%", height: "100%" }}>
      <ReactFlow
        nodes={initialNodes}
        edges={initialEdges}
        fitView
      >
        <MiniMap />
        <Controls />
        <Background />
      </ReactFlow>
    </div>
  );
}