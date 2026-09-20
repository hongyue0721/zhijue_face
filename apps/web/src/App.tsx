import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "./api";
import { AppHeader } from "./components/layout/AppHeader";
import { ServiceNotice, type ServiceState } from "./components/layout/ServiceNotice";
import { InterviewPage } from "./pages/InterviewPage";
import { PreparePage } from "./pages/PreparePage";
import { StartPage } from "./pages/StartPage";
import { ReportPage } from "./pages/ReportPage";
import { ResumeDraftPage } from "./pages/ResumeDraftPage";
import { parseRoute } from "./routing";

function browserLocation(): string {
  return `${window.location.pathname}${window.location.search}`;
}

export default function App() {
  const [location, setLocation] = useState(browserLocation);
  const [service, setService] = useState<ServiceState>({ status: "checking" });
  const route = useMemo(
    () => parseRoute(window.location.pathname, window.location.search),
    [location],
  );

  const navigate = useCallback((path: string, replace = false) => {
    window.history[replace ? "replaceState" : "pushState"]({}, "", path);
    setLocation(browserLocation());
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  useEffect(() => {
    if (window.location.pathname === "/") navigate("/start", true);
    const onPopState = () => setLocation(browserLocation());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [navigate]);

  useEffect(() => {
    const controller = new AbortController();
    api.ready(controller.signal)
      .then((ready) => setService({ status: "ready", runMode: ready.run_mode }))
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (error instanceof ApiError && error.code === "SERVICE_NOT_READY") {
          setService({ status: "unavailable" });
          return;
        }
        setService({ status: "unavailable" });
      });
    return () => controller.abort();
  }, []);

  const currentStep = route.page === "start" ? 1 : route.page === "prepare" ? 2 : 3;
  const serviceReady = service.status === "ready";

  return (
    <div className="app-shell">
      <AppHeader currentStep={currentStep} />
      <ServiceNotice state={service} />
      {route.page === "start" ? (
        <StartPage profileId={route.profileId} serviceReady={serviceReady} navigate={navigate} />
      ) : route.page === "prepare" ? (
        <PreparePage
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
          navigate={navigate}
        />
      ) : (
        <ResumeDraftPage draftId={route.draftId} serviceReady={serviceReady} />
      )}
    </div>
  );
}
