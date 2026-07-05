declare const __APP_BUILD_ID__: string;

const CHECK_INTERVAL_MS = 2 * 60 * 1000;

async function fetchRemoteBuildId(): Promise<string | null> {
  try {
    const res = await fetch(`/version.json?_=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) return null;
    const data = (await res.json()) as { buildId?: string };
    return data.buildId ?? null;
  } catch {
    return null;
  }
}

async function reloadIfStale(): Promise<void> {
  const remote = await fetchRemoteBuildId();
  if (remote && remote !== __APP_BUILD_ID__) {
    window.location.reload();
  }
}

/** Prod: auto-reload when a new docker build is deployed (tab focus or periodic check). */
export function startAppVersionWatch(): void {
  if (import.meta.env.DEV) return;

  const onVisible = () => {
    if (document.visibilityState === "visible") {
      void reloadIfStale();
    }
  };

  document.addEventListener("visibilitychange", onVisible);
  window.setInterval(() => {
    if (document.visibilityState === "visible") {
      void reloadIfStale();
    }
  }, CHECK_INTERVAL_MS);
}