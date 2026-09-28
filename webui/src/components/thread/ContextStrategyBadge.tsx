import { useState } from "react";
import { ListOrdered, Network } from "lucide-react";
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

export type ContextStrategy = "linear" | "graph";

interface ContextStrategyBadgeProps {
  strategy: ContextStrategy;
  onStrategyChange?: (strategy: ContextStrategy) => void;
  disabled?: boolean;
  isHero?: boolean;
}

export function ContextStrategyBadge({
  strategy = "linear",
  onStrategyChange,
  disabled = false,
  isHero = false,
}: ContextStrategyBadgeProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  const isGraph = strategy === "graph";
  const label = isGraph
    ? t("thread.contextStrategy.graph", { defaultValue: "Graph" })
    : t("thread.contextStrategy.linear", { defaultValue: "Linear" });

  const Icon = isGraph ? Network : ListOrdered;

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <TooltipProvider delayDuration={400}>
        <Tooltip>
          <TooltipTrigger asChild>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={disabled}
                data-testid="context-strategy-badge"
                className={cn(
                  "h-7 gap-1.5 rounded-full px-2.5 text-xs font-medium transition-all select-none",
                  isGraph
                    ? "bg-purple-500/10 text-purple-600 hover:bg-purple-500/20 dark:bg-purple-400/15 dark:text-purple-300"
                    : "bg-accent/40 text-muted-foreground hover:bg-accent/70 hover:text-foreground",
                  isHero && "h-8 px-3 text-xs",
                )}
              >
                <Icon className={cn("h-3.5 w-3.5", isGraph ? "text-purple-500" : "text-muted-foreground")} />
                <span>{label}</span>
              </Button>
            </DropdownMenuTrigger>
          </TooltipTrigger>
          {!open ? (
            <TooltipContent side="top" className="text-xs">
              {t("thread.contextStrategy.tooltip", {
                defaultValue: "Context Strategy: Switch between Linear history and Conversation Graph context",
              })}
            </TooltipContent>
          ) : null}
        </Tooltip>
      </TooltipProvider>

      <DropdownMenuContent align="end" className="w-56 p-1.5">
        <div className="px-2 py-1 text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
          {t("thread.contextStrategy.title", { defaultValue: "Context Strategy" })}
        </div>
        <DropdownMenuItem
          onClick={() => {
            onStrategyChange?.("linear");
            setOpen(false);
          }}
          className={cn(
            "flex cursor-pointer items-center justify-between rounded-md px-2 py-1.5 text-xs transition-colors",
            !isGraph && "bg-accent font-medium text-accent-foreground",
          )}
        >
          <div className="flex items-center gap-2">
            <ListOrdered className="h-4 w-4 text-muted-foreground" />
            <div>
              <div className="font-medium">{t("thread.contextStrategy.linear", { defaultValue: "Linear" })}</div>
              <div className="text-[10px] text-muted-foreground">
                {t("thread.contextStrategy.linearDesc", { defaultValue: "Recent chronological history window" })}
              </div>
            </div>
          </div>
          {!isGraph && <span className="text-primary text-xs">✓</span>}
        </DropdownMenuItem>

        <DropdownMenuItem
          onClick={() => {
            onStrategyChange?.("graph");
            setOpen(false);
          }}
          className={cn(
            "flex cursor-pointer items-center justify-between rounded-md px-2 py-1.5 text-xs transition-colors mt-1",
            isGraph && "bg-purple-500/15 font-medium text-purple-700 dark:text-purple-300",
          )}
        >
          <div className="flex items-center gap-2">
            <Network className="h-4 w-4 text-purple-500" />
            <div>
              <div className="font-medium">{t("thread.contextStrategy.graph", { defaultValue: "Graph" })}</div>
              <div className="text-[10px] text-muted-foreground">
                {t("thread.contextStrategy.graphDesc", { defaultValue: "Relational conversation graph context" })}
              </div>
            </div>
          </div>
          {isGraph && <span className="text-purple-600 dark:text-purple-400 text-xs">✓</span>}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
