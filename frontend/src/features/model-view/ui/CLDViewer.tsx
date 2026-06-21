"use client";

import React, { useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { CLDData } from "@/entities/model/model";
import { Handle, Position } from "@xyflow/react";

// Custom node components for CLD
function StockNode({ data }: NodeProps) {
  return (
    <div className="px-4 py-2 rounded-lg border-2 border-emerald-700 bg-emerald-50 text-emerald-900 font-bold text-sm min-w-[110px] max-w-[200px] text-center shadow-sm whitespace-normal leading-tight">
      <Handle type="target" position={Position.Top} className="!bg-emerald-700" />
      {data.label as string}
      <Handle type="source" position={Position.Bottom} className="!bg-emerald-700" />
    </div>
  );
}

function FlowNode({ data }: NodeProps) {
  return (
    <div className="px-4 py-2 rounded-full border-2 border-blue-700 bg-blue-50 text-blue-900 font-bold text-sm min-w-[110px] max-w-[200px] text-center shadow-sm whitespace-normal leading-tight">
      <Handle type="target" position={Position.Top} className="!bg-blue-700" />
      {data.label as string}
      <Handle type="source" position={Position.Bottom} className="!bg-blue-700" />
    </div>
  );
}

function AuxiliaryNode({ data }: NodeProps) {
  return (
    <div className="px-4 py-2 rounded-md border-2 border-amber-700 bg-amber-50 text-amber-900 font-bold text-sm min-w-[110px] max-w-[200px] text-center shadow-sm whitespace-normal leading-tight">
      <Handle type="target" position={Position.Top} className="!bg-amber-700" />
      {data.label as string}
      <Handle type="source" position={Position.Bottom} className="!bg-amber-700" />
    </div>
  );
}

function DefaultNode({ data }: NodeProps) {
  return (
    <div className="px-4 py-2 rounded-md border border-gray-500 bg-white text-gray-900 font-bold text-sm min-w-[110px] max-w-[200px] text-center shadow-sm whitespace-normal leading-tight">
      <Handle type="target" position={Position.Top} className="!bg-gray-600" />
      {data.label as string}
      <Handle type="source" position={Position.Bottom} className="!bg-gray-600" />
    </div>
  );
}

const nodeTypes = {
  stock: StockNode,
  flow: FlowNode,
  auxiliary: AuxiliaryNode,
  default: DefaultNode,
};

interface CLDViewerProps {
  cldData: CLDData;
}

export function CLDViewer({ cldData }: CLDViewerProps) {
  const nodes: Node[] = useMemo(() => {
    if (!cldData?.nodes?.length) return [];

    // Calculate positions using simple circular layout
    const nodeCount = cldData.nodes.length;
    const radius = Math.max(200, nodeCount * 60);
    const centerX = 400;
    const centerY = 300;

    return cldData.nodes.map((node, index) => {
      const angle = (2 * Math.PI * index) / nodeCount - Math.PI / 2;
      const x = centerX + radius * Math.cos(angle) * 0.8;
      const y = centerY + radius * Math.sin(angle) * 0.6;

      return {
        id: node.id,
        type: node.type || "default",
        position: { x, y },
        data: { label: node.label },
      };
    });
  }, [cldData?.nodes]);

  const edges: Edge[] = useMemo(() => {
    if (!cldData?.edges?.length) return [];

    return cldData.edges.map((edge, index) => ({
      id: `e-${index}`,
      source: edge.source,
      target: edge.target,
      label: edge.polarity || "+",
      type: "smoothstep",
      animated: false,
      style: {
        stroke:
          edge.polarity === "+"
            ? "hsl(142, 76%, 36%)"
            : edge.polarity === "-"
            ? "hsl(0, 84%, 60%)"
            : "hsl(240, 5%, 65%)",
        strokeWidth: 2,
      },
      labelStyle: {
        fill:
          edge.polarity === "+"
            ? "hsl(142, 76%, 28%)"
            : edge.polarity === "-"
            ? "hsl(0, 84%, 40%)"
            : "hsl(240, 5%, 40%)",
        fontSize: 14,
        fontWeight: 700,
      },
      labelBgStyle: { fill: "rgba(255, 255, 255, 0.95)" },
      labelBgPadding: [6, 4],
      labelShowBg: true,
      markerEnd: {
        type: "arrowclosed" as const,
        color:
          edge.polarity === "+"
            ? "hsl(142, 76%, 36%)"
            : edge.polarity === "-"
            ? "hsl(0, 84%, 60%)"
            : "hsl(240, 5%, 65%)",
      },
    }));
  }, [cldData?.edges]);

  if (!cldData?.nodes?.length) {
    return (
      <div className="flex items-center justify-center h-[400px] text-muted-foreground text-sm border border-border/50 rounded-lg">
        Нет данных для CLD диаграммы
      </div>
    );
  }

  return (
    <div className="h-[500px] border border-border/50 rounded-lg overflow-hidden bg-gray-50">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        attributionPosition="bottom-left"
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={16} size={1} color="hsl(240, 5%, 70%)" />
        <Controls />
        <MiniMap
          nodeColor={(node) => {
            switch (node.type) {
              case "stock":
                return "hsl(142, 76%, 36%)";
              case "flow":
                return "hsl(217, 91%, 60%)";
              case "auxiliary":
                return "hsl(38, 92%, 50%)";
              default:
                return "hsl(240, 5%, 50%)";
            }
          }}
          maskColor="hsl(240, 10%, 90%, 0.8)"
          className="!bg-gray-50/80"
        />
      </ReactFlow>
    </div>
  );
}
