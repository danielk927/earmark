import { Link } from "wouter";
import type { AppMode } from "../config";
import { Notice, Page, useHref } from "../components/common";

export function NotConnectedPage({ mode }: { mode: Extract<AppMode, { kind: "unconfigured" }> }) {
  return (
    <Page title="Not connected" lead="This dashboard doesn't know which Earmark server to read from, so it can't show anything yet.">
      <Notice tone="warn" icon="offline" title={mode.reason === "invalid" ? "The server address is not a valid URL." : "No server address was set when this dashboard was built."}>
        {mode.reason === "invalid" ? (
          <p>
            It was built with <code>VITE_CONVEX_URL</code> set to <code>{mode.url}</code>. Rebuild it with the deployment
            URL, for example <code>https://your-deployment.convex.cloud</code>.
          </p>
        ) : (
          <p>
            Rebuild it with <code>VITE_CONVEX_URL</code> set to the Convex deployment URL, for example{" "}
            <code>https://your-deployment.convex.cloud</code>.
          </p>
        )}
      </Notice>
      <p>
        <a className="button primary" href="?demo=1">
          See the dashboard with demo data
        </a>
      </p>
    </Page>
  );
}

export function NotFoundPage() {
  const href = useHref();
  return (
    <Page title="Page not found" lead="There is no page at this address.">
      <p>
        <Link href={href("/")}>Go to the live map</Link>
      </p>
    </Page>
  );
}
