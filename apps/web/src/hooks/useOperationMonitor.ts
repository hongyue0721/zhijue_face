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

export function preferObservedOperation(
  current: OperationView | null,
  next: OperationView,
): OperationView {
  return current && isTerminalOperation(current) ? current : next;
}

export function stopOperationTransport(
  timer: number | null,
  source: Pick<EventSource, "close"> | null,
  controller: Pick<AbortController, "abort">,
): null {
  if (timer !== null) window.clearInterval(timer);
  source?.close();
  controller.abort();
  return null;
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
    let timer: number | null = null;
    let disposed = false;
    let terminalSnapshot: OperationView | null = null;

    const stopTransport = () => {
      timer = stopOperationTransport(timer, source, controller);
    };

    const refresh = async () => {
      if (disposed || terminalSnapshot) return;
      try {
        const next = await api.getOperation(operationId, controller.signal);
        if (disposed || terminalSnapshot) return;
        setError(null);
        setOperation((current) => preferObservedOperation(current, next));
        if (isTerminalOperation(next)) {
          terminalSnapshot = next;
          stopTransport();
          onTerminalRef.current(next);
        }
      } catch (nextError) {
        if (
          !disposed
          && !terminalSnapshot
          && !(nextError instanceof DOMException && nextError.name === "AbortError")
        ) {
          setError(nextError);
        }
      }
    };

    source = new EventSource(api.eventsUrl(operationId));
    for (const eventName of EVENT_NAMES) source.addEventListener(eventName, refresh);
    source.onerror = () => void refresh();
    timer = window.setInterval(refresh, 800);
    void refresh();

    return () => {
      disposed = true;
      stopTransport();
    };
  }, [operationId]);

  return { operation, error };
}
