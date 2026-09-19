export type OperationScope = "profile" | "prepare" | "interview";

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
