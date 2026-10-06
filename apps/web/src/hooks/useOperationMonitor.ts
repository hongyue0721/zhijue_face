import { useEffect, useRef, useState } from "react";
import { ApiError, api, type OperationView } from "../api";

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
  "operation.retry_scheduled",
];

export function isTerminalOperation(operation: OperationView): boolean {
  return TERMINAL_STATUSES[operation.status];
}

export function preferObservedOperation(
  current: OperationView | null,
  next: OperationView,
): OperationView {
  if (current?.id !== next.id) return next;
  if (current && current.last_event_seq > next.last_event_seq) return current;
  if (current && isTerminalOperation(current)) {
    return isTerminalOperation(next) && next.last_event_seq > current.last_event_seq ? next : current;
  }
  return next;
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

export function isPermanentOperationMonitorError(error: unknown): error is ApiError {
  return error instanceof ApiError
    && error.status === 404
    && error.code === "RESOURCE_NOT_FOUND";
}

export function useOperationMonitor(
  operationId: string | null,
  onTerminal: (operation: OperationView, signal: AbortSignal) => void,
  onUnavailable?: (error: ApiError) => void,
  onSuccessor?: (operationId: string) => void,
) {
  const [following, setFollowing] = useState<{ root: string; id: string } | null>(null);
  const watchedId = following?.root === operationId ? following.id : operationId;
  const watchedIdRef = useRef(watchedId);
  watchedIdRef.current = watchedId;
  const [snapshot, setSnapshot] = useState<{
    id: string | null;
    operation: OperationView | null;
    error: unknown;
  }>({ id: null, operation: null, error: null });
  const onTerminalRef = useRef(onTerminal);
  onTerminalRef.current = onTerminal;
  const onUnavailableRef = useRef(onUnavailable);
  onUnavailableRef.current = onUnavailable;
  const onSuccessorRef = useRef(onSuccessor);
  onSuccessorRef.current = onSuccessor;

  useEffect(() => {
    setSnapshot({ id: watchedId, operation: null, error: null });
    if (!watchedId || !operationId) return;

    const controller = new AbortController();
    const callbackController = new AbortController();
    let source: EventSource | null = null;
    let timer: number | null = null;
    let disposed = false;
    let terminalSnapshot: OperationView | null = null;
    let transportUnavailable = false;

    const stopTransport = () => {
      timer = stopOperationTransport(timer, source, controller);
    };

    const refresh = async () => {
      if (disposed || watchedIdRef.current !== watchedId || terminalSnapshot || transportUnavailable) return;
      try {
        const next = await api.getOperation(watchedId, controller.signal);
        if (disposed || watchedIdRef.current !== watchedId || terminalSnapshot || transportUnavailable) return;
        if (next.next_operation_id) {
          terminalSnapshot = next;
          stopTransport();
          setFollowing({ root: operationId, id: next.next_operation_id });
          onSuccessorRef.current?.(next.next_operation_id);
          return;
        }
        setSnapshot((current) => ({
          id: watchedId,
          operation: preferObservedOperation(current.id === watchedId ? current.operation : null, next),
          error: null,
        }));
        if (isTerminalOperation(next)) {
          terminalSnapshot = next;
          stopTransport();
          onTerminalRef.current(next, callbackController.signal);
        }
      } catch (nextError) {
        if (
          disposed
          || watchedIdRef.current !== watchedId
          || terminalSnapshot
          || transportUnavailable
          || (nextError instanceof DOMException && nextError.name === "AbortError")
        ) {
          return;
        }
        setSnapshot((current) => ({ ...current, id: watchedId, error: nextError }));
        if (isPermanentOperationMonitorError(nextError)) {
          transportUnavailable = true;
          stopTransport();
          onUnavailableRef.current?.(nextError);
        }
      }
    };

    source = new EventSource(api.eventsUrl(watchedId));
    for (const eventName of EVENT_NAMES) source.addEventListener(eventName, refresh);
    source.onerror = () => void refresh();
    timer = window.setInterval(refresh, 800);
    void refresh();

    return () => {
      disposed = true;
      callbackController.abort();
      stopTransport();
    };
  }, [operationId, watchedId]);

  return snapshot.id === watchedId
    ? { operation: snapshot.operation, error: snapshot.error }
    : { operation: null, error: null };
}
