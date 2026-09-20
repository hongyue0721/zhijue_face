export type AppRoute =
  | { page: "start"; profileId: string | null }
  | { page: "prepare"; profileId: string; interviewId: string | null }
  | { page: "interview"; interviewId: string }
  | { page: "report"; interviewId: string }
  | { page: "resume"; draftId: string };

function readQuery(search: string, name: string): string | null {
  const value = new URLSearchParams(search).get(name);
  return value?.trim() || null;
}

export function parseRoute(pathname: string, search: string): AppRoute {
  if (pathname === "/start" || pathname === "/") {
    return { page: "start", profileId: readQuery(search, "profile") };
  }
  const prepareMatch = pathname.match(/^\/profiles\/([^/]+)\/prepare$/);
  if (prepareMatch) {
    return {
      page: "prepare",
      profileId: decodeURIComponent(prepareMatch[1]),
      interviewId: readQuery(search, "interview"),
    };
  }
  const reportMatch = pathname.match(/^\/interviews\/([^/]+)\/report$/);
  if (reportMatch) {
    return { page: "report", interviewId: decodeURIComponent(reportMatch[1]) };
  }
  const interviewMatch = pathname.match(/^\/interviews\/([^/]+)$/);
  if (interviewMatch) {
    return { page: "interview", interviewId: decodeURIComponent(interviewMatch[1]) };
  }
  const resumeMatch = pathname.match(/^\/resume-drafts\/([^/]+)$/);
  if (resumeMatch) {
    return { page: "resume", draftId: decodeURIComponent(resumeMatch[1]) };
  }
  return { page: "start", profileId: null };
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
