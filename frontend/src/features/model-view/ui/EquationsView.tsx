"use client";

import React from "react";
import type { ModelEquation } from "@/entities/model/model";
import { Badge } from "@/shared/ui/badge";
import { FileCode } from "lucide-react";

interface EquationsViewProps {
  equations: ModelEquation[];
  pythonCode?: string;
  vensimCode?: string;
}

export function EquationsView({
  equations,
  pythonCode,
  vensimCode,
}: EquationsViewProps) {
  const [showPython, setShowPython] = React.useState(false);
  const [showVensim, setShowVensim] = React.useState(false);

  if (!equations?.length && !pythonCode && !vensimCode) {
    return (
      <div className="flex items-center justify-center h-[200px] text-muted-foreground text-sm border border-border/50 rounded-lg">
        Нет уравнений для отображения
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Equations List */}
      {equations?.length > 0 && (
        <div className="border border-border/50 rounded-lg overflow-hidden">
          <div className="bg-muted/50 px-4 py-2 border-b border-border/50 flex items-center gap-2">
            <FileCode className="h-4 w-4 text-muted-foreground" />
            <span className="text-sm font-medium">Уравнения модели</span>
            <Badge variant="secondary" className="ml-auto text-xs">
              {equations.length}
            </Badge>
          </div>
          <div className="divide-y divide-border/30">
            {equations.map((eq, index) => (
              <div
                key={index}
                className="px-4 py-3 flex items-center gap-3 hover:bg-muted/20 transition-colors"
              >
                <span className="text-xs text-muted-foreground w-8 shrink-0">
                  {index + 1}
                </span>
                <code className="text-sm font-mono text-foreground">
                  <span className="text-primary font-semibold">{eq.lhs}</span>
                  <span className="text-muted-foreground mx-2">=</span>
                  <span className="text-foreground">{eq.rhs}</span>
                </code>
                {eq.description && (
                  <span className="text-xs text-muted-foreground ml-auto">
                    {eq.description}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Python Code */}
      {pythonCode && (
        <div className="border border-border/50 rounded-lg overflow-hidden">
          <button
            onClick={() => setShowPython(!showPython)}
            className="w-full bg-muted/50 px-4 py-2 border-b border-border/50 flex items-center gap-2 hover:bg-muted transition-colors text-left"
          >
            <Badge variant="default" className="bg-blue-500 text-white text-xs">
              Python
            </Badge>
            <span className="text-sm font-medium">Python код</span>
            <span className="ml-auto text-xs text-muted-foreground">
              {showPython ? "Скрыть" : "Показать"}
            </span>
          </button>
          {showPython && (
            <pre className="p-4 overflow-x-auto text-xs">
              <code className="text-foreground">{pythonCode}</code>
            </pre>
          )}
        </div>
      )}

      {/* Vensim Code */}
      {vensimCode && (
        <div className="border border-border/50 rounded-lg overflow-hidden">
          <button
            onClick={() => setShowVensim(!showVensim)}
            className="w-full bg-muted/50 px-4 py-2 border-b border-border/50 flex items-center gap-2 hover:bg-muted transition-colors text-left"
          >
            <Badge
              variant="default"
              className="bg-emerald-600 text-white text-xs"
            >
              Vensim
            </Badge>
            <span className="text-sm font-medium">Vensim код</span>
            <span className="ml-auto text-xs text-muted-foreground">
              {showVensim ? "Скрыть" : "Показать"}
            </span>
          </button>
          {showVensim && (
            <pre className="p-4 overflow-x-auto text-xs">
              <code className="text-foreground">{vensimCode}</code>
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
