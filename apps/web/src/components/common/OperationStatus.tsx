import { Alert, Progress, Spinner } from "@any-design/anyui/react";
import type { OperationView } from "../../api";
import { operationStatusText } from "../../presentation";

export function OperationStatus({ operation, label }: { operation: OperationView | null; label: string }) {
  if (!operation || operation.status === "succeeded") return null;
  const active = operation.status === "queued" || operation.status === "running";
  const type = active ? "info" : "danger";
  return (
    <Alert type={type} title={`${label} · ${operationStatusText[operation.status]}`}>
      {active ? (
        <div className="operation-active">
          <Spinner size="small" />
          <Progress indeterminate status="active" />
        </div>
      ) : null}
      {operation.error ? <p>{operation.error.message}</p> : null}
    </Alert>
  );
}
