import { useSyncExternalStore } from "react";

/* Chromium's install prompt (Chrome, Edge, Android). Not in the TS DOM lib. */
interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

// The event can fire before React mounts, so capture it at module load.
let deferred: BeforeInstallPromptEvent | null = null;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());

if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (e) => {
    // No preventDefault: Chrome's own install banner stays, and our button
    // is a second way in for people who dismissed it.
    deferred = e as BeforeInstallPromptEvent;
    notify();
  });
  window.addEventListener("appinstalled", () => {
    deferred = null;
    notify();
  });
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const isStandalone = () =>
  window.matchMedia("(display-mode: standalone)").matches ||
  (navigator as Navigator & { standalone?: boolean }).standalone === true;

// iOS has no install prompt; installing is Share → Add to Home Screen. In-app
// webviews (LinkedIn, Gmail, ...) can't do that and omit the "Safari/" token.
const isIos = () =>
  (/iphone|ipad|ipod/i.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)) &&
  /Safari\//.test(navigator.userAgent);

export type InstallState =
  | { kind: "prompt"; install: () => Promise<void> }
  | { kind: "ios" }
  | { kind: "none" };

async function install() {
  const e = deferred;
  if (!e) return;
  try {
    await e.prompt();
    await e.userChoice;
  } catch {
    /* Already used or blocked: nothing to show. */
  } finally {
    // A prompt can only be shown once; Chrome fires a fresh event if it may ask again.
    deferred = null;
    notify();
  }
}

export function useInstallPrompt(): InstallState {
  const event = useSyncExternalStore(subscribe, () => deferred, () => null);
  if (event) return { kind: "prompt", install };
  if (typeof window !== "undefined" && isIos() && !isStandalone()) return { kind: "ios" };
  return { kind: "none" };
}
