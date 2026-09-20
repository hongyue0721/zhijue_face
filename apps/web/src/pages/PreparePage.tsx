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
import { interviewRoleText } from "../presentation";
import { clearOperationId, loadOperationId, saveOperationId } from "../storage";

const REQUIREMENT_TIER_COPY = {
  required: { count: "核心要求", item: "核心要求" },
  preferred: { count: "优先要求", item: "优先要求" },
  responsibility: { count: "岗位职责", item: "岗位职责" },
  contextual: { count: "场景要求", item: "场景要求" },
} as const;

function JobSummary({ interview }: { interview: InterviewView }) {
  const counts = { required: 0, preferred: 0, responsibility: 0, contextual: 0 };
  for (const requirement of interview.jd_requirements) counts[requirement.tier] += 1;
  return (
    <section className="surface-card job-summary" aria-labelledby="job-summary-title">
      <div className="job-summary-heading">
        <div>
          <p className="eyebrow">本场岗位</p>
          <h2 id="job-summary-title">{interviewRoleText(interview)}</h2>
        </div>
        <JDSourceBadge source={interview.jd_source} />
      </div>
      <div className="requirement-counts" aria-label="岗位要求分类统计">
        {Object.entries(counts).map(([tier, count]) => (
          <span key={tier}><strong>{REQUIREMENT_TIER_COPY[tier as keyof typeof counts].count}</strong> {count}</span>
        ))}
      </div>
      <details className="requirement-details">
        <summary>查看完整岗位要求（{interview.jd_requirements.length}）</summary>
        <div className="requirement-details-body">
          <h3>完整岗位要求</h3>
          <ul className="requirement-list">
            {interview.jd_requirements.map((requirement) => (
              <li key={requirement.id}>
                <Tag>{REQUIREMENT_TIER_COPY[requirement.tier].item}</Tag>
                <span>{requirement.statement}</span>
              </li>
            ))}
          </ul>
        </div>
      </details>
    </section>
  );
}

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
          创建面试前必须存在服务端资料快照。页面不会绕过这一门槛。
        </Alert>
        <Button type="primary" onClick={() => navigate(startPath(profile.id))}>返回确认资料</Button>
      </main>
    );
  }

  return (
    <main className="page-container prepare-page">
      <div className="page-intro">
        <p className="eyebrow">面试准备</p>
        <h1>面试准备</h1>
        <p>根据你的资料与岗位要求，系统已经生成本场验证计划。</p>
      </div>
      <ErrorNotice error={error ?? operationError} onReload={() => void reload()} />
      {!interview ? (
        <JDInput disabled={!serviceReady} busy={busy} onGenerate={createPlan} />
      ) : (
        <>
          <JobSummary interview={interview} />
          <section className="surface-card ready-card plan-ready">
            <div>
              <p className="eyebrow">准备完成</p>
              <h2>本场验证计划已准备</h2>
              <p>开始后将根据当前五题计划生成本场主问题；后续是否追问、澄清或进入下一题，将根据你的回答动态决定。</p>
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
          <div className="plan-grid">
            <CoverageMap entries={interview.coverage_map} requirements={interview.jd_requirements} />
            <InterviewPlan slots={interview.root_plan.slots} requirements={interview.jd_requirements} />
          </div>
          <TechnicalDetails interview={interview} />
        </>
      )}
      <OperationStatus operation={operation} label={operation?.kind === "interview.start" ? "开始面试" : "生成面试计划"} />
    </main>
  );
}
