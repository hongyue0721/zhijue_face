import { useEffect, useRef, useState } from "react";
import { api, type OperationView } from "../api";

const TERMINAL_STATUSES: Record<OperationView["status"], boolean> = {
  queued: false,
  running: false,
  succeeded: true,
  failed: true,
  interrupted: true,
  canceled: true,
};
const EVENT_NAMES = [
  "operation.started",
  "operation.progress",
  "operation.completed",
  "operation.failed",
  "operation.interrupted",
];

export function isTerminalOperation(operation: OperationView): boolean {
  return TERMINAL_STATUSES[operation.status];
}

export function useOperationMonitor(
  operationId: string | null,
  onTerminal: (operation: OperationView) => void,
) {
  const [operation, setOperation] = useState<OperationView | null>(null);
  const [error, setError] = useState<unknown>(null);
  const onTerminalRef = useRef(onTerminal);
  onTerminalRef.current = onTerminal;

  useEffect(() => {
    setOperation(null);
    setError(null);
    if (!operationId) return;

    const controller = new AbortController();
    let source: EventSource | null = null;
    let stopped = false;
    let terminalDelivered = false;

    const refresh = async () => {
      try {
        const next = await api.getOperation(operationId, controller.signal);
        if (stopped) return;
        setOperation(next);
        setError(null);
        if (isTerminalOperation(next) && !terminalDelivered) {
          terminalDelivered = true;
          source?.close();
          onTerminalRef.current(next);
        }
      } catch (nextError) {
        if (!stopped && !(nextError instanceof DOMException && nextError.name === "AbortError")) {
          setError(nextError);
        }
      }
    };

    source = new EventSource(api.eventsUrl(operationId));
    for (const eventName of EVENT_NAMES) source.addEventListener(eventName, refresh);
    source.onerror = () => void refresh();
    const timer = window.setInterval(refresh, 800);
    void refresh();

    return () => {
      stopped = true;
      controller.abort();
      window.clearInterval(timer);
      source?.close();
    };
  }, [operationId]);

  return { operation, error };
}
