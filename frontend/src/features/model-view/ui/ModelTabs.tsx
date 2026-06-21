"use client";

import React from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/shared/ui/tabs";
import type { GeneratedModel } from "@/entities/model/model";
import { CLDViewer } from "./CLDViewer";
import { SFDViewer } from "./SFDViewer";
import { EquationsView } from "./EquationsView";
import { SimulationPanel } from "@/features/simulation-run/ui/SimulationPanel";
import {
  GitBranch,
  Workflow,
  FunctionSquare,
  LineChart,
} from "lucide-react";

interface ModelTabsProps {
  model: GeneratedModel;
}

export function ModelTabs({ model }: ModelTabsProps) {
  const [activeTab, setActiveTab] = React.useState("cld");

  const hasCLD = model.cld_data?.nodes?.length > 0;
  const hasSFD = model.sfd_data?.nodes?.length > 0;
  const hasEquations = model.equations?.length > 0;

  return (
    <div className="border border-border/50 rounded-lg overflow-hidden bg-card">
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <div className="border-b border-border/50 bg-muted/30 px-2">
          <TabsList className="bg-transparent h-10">
            <TabsTrigger
              value="cld"
              disabled={!hasCLD}
              className="text-xs gap-1.5 data-[state=active]:bg-background"
            >
              <GitBranch className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">CLD</span>
              <span className="sm:hidden">CLD</span>
            </TabsTrigger>
            <TabsTrigger
              value="sfd"
              disabled={!hasSFD}
              className="text-xs gap-1.5 data-[state=active]:bg-background"
            >
              <Workflow className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">SFD</span>
              <span className="sm:hidden">SFD</span>
            </TabsTrigger>
            <TabsTrigger
              value="equations"
              disabled={!hasEquations}
              className="text-xs gap-1.5 data-[state=active]:bg-background"
            >
              <FunctionSquare className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Уравнения</span>
              <span className="sm:hidden">Eq</span>
            </TabsTrigger>
            <TabsTrigger
              value="simulation"
              className="text-xs gap-1.5 data-[state=active]:bg-background"
            >
              <LineChart className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Симуляция</span>
              <span className="sm:hidden">Sim</span>
            </TabsTrigger>
          </TabsList>
        </div>

        <div className="p-4">
          <TabsContent value="cld" className="mt-0">
            {hasCLD ? (
              <CLDViewer cldData={model.cld_data} />
            ) : (
              <EmptyTab message="Нет данных CLD диаграммы" />
            )}
          </TabsContent>

          <TabsContent value="sfd" className="mt-0">
            {hasSFD ? (
              <SFDViewer sfdData={model.sfd_data} />
            ) : (
              <EmptyTab message="Нет данных SFD диаграммы" />
            )}
          </TabsContent>

          <TabsContent value="equations" className="mt-0">
            {hasEquations ? (
              <EquationsView
                equations={model.equations}
                pythonCode={model.python_code}
                vensimCode={model.vensim_code}
              />
            ) : (
              <EmptyTab message="Нет уравнений" />
            )}
          </TabsContent>

          <TabsContent value="simulation" className="mt-0">
            <SimulationPanel model={model} />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}

function EmptyTab({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center h-[200px] text-muted-foreground text-sm">
      {message}
    </div>
  );
}
