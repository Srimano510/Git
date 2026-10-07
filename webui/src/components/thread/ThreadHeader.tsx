import { ContextStrategyBadge } from "@/components/thread/ContextStrategyBadge";
import { Menu } from "lucide-react";
import { type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { SessionHandleLabel } from "@/components/SessionHandleLabel";
import type { SessionHandle } from "@/lib/types";

interface ThreadHeaderProps {
  title: string;
  handle?: SessionHandle | null;
  sessionKey: string;
  transport: any;
  sessionMetadata?: Record<string, any>;
  onToggleSidebar?: () => void;
  actions?: ReactNode;
}

export function ThreadHeader({
  title,
  handle,
  sessionKey,
  transport,
  sessionMetadata,
  onToggleSidebar,
  actions,
}: ThreadHeaderProps) {
  const { t } = useTranslation();

  return (
    <header className="flex h-12 w-full items-center justify-between border-b px-4 py-2 bg-background">
      {/* Left side: Sidebar Toggle & Title */}
      <div className="flex items-center gap-2 overflow-hidden">
        {onToggleSidebar && (
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={onToggleSidebar}
          >
            <Menu className="h-4 w-4" />
          </Button>
        )}
        <h1 className="truncate text-sm font-semibold">{title}</h1>
        {handle && <SessionHandleLabel handle={handle} />}
      </div>

      {/* Right side: Strategy Badge & Header Actions */}
      <div className="flex items-center gap-2">
        {/* PASTE BADGE HERE */}
        <ContextStrategyBadge
          sessionKey={sessionKey}
          transport={transport}
          currentStrategy={sessionMetadata?.context_strategy || "linear"}
        />
        {actions}
      </div>
    </header>
  );
}