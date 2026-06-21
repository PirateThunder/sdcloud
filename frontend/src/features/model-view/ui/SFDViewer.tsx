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
import type { SFDData } from "@/entities/model/model";
import { Handle, Position } from "@xyflow/react";

// SFD uses different visual styles - stocks are rectangles, flows are valves
function SFDStockNode({ data }: NodeProps) {
  return (
    <div className="px-4 py-3 rounded-md border-2 border-emerald-700 bg-emerald-50 text-emerald-900 font-bold text-sm min-w-[130px] max-w-[220px] text-center shadow-md whitespace-normal leading-tight">
      <Handle type="target" position={Position.Left} className="!bg-emerald-700" style={{ width: 8, height: 8 }} />
      {data.label as string}
      <Handle type="source" position={Position.Right} className="!bg-emerald-700" style={{ width: 8, height: 8 }} />
    </div>
  );
}

function SFDFlowNode({ data }: NodeProps) {
  return (
    <div className="flex flex-col items-center gap-1 min-w-[100px]">
      <div className="w-7 h-7 rotate-45 border-2 border-blue-700 bg-blue-50 flex items-center justify-center shadow-sm">
        <div className="w-2 h-2 bg-blue-700 rounded-full" />
      </div>
      <span className="text-blue-900 font-bold text-xs text-center whitespace-normal leading-tight max-w-[140px]">{data.label as string}</span>
      <Handle type="target" position={Position.Top} className="!bg-blue-700" />
      <Handle type="source" position={Position.Bottom} className="!bg-blue-700" />
    </div>
  );
}

function SFDAuxiliaryNode({ data }: NodeProps) {
  return (
    <div className="px-4 py-2 rounded-full border border-dashed border-amber-700 bg-amber-50 text-amber-900 font-bold text-xs min-w-[100px] max-w-[180px] text-center whitespace-normal leading-tight">
      <Handle type="target" position={Position.Top} className="!bg-amber-700" />
      {data.label as string}
      <Handle type="source" position={Position.Bottom} className="!bg-amber-700" />
    </div>
  );
}

function SFDDefaultNode({ data }: NodeProps) {
  return (
    <div className="px-4 py-2 rounded border border-gray-500 bg-white text-gray-900 font-bold text-xs min-w-[100px] max-w-[180px] text-center whitespace-normal leading-tight">
      <Handle type="target" position={Position.Top} className="!bg-gray-600" />
      {data.label as string}
      <Handle type="source" position={Position.Bottom} className="!bg-gray-600" />
    </div>
  );
}

const nodeTypes = {
  stock: SFDStockNode,
  flow: SFDFlowNode,
  auxiliary: SFDAuxiliaryNode,
  default: SFDDefaultNode,
};

interface SFDViewerProps {
  sfdData: SFDData;
}

export function SFDViewer({ sfdData }: SFDViewerProps) {
  const nodes: Node[] = useMemo(() => {
    if (!sfdData?.nodes?.length) return [];

    const nodeCount = sfdData.nodes.length;
    const radius = Math.max(250, nodeCount * 70);
    const centerX = 400;
    const centerY = 300;

    return sfdData.nodes.map((node, index) => {
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
  }, [sfdData?.nodes]);

  const edges: Edge[] = useMemo(() => {
    if (!sfdData?.edges?.length) return [];

    return sfdData.edges.map((edge, index) => ({
      id: `sfd-e-${index}`,
      source: edge.source,
      target: edge.target,
      type: "smoothstep",
      animated: true,
      style: {
        stroke: "hsl(217, 91%, 60%)",
        strokeWidth: 2,
      },
      markerEnd: {
        type: "arrowclosed" as const,
        color: "hsl(217, 91%, 60%)",
      },
    }));
  }, [sfdData?.edges]);

  if (!sfdData?.nodes?.length) {
    return (
      <div className="flex items-center justify-center h-[400px] text-muted-foreground text-sm border border-border/50 rounded-lg">
        Нет данных для SFD диаграммы
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
