import { Component, useEffect, useRef, useState, type ErrorInfo, type ReactNode } from "react";
import { useSearch } from "wouter";
import { useBackendKind } from "../data/backend";
import { errorMessage } from "../lib/errors";
import { Icon, type IconName } from "./Icon";

let hasNavigated = false;
/** Called by the router on every client-side navigation after the first render. */
export function markNavigated() {
  hasNavigated = true;
}

/** One h1 per page. After a client-side navigation, focus moves to the h1 so screen readers start there. */
export function Page({ title, lead, children }: { title: string; lead?: ReactNode; children: ReactNode }) {
  const h1 = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    document.title = `${title} - Earmark`;
    if (hasNavigated) h1.current?.focus();
  }, [title]);
  return (
    <>
      <div className="page-head">
        <h1 ref={h1} tabIndex={-1}>
          {title}
        </h1>
        {lead && <p className="lead">{lead}</p>}
      </div>
      {children}
    </>
  );
}

export function Loading({ what }: { what: string }) {
  return (
    <p className="loading" role="status">
      Loading {what}...
    </p>
  );
}

/** Current unix seconds, refreshed on an interval so "4 min ago" stays true. */
export function useNow(intervalMs = 15_000): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

/** In demo mode every link keeps ?demo=1 so the visitor never falls out of the demo. */
export function useHref(): (path: string, params?: Record<string, string>) => string {
  const kind = useBackendKind();
  useSearch();
  return (path, params) => {
    const q = new URLSearchParams(params);
    if (kind === "demo") q.set("demo", "1");
    const s = q.toString();
    return s ? `${path}?${s}` : path;
  };
}

/** A table that can scroll sideways on narrow screens; focusable so keyboard users can scroll it. */
export function TableScroll({ label, children }: { label: string; children: ReactNode }) {
  return (
    // eslint-disable-next-line jsx-a11y-x/no-noninteractive-tabindex -- scrollable regions must be keyboard reachable
    <div className="table-scroll" role="region" aria-label={label} tabIndex={0}>
      {children}
    </div>
  );
}

export type Tone ="ok" | "warn" | "bad" | "idle" | "accent";

export function StatusText({ icon, tone, children }: { icon: IconName; tone: Tone; children: ReactNode }) {
  return (
    <span className={`status status-${tone}`}>
      <Icon name={icon} size={20} />
      <span>{children}</span>
    </span>
  );
}

export function Notice({
  tone = "idle",
  icon = "info",
  title,
  children,
  role,
}: {
  tone?: Tone;
  icon?: IconName;
  title?: ReactNode;
  children?: ReactNode;
  role?: "status" | "alert" | "note";
}) {
  return (
    <div className={`notice notice-${tone}`} role={role}>
      <Icon name={icon} size={24} />
      <div className="notice-body">
        {title && <p className="notice-title">{title}</p>}
        {children}
      </div>
    </div>
  );
}

interface BoundaryState {
  error: unknown;
}

/** Shows a readable error in place of a page that failed to load, with a way to retry. */
export class ErrorBoundary extends Component<{ children: ReactNode; what: string }, BoundaryState> {
  state: BoundaryState = { error: null };
  static getDerivedStateFromError(error: unknown): BoundaryState {
    return { error };
  }
  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error(error, info.componentStack);
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="page-head">
        <h1>Could not load {this.props.what}</h1>
        <Notice tone="bad" icon="alert" role="alert" title="The Earmark server returned an error.">
          <p>{errorMessage(this.state.error)}</p>
        </Notice>
        <p>
          <button type="button" className="button" onClick={() => this.setState({ error: null })}>
            Try again
          </button>
        </p>
      </div>
    );
  }
}
