import type { ProfileView } from "./api";

/** A response belongs to one route and must never roll its revision back. */
export function acceptsProfileSnapshot(
  current: Pick<ProfileView, "id" | "revision"> | null,
  next: Pick<ProfileView, "id" | "revision">,
  profileId: string | null,
): boolean {
  return (!profileId || next.id === profileId)
    && (!current || (current.id === next.id && next.revision >= current.revision));
}
