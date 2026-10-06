import { Alert } from "@any-design/anyui/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { AppHeader } from "./components/layout/AppHeader";
import { ServiceNotice, type ServiceState } from "./components/layout/ServiceNotice";
import { InterviewPage } from "./pages/InterviewPage";
import { PreparePage } from "./pages/PreparePage";
import { StartPage } from "./pages/StartPage";
import { ReportPage } from "./pages/ReportPage";
import { ResumeDraftPage } from "./pages/ResumeDraftPage";
import { KnowledgePacksPage } from "./pages/KnowledgePacksPage";
import { knowledgePacksPath, parseRoute } from "./routing";

function browserLocation(): string {
  return `${window.location.pathname}${window.location.search}`;
}

export default function App() {
  const [location, setLocation] = useState(browserLocation);
  const [service, setService] = useState<ServiceState>({ status: "checking" });
  const readinessRequest = useRef<AbortController | null>(null);
  const startPageInstance = useRef(0);
  const route = useMemo(
    () => parseRoute(window.location.pathname, window.location.search),
    [location],
  );

  const navigate = useCallback((path: string, replace = false) => {
    const previous = parseRoute(window.location.pathname, window.location.search);
    window.history[replace ? "replaceState" : "pushState"]({}, "", path);
    const next = parseRoute(window.location.pathname, window.location.search);
    // A newly-created profile adopts its URL without discarding an in-flight
    // upload/file retry. Other navigation owns a fresh profile page instance.
    if (!(replace && previous.page === "start" && !previous.profileId && next.page === "start" && next.profileId)) {
      startPageInstance.current += 1;
    }
    setLocation(browserLocation());
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({ top: 0, behavior: reduceMotion ? "auto" : "smooth" });
  }, []);

  useEffect(() => {
    if (window.location.pathname === "/") {
      navigate("/start", true);
    } else if (route.page === "redirect") {
      navigate(route.path, true);
    }
    const onPopState = () => {
      startPageInstance.current += 1;
      setLocation(browserLocation());
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [navigate, route]);

  const checkService = useCallback(() => {
    readinessRequest.current?.abort();
    const controller = new AbortController();
    readinessRequest.current = controller;
    setService({ status: "checking" });
    api.ready(controller.signal)
      .then((ready) => {
        if (readinessRequest.current !== controller) return;
        setService({ status: "ready", runMode: ready.run_mode, dataMode: ready.data_mode, contentGeneration: ready.content_generation });
      })
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (readinessRequest.current === controller) setService({ status: "unavailable" });
      });
  }, []);

  useEffect(() => {
    checkService();
    return () => readinessRequest.current?.abort();
  }, [checkService]);

  const currentStep = route.page === "start"
    ? 1
    : route.page === "prepare"
      ? 2
      : route.page === "interview"
        ? 3
        : route.page === "report"
          ? 4
          : null;
  const serviceReady = service.status === "ready";
  const contentGenerationReady = service.status === "ready" && service.contentGeneration === "configured";
  const invalidRoute = new URLSearchParams(window.location.search).get("notice") === "invalid_route";

  return (
    <div className="app-shell">
      <AppHeader currentStep={currentStep} onOpenPacks={() => navigate(knowledgePacksPath(undefined, route.page === "packs" ? route.returnTo : location))} />
      <ServiceNotice state={service} onRetry={checkService} />
      {invalidRoute ? (
        <div className="global-notice">
          <Alert type="warn" title="页面地址无效">
            已返回资料页。请从页面按钮进入面试、报告或简历草稿。
          </Alert>
        </div>
      ) : null}
      {route.page === "start" ? (
        <StartPage key={startPageInstance.current} profileId={route.profileId} serviceReady={serviceReady} contentGenerationReady={contentGenerationReady} navigate={navigate} />
      ) : route.page === "prepare" ? (
        <PreparePage
          key={route.profileId}
          profileId={route.profileId}
          interviewId={route.interviewId}
          serviceReady={serviceReady}
          navigate={navigate}
        />
      ) : route.page === "interview" ? (
        <InterviewPage
          interviewId={route.interviewId}
          serviceReady={serviceReady}
          navigate={navigate}
        />
      ) : route.page === "report" ? (
        <ReportPage
          interviewId={route.interviewId}
          serviceReady={serviceReady}
          contentGenerationReady={contentGenerationReady}
          navigate={navigate}
        />
      ) : route.page === "resume" ? (
        <ResumeDraftPage draftId={route.draftId} serviceReady={serviceReady} contentGenerationReady={contentGenerationReady} navigate={navigate} />
      ) : route.page === "packs" ? (
        <KnowledgePacksPage releaseId={route.releaseId} returnTo={route.returnTo} navigate={navigate} />
      ) : null}
    </div>
  );
}
