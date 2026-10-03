import { cn } from "@nova/ui";

export function PageHeader({ title, description, actions, className }: { title: string; description?: string; actions?: React.ReactNode; className?: string }) {
  return (
    <header className={cn("mb-6 flex flex-wrap items-end justify-between gap-4", className)}>
      <div>
        <h1 className="text-[28px] font-semibold tracking-tight">{title}</h1>
        {description ? <p className="mt-1 text-sm text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </header>
  );
}

export function Page({ children, className, wide = false }: { children: React.ReactNode; className?: string; wide?: boolean }) {
  return <div className={cn("mx-auto w-full px-5 py-8 md:px-8 md:py-10", wide ? "max-w-[1180px]" : "max-w-[920px]", className)}>{children}</div>;
}

export function EmptyState({ icon, title, description, action }: { icon: React.ReactNode; title: string; description?: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-[16px] border border-dashed border-border px-6 py-16 text-center">
      <div className="mb-4 text-subtle [&_svg]:size-7">{icon}</div>
      <h2 className="text-[15px] font-medium">{title}</h2>
      {description ? <p className="mt-1 max-w-sm text-sm text-muted">{description}</p> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function ErrorNotice({ title, message, actions }: { title: string; message?: string; actions?: React.ReactNode }) {
  return (
    <div className="rounded-[12px] border border-danger/25 bg-danger/[0.06] px-4 py-3">
      <div className="text-sm font-medium text-text">{title}</div>
      {message ? <div className="mt-0.5 text-[13px] text-muted">{message}</div> : null}
      {actions ? <div className="mt-2.5 flex gap-2">{actions}</div> : null}
    </div>
  );
}

export function ClassificationBadge({ level }: { level: number }) {
  if (level < 2) return null;
  const label = level >= 3 ? "C3 · Secret" : "C2 · Confidential";
  return (
    <span
      title="Contains classified context from ORBIT. Outputs inherit this classification."
      className={cn(
        "inline-flex shrink-0 items-center whitespace-nowrap rounded-md px-1.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide",
        level >= 3 ? "bg-danger/12 text-danger" : "bg-warning/12 text-warning",
      )}
    >
      {label}
    </span>
  );
}
