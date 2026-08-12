import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type ReactFlowInstance,
} from "@xyflow/react";

import type {
  Node,
  Edge,
} from "@xyflow/react";

import { useEffect, useRef, useState } from "react";

import "@xyflow/react/dist/style.css";

const initialNodes: Node[] = [
  {
    id: "1",
    position: { x: 250, y: 100 },
    data: {
      label: "💬 Start Conversation",
    },
  },
  {
    id: "2",
    position: { x: 650, y: 300 },
    data: {
      label: "⚙️ Plan the workflow",
    },
  },
  {
    id: "3",
    position: { x: 520, y: 520 },
    data: {
      label: "📄 Generate artifact",
    },
  },
];

const initialEdges: Edge[] = [
  { id: "e1-2", source: "1", target: "2" },
  { id: "e2-3", source: "2", target: "3" },
];

export default function InfiniteCanvas() {
  const flowRef = useRef<ReactFlowInstance | null>(null);
  const [currentNodeId, setCurrentNodeId] = useState<string>("1");
  const [mapOpen, setMapOpen] = useState(false);

  const focusNode = (id: string) => {
    const instance = flowRef.current;
    if (!instance) {
      return;
    }

    const node = initialNodes.find((candidate) => candidate.id === id);
    if (!node || !node.position) {
      return;
    }

    instance.setCenter(node.position.x + 170, node.position.y + 74, {
      zoom: 1,
      duration: 0,
    });
  };

  const handleNodeClick = (_event: unknown, node: Node) => {
    setCurrentNodeId(node.id);
    focusNode(node.id);
  };

  useEffect(() => {
    focusNode(currentNodeId);
  }, [currentNodeId]);

  return (
    <div className="canvas-layout">
      <div className="canvas-frame">
        <ReactFlow
          nodes={initialNodes}
          edges={initialEdges}
          fitView
          onInit={(instance) => {
            flowRef.current = instance;
            focusNode(currentNodeId);
          }}
          onNodeClick={handleNodeClick}
          onSelectionChange={(selection) => {
            const selectedNode = selection.nodes?.[0];
            if (selectedNode?.id) {
              setCurrentNodeId(selectedNode.id);
            }
          }}
        >
          <MiniMap
            pannable
            zoomable
            position="top-right"
            className="corner-minimap"
            onClick={() => setMapOpen(true)}
            nodeColor={(node) => node.id === currentNodeId ? "#8b5cf6" : "#d8d5e4"}
            nodeClassName={(node) =>
              node.id === currentNodeId ? "selected-node-map" : ""
            }
          />
          <Controls />
          <Background />
        </ReactFlow>

        {mapOpen && (
          <div className="map-fullscreen-overlay">
            <div className="map-fullscreen-header">
              <span className="map-title">Workspace Map</span>
              <button
                className="map-close-button"
                aria-label="Close map view"
                onClick={() => setMapOpen(false)}
              >
                ×
              </button>
            </div>
            <div className="map-fullscreen-body">
              <div className="map-large-surface">
                <ReactFlow
                  nodes={initialNodes}
                  edges={initialEdges}
                  fitView
                  className="map-overlay-flow"
                  fitViewOptions={{ padding: 0.25 }}
                  nodesDraggable={false}
                  nodesConnectable={false}
                  elementsSelectable={false}
                  onNodeClick={(_event, node) => {
                    setCurrentNodeId(node.id);
                    focusNode(node.id);
                  }}
                >
                  <Background />
                  <Controls />
                </ReactFlow>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}