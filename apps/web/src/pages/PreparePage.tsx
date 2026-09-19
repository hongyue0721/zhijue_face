import { Alert, Button, Tag } from "@any-design/anyui/react";
import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  api,
  newCommandKey,
  type CreateInterviewOptions,
  type InterviewView,
  type OperationView,
  type ProfileView,
} from "../api";
import { ErrorNotice } from "../components/common/ErrorNotice";
import { OperationStatus } from "../components/common/OperationStatus";
import { CoverageMap } from "../components/prepare/CoverageMap";
import { InterviewPlan } from "../components/prepare/InterviewPlan";
import { JDInput } from "../components/prepare/JDInput";
import { JDSourceBadge } from "../components/prepare/JDSourceBadge";
import { TechnicalDetails } from "../components/prepare/TechnicalDetails";
import { useOperationMonitor } from "../hooks/useOperationMonitor";
import { interviewPath, preparePath, startPath } from "../routing";
import { interviewRoleText, requirementTierText } from "../presentation";
import { clearOperationId, loadOperationId, saveOperationId } from "../storage";

export function PreparePage({
  profileId,
  interviewId,
  serviceReady,
  navigate,
}: {
  profileId: string;
  interviewId: string | null;
  serviceReady: boolean;
  navigate: (path: string, replace?: boolean) => void;
}) {
  const [profile, setProfile] = useState<ProfileView | null>(null);
  const [interview, setInterview] = useState<InterviewView | null>(null);
  const [operationId, setOperationId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const applyInterview = useCallback((next: InterviewView) => {
    setInterview(next);
    if (next.active_operation_id) {
      saveOperationId("prepare", profileId, next.active_operation_id);
      setOperationId(next.active_operation_id);
    } else if (["active", "finishing", "completed"].includes(next.status)) {
      navigate(interviewPath(next.id), true);
    }
  }, [navigate, profileId]);

  const reload = useCallback(async () => {
    const nextProfile = await api.getProfile(profileId);
    setProfile(nextProfile);
    if (interviewId) applyInterview(await api.getInterview(interviewId));
  }, [applyInterview, interviewId, profileId]);

  useEffect(() => {
    const controller = new AbortController();
    const storedOperationId = loadOperationId("prepare", profileId);
    setOperationId(storedOperationId);
    setError(null);
    api.getProfile(profileId, controller.signal)
      .then(setProfile)
      .catch((nextError) => {
        if (!(nextError instanceof DOMException && nextError.name === "AbortError")) setError(nextError);
      });
    if (interviewId) {
      api.getInterview(interviewId, controller.signal)
        .then(applyInterview)
        .catch((nextError) => {
          const waitingForPlan = nextError instanceof ApiError
            && nextError.code === "RESOURCE_NOT_FOUND"
            && storedOperationId;
          if (!waitingForPlan && !(nextError instanceof DOMException && nextError.name === "AbortError")) {
            setError(nextError);
          }
        });
    }
    return () => controller.abort();
  }, [applyInterview, interviewId, profileId]);

  const operationSettled = useCallback(async (settled: OperationView) => {
    setSubmitting(false);
    try {
      if (settled.status === "succeeded") {
        const next = await api.getInterview(settled.resource_id);
        clearOperationId("prepare", profileId);
        setOperationId(null);
        if (settled.kind === "interview.start") {
          navigate(interviewPath(next.id), true);
        } else {
          setInterview(next);
        }
      } else if (interviewId && settled.kind !== "interview.plan") {
        applyInterview(await api.getInterview(interviewId));
      }
    } catch (nextError) {
      setError(nextError);
    }
  }, [applyInterview, interviewId, navigate, profileId]);

  const { operation, error: operationError } = useOperationMonitor(operationId, operationSettled);
  const operationActive = operation?.status === "queued" || operation?.status === "running";
  const busy = submitting || operationActive;

  const createPlan = async (options: CreateInterviewOptions) => {
    if (!profile?.latest_snapshot_id) return;
    setSubmitting(true);
    setError(null);
    try {
      const accepted = await api.createInterview(
        profile.id,
        profile.revision,
        options,
        newCommandKey("plan"),
      );
      saveOperationId("prepare", profile.id, accepted.operation_id);
      navigate(preparePath(profile.id, accepted.resource_id), true);
      setOperationId(accepted.operation_id);
    } catch (nextError) {
      setSubmitting(false);
      setError(nextError);
    }
  };

  const startInterview = async () => {
    if (!interview) return;
    setSubmitting(true);
    setError(null);
    try {
      const accepted = await api.startInterview(
        interview.id,
        interview.revision,
        newCommandKey("start"),
      );
      saveOperationId("prepare", profileId, accepted.operation_id);
      setOperationId(accepted.operation_id);
    } catch (nextError) {
      setSubmitting(false);
      setError(nextError);
    }
  };

  if (profile && !profile.latest_snapshot_id) {
    return (
      <main className="page-container narrow-page">
        <Alert type="warn" title="资料尚未确认">
          创建面试前必须存在服务端 Profile Snapshot。页面不会绕过这一门槛。
        </Alert>
        <Button type="primary" onClick={() => navigate(startPath(profile.id))}>返回确认资料</Button>
      </main>
    );
  }

  return (
    <main className="page-container prepare-page">
      <div className="page-intro">
        <p className="eyebrow">Step 2 · Preparation</p>
        <h1>准备面试</h1>
        <p>岗位要求与资料覆盖由服务端计划结果驱动，页面不会提前展示尚未生成的具体题目。</p>
      </div>
      <ErrorNotice error={error ?? operationError} onReload={() => void reload()} />
      {!interview ? (
        <JDInput disabled={!serviceReady} busy={busy} onGenerate={createPlan} />
      ) : (
        <>
          <section className="surface-card job-summary" aria-labelledby="job-summary-title">
            <div>
              <p className="eyebrow">本场岗位</p>
              <h2 id="job-summary-title">{interviewRoleText(interview)}</h2>
            </div>
            <JDSourceBadge source={interview.jd_source} />
            <ul className="requirement-list">
              {interview.jd_requirements.map((requirement) => (
                <li key={requirement.id}>
                  <Tag>{requirementTierText(requirement.tier)}</Tag>
                  <span>{requirement.statement}</span>
                </li>
              ))}
            </ul>
          </section>
          <div className="plan-grid">
            <CoverageMap entries={interview.coverage_map} requirements={interview.jd_requirements} />
            <InterviewPlan slots={interview.root_plan.slots} requirements={interview.jd_requirements} />
          </div>
          <TechnicalDetails interview={interview} />
          <section className="surface-card ready-card plan-ready">
            <div>
              <p className="eyebrow">Plan Ready</p>
              <h2>验证计划已准备</h2>
              <p>开始后将按当前五题计划动态生成题目，具体措辞以 Interview.current_question 为准。</p>
            </div>
            <Button
              type="primary"
              size="large"
              loading={busy && operation?.kind === "interview.start"}
              disabled={!serviceReady || busy || interview.status !== "ready"}
              onClick={startInterview}
            >
              开始模拟面试
            </Button>
          </section>
        </>
      )}
      <OperationStatus operation={operation} label={operation?.kind === "interview.start" ? "开始面试" : "生成面试计划"} />
    </main>
  );
}
