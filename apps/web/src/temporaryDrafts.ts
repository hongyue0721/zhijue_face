// Private bodies are written only after explicit, tab-session opt-in.
// Browsers may restore sessionStorage with a restored tab; this is not secure erasure.
const PREFIX = "zhijue:temporary-draft:";
const CONSENT = `${PREFIX}enabled`;
type Entry = { profileId: string; value: unknown; persist?: false };
const memory = new Map<string, Entry | null>();
let enabled: boolean | undefined;

export function temporaryDraftsEnabled(): boolean {
  if (enabled === undefined) {
    try { enabled = window.sessionStorage.getItem(CONSENT) === "true"; }
    catch { enabled = false; }
  }
  return enabled;
}

export function setTemporaryDraftsEnabled(value: boolean): boolean {
  enabled = value;
  try {
    if (value) {
      window.sessionStorage.setItem(CONSENT, "true");
      for (const [key, entry] of memory) {
        if (entry && entry.persist !== false) window.sessionStorage.setItem(PREFIX + key, JSON.stringify(entry));
        else window.sessionStorage.removeItem(PREFIX + key);
      }
    } else {
      for (const key of storageKeys()) window.sessionStorage.removeItem(key);
    }
    return true;
  } catch { return false; }
}

function storageKeys(): string[] {
  const keys: string[] = [];
  for (let index = 0; index < window.sessionStorage.length; index++) {
    const key = window.sessionStorage.key(index);
    if (key?.startsWith(PREFIX)) keys.push(key);
  }
  return keys;
}

export function loadTemporaryDraft(key: string): unknown {
  if (memory.has(key)) return memory.get(key)?.value;
  if (!temporaryDraftsEnabled()) return undefined;
  try {
    const raw = window.sessionStorage.getItem(PREFIX + key);
    if (!raw) return undefined;
    const entry = JSON.parse(raw) as Entry;
    if (!entry || typeof entry.profileId !== "string" || !("value" in entry)) return undefined;
    memory.set(key, entry);
    return entry.value;
  } catch { return undefined; }
}

export function saveTemporaryDraft(key: string, profileId: string, value: unknown, persist = true): boolean {
  const entry: Entry = { profileId, value, ...(persist ? {} : { persist: false as const }) };
  memory.set(key, entry);
  if (!persist || !temporaryDraftsEnabled()) return true;
  try {
    window.sessionStorage.setItem(CONSENT, "true");
    window.sessionStorage.setItem(PREFIX + key, JSON.stringify(entry));
    return true;
  } catch { return false; }
}

export function clearTemporaryDraft(key: string): boolean {
  memory.set(key, null);
  try { window.sessionStorage.removeItem(PREFIX + key); return true; }
  catch { return false; }
}

export function clearProfileTemporaryDrafts(profileId: string): boolean {
  let cleared = true;
  for (const [key, entry] of memory) {
    if (entry?.profileId === profileId) cleared = clearTemporaryDraft(key) && cleared;
  }
  try {
    for (const storageKey of storageKeys()) {
      if (storageKey === CONSENT) continue;
      const raw = window.sessionStorage.getItem(storageKey);
      if (raw && (JSON.parse(raw) as Entry).profileId === profileId) {
        cleared = clearTemporaryDraft(storageKey.slice(PREFIX.length)) && cleared;
      }
    }
  } catch { cleared = false; }
  return cleared;
}

export function temporaryDraftKeys(): string[] {
  const keys = new Set(memory.keys());
  try {
    for (const key of storageKeys()) {
      if (key !== CONSENT) keys.add(key.slice(PREFIX.length));
    }
  } catch { /* In-memory navigation still works when browser storage is denied. */ }
  return [...keys];
}
