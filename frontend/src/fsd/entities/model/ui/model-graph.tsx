'use client'

import {
  Background,
  Controls,
  type Edge,
  MarkerType,
  MiniMap,
  type Node,
  ReactFlow,
} from '@xyflow/react'
import { useMemo } from 'react'

import type { ModelGraph } from '../model/types'

const kindColors: Record<string, string> = {
  stock: '#1684a7',
  flow: '#0f766e',
  auxiliary: '#a36b13',
  constant: '#68766f',
  cloud: '#89958f',
  variable: '#68766f',
}

function layout(graph: ModelGraph, mode: 'cld' | 'sfd'): Node[] {
  if (mode === 'cld') {
    const count = graph.nodes.length
    const radiusX = Math.max(230, count * 42)
    const radiusY = Math.max(150, count * 24)
    return graph.nodes.map((node, index) => {
      const angle = (index / Math.max(count, 1)) * Math.PI * 2 - Math.PI / 2
      return {
        id: node.id,
        position: { x: Math.cos(angle) * radiusX, y: Math.sin(angle) * radiusY },
        data: { label: node.label },
      }
    })
  }
  const columns = ['stock', 'flow', 'auxiliary', 'constant', 'cloud', 'variable']
  return graph.nodes.map((node) => {
    const column = Math.max(0, columns.indexOf(node.type))
    const siblings = graph.nodes.filter((candidate) => candidate.type === node.type)
    const row = siblings.findIndex((candidate) => candidate.id === node.id)
    return {
      id: node.id,
      position: { x: column * 240, y: row * 105 },
      data: { label: node.label },
    }
  })
}

export function ModelGraphView({ graph, mode }: { graph: ModelGraph; mode: 'cld' | 'sfd' }) {
  const nodes = useMemo<Node[]>(
    () =>
      layout(graph, mode).map((node) => {
        const source = graph.nodes.find((candidate) => candidate.id === node.id)
        const color = kindColors[source?.type ?? 'variable'] ?? kindColors.variable
        return {
          ...node,
          style: {
            width: 176,
            padding: 12,
            border: `1px solid ${color}`,
            borderLeft: `4px solid ${color}`,
            borderRadius: 12,
            background: 'var(--card)',
            color: 'var(--foreground)',
            fontSize: 12,
            lineHeight: 1.4,
            boxShadow: '0 2px 8px rgb(0 0 0 / 4%)',
          },
        }
      }),
    [graph, mode],
  )
  const edges = useMemo<Edge[]>(
    () =>
      graph.edges.map((edge, index) => ({
        id: `${edge.source}-${edge.target}-${index}`,
        source: edge.source,
        target: edge.target,
        label: mode === 'cld' ? edge.polarity : edge.label,
        type: 'smoothstep',
        animated: false,
        style: { stroke: edge.polarity === '-' ? '#b63b35' : '#0f766e', strokeWidth: 1.5 },
        labelStyle: { fill: 'var(--foreground)', fontSize: 11 },
        labelBgStyle: { fill: 'var(--card)' },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: edge.polarity === '-' ? '#b63b35' : '#0f766e',
        },
      })),
    [graph.edges, mode],
  )

  return (
    <div
      role="application"
      className="h-[540px] overflow-hidden rounded-xl border border-border"
      aria-label={mode === 'cld' ? 'CLD диаграмма' : 'SFD диаграмма'}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        fitViewOptions={{ padding: 0.16, maxZoom: 1.1 }}
        minZoom={0.2}
        maxZoom={1.8}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        panOnDrag
        zoomOnScroll
        preventScrolling={false}
      >
        <Background gap={24} size={1} color="var(--border)" />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable className="hidden sm:block" />
      </ReactFlow>
    </div>
  )
}
