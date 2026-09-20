export type OperationScope = "profile" | "prepare" | "interview" | "report" | "resume";

function storageKey(scope: OperationScope, resourceId: string): string {
  return `zhijue:${scope}:operation:${resourceId}`;
}

export function loadOperationId(scope: OperationScope, resourceId: string): string | null {
  try {
    return window.sessionStorage.getItem(storageKey(scope, resourceId));
  } catch {
    return null;
  }
}

export function saveOperationId(
  scope: OperationScope,
  resourceId: string,
  operationId: string,
): void {
  try {
    window.sessionStorage.setItem(storageKey(scope, resourceId), operationId);
  } catch {
    // Session storage only improves refresh recovery; API state remains authoritative.
  }
}

export function clearOperationId(scope: OperationScope, resourceId: string): void {
  try {
    window.sessionStorage.removeItem(storageKey(scope, resourceId));
  } catch {
    // The resource snapshot still recovers every server-exposed active operation.
  }
}

export type RecoverableCommandScope =
  | "report-improvements"
  | "report-resume"
  | "report-retry"
  | "resume-retry";

export type RecoverableCommand =
  | {
      kind: "report-improvements";
      idempotencyKey: string;
      input: { expected_revision: number };
    }
  | {
      kind: "report-resume";
      idempotencyKey: string;
      input: {
        profile_id: string;
        expected_revision: number;
        profile_snapshot_id: string;
        interview_id: string;
      };
    }
  | {
      kind: "report-retry";
      idempotencyKey: string;
      input: { operation_id: string; expected_revision: number };
    }
  | {
      kind: "resume-retry";
      idempotencyKey: string;
      input: { operation_id: string; expected_revision: number };
    };

function commandStorageKey(scope: RecoverableCommandScope, resourceId: string): string {
  return `zhijue:${scope}:command:${resourceId}`;
}


function parseRecoverableCommand(value: unknown): RecoverableCommand | null {
  if (
    typeof value !== "object"
    || value === null
    || !("kind" in value)
    || !("idempotencyKey" in value)
    || !("input" in value)
    || typeof value.kind !== "string"
    || typeof value.idempotencyKey !== "string"
    || typeof value.input !== "object"
    || value.input === null
    || !("expected_revision" in value.input)
    || !Number.isInteger(value.input.expected_revision)
  ) {
    return null;
  }
  const revision = value.input.expected_revision;
  if (typeof revision !== "number") return null;

  if (value.kind === "report-improvements") {
    return {
      kind: value.kind,
      idempotencyKey: value.idempotencyKey,
      input: { expected_revision: revision },
    };
  }
  if (
    value.kind === "report-resume"
    && "profile_id" in value.input
    && "profile_snapshot_id" in value.input
    && "interview_id" in value.input
    && typeof value.input.profile_id === "string"
    && typeof value.input.profile_snapshot_id === "string"
    && typeof value.input.interview_id === "string"
  ) {
    return {
      kind: value.kind,
      idempotencyKey: value.idempotencyKey,
      input: {
        profile_id: value.input.profile_id,
        expected_revision: revision,
        profile_snapshot_id: value.input.profile_snapshot_id,
        interview_id: value.input.interview_id,
      },
    };
  }
  if (
    (value.kind === "report-retry" || value.kind === "resume-retry")
    && "operation_id" in value.input
    && typeof value.input.operation_id === "string"
  ) {
    return {
      kind: value.kind,
      idempotencyKey: value.idempotencyKey,
      input: {
        operation_id: value.input.operation_id,
        expected_revision: revision,
      },
    };
  }
  return null;
}
export function loadRecoverableCommand(
  scope: RecoverableCommandScope,
  resourceId: string,
): RecoverableCommand | null {
  try {
    const raw = window.sessionStorage.getItem(commandStorageKey(scope, resourceId));
    return raw ? parseRecoverableCommand(JSON.parse(raw) as unknown) : null;
  } catch {
    return null;
  }
}

export function saveRecoverableCommand(
  scope: RecoverableCommandScope,
  resourceId: string,
  command: RecoverableCommand,
): void {
  if (scope !== command.kind) {
    throw new Error("Recoverable command scope must match its command kind.");
  }
  try {
    window.sessionStorage.setItem(
      commandStorageKey(scope, resourceId),
      JSON.stringify(command),
    );
  } catch {
    // The key and non-sensitive command identifiers only improve same-tab replay.
  }
}

export function clearRecoverableCommand(
  scope: RecoverableCommandScope,
  resourceId: string,
): void {
  try {
    window.sessionStorage.removeItem(commandStorageKey(scope, resourceId));
  } catch {
    // The server's idempotency record remains authoritative.
  }
}
