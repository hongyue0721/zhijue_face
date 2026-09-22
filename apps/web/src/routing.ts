export type AppRoute =
  | { page: "start"; profileId: string | null }
  | { page: "prepare"; profileId: string; interviewId: string | null }
  | { page: "interview"; interviewId: string }
  | { page: "report"; interviewId: string }
  | { page: "resume"; draftId: string }
  | { page: "redirect"; path: string };

function readQuery(search: string, name: string): string | null {
  const value = new URLSearchParams(search).get(name);
  return value?.trim() || null;
}

function decodePathSegment(value: string): string | null {
  try {
    return decodeURIComponent(value).trim() || null;
  } catch {
    return null;
  }
}

export function parseRoute(pathname: string, search: string): AppRoute {
  if (pathname === "/start" || pathname === "/") {
    return { page: "start", profileId: readQuery(search, "profile") };
  }
  const prepareMatch = pathname.match(/^\/profiles\/([^/]+)\/prepare$/);
  if (prepareMatch) {
    const profileId = decodePathSegment(prepareMatch[1]);
    return profileId
      ? { page: "prepare", profileId, interviewId: readQuery(search, "interview") }
      : { page: "redirect", path: "/start?notice=invalid_route" };
  }
  const reportMatch = pathname.match(/^\/interviews\/([^/]+)\/report$/);
  if (reportMatch) {
    const interviewId = decodePathSegment(reportMatch[1]);
    return interviewId
      ? { page: "report", interviewId }
      : { page: "redirect", path: "/start?notice=invalid_route" };
  }
  const interviewMatch = pathname.match(/^\/interviews\/([^/]+)$/);
  if (interviewMatch) {
    const interviewId = decodePathSegment(interviewMatch[1]);
    return interviewId
      ? { page: "interview", interviewId }
      : { page: "redirect", path: "/start?notice=invalid_route" };
  }
  const resumeMatch = pathname.match(/^\/resume-drafts\/([^/]+)$/);
  if (resumeMatch) {
    const draftId = decodePathSegment(resumeMatch[1]);
    return draftId
      ? { page: "resume", draftId }
      : { page: "redirect", path: "/start?notice=invalid_route" };
  }
  return { page: "redirect", path: "/start?notice=invalid_route" };
}

export function startPath(profileId?: string): string {
  return profileId ? `/start?profile=${encodeURIComponent(profileId)}` : "/start";
}

export function preparePath(profileId: string, interviewId?: string): string {
  const base = `/profiles/${encodeURIComponent(profileId)}/prepare`;
  return interviewId ? `${base}?interview=${encodeURIComponent(interviewId)}` : base;
}

export function interviewPath(interviewId: string): string {
  return `/interviews/${encodeURIComponent(interviewId)}`;
}

export function reportPath(interviewId: string): string {
  return `/interviews/${encodeURIComponent(interviewId)}/report`;
}

export function resumeDraftPath(draftId: string): string {
  return `/resume-drafts/${encodeURIComponent(draftId)}`;
}
