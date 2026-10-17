import { ListOrdered, Network, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export type ContextStrategy = "linear" | "graph" | "hybrid";

interface ContextStrategyBadgeProps {
  strategy?: ContextStrategy;
  onStrategyChange?: (strategy: ContextStrategy) => void;
}

export function ContextStrategyBadge({
  strategy = "linear",
  onStrategyChange,
}: ContextStrategyBadgeProps) {
  const { t } = useTranslation();
  const handleSelectStrategy = (next: ContextStrategy) => onStrategyChange?.(next);

  return (
    <DropdownMenu>
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                className={cn("h-7 gap-1.5 px-2 text-xs font-medium")}
              >
                {strategy === "hybrid" ? (
                  <Sparkles className="h-3.5 w-3.5 text-amber-500" />
                ) : strategy === "graph" ? (
                  <Network className="h-3.5 w-3.5 text-purple-500" />
                ) : (
                  <ListOrdered className="h-3.5 w-3.5 text-blue-500" />
                )}
                <span className="capitalize">{strategy}</span>
              </Button>
            </DropdownMenuTrigger>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            <p>{t("Change Context Strategy")}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => handleSelectStrategy("linear")}>
          <ListOrdered className="mr-2 h-4 w-4 text-blue-500" />
          <span>Linear (Sequential)</span>
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => handleSelectStrategy("graph")}>
          <Network className="mr-2 h-4 w-4 text-purple-500" />
          <span>Graph (DAG Pruning)</span>
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => handleSelectStrategy("hybrid")}>
          <Sparkles className="mr-2 h-4 w-4 text-amber-500" />
          <span>Hybrid (Graph + Vector)</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}