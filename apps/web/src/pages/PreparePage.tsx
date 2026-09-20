import { Alert, Button, Tag } from "@any-design/anyui/react";
import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  api,
  newCommandKey,
  type CreateInterviewOptions,
  type CoverageEntryView,
  type InterviewView,
  type OperationView,
  type ProfileView,
} from "../api";
import { ErrorNotice } from "../components/common/ErrorNotice";
import { OperationStatus } from "../components/common/OperationStatus";
import { InterviewPlan } from "../components/prepare/InterviewPlan";
import { JDInput } from "../components/prepare/JDInput";
import { JDSourceBadge } from "../components/prepare/JDSourceBadge";
import { TechnicalDetails } from "../components/prepare/TechnicalDetails";
import { useOperationMonitor } from "../hooks/useOperationMonitor";
import { interviewPath, preparePath, startPath } from "../routing";
import {
  coverageExplanation,
  coverageStatusText,
  interviewRoleText,
  requirementTitle,
} from "../presentation";
import { clearOperationId, loadOperationId, saveOperationId } from "../storage";

const REQUIREMENT_TIER_COPY = {
  required: { count: "核心要求", item: "核心要求" },
  preferred: { count: "优先要求", item: "优先要求" },
  responsibility: { count: "岗位职责", item: "岗位职责" },
  contextual: { count: "场景要求", item: "场景要求" },
} as const;

function JobSummary({ interview }: { interview: InterviewView }) {
  const counts = { required: 0, preferred: 0, responsibility: 0, contextual: 0 };
  const coverageCounts: Record<CoverageEntryView["status"], number> = {
    supported: 0,
    claimed: 0,
    unverified: 0,
    unknown: 0,
    contradicted: 0,
  };
  for (const requirement of interview.jd_requirements) counts[requirement.tier] += 1;
  for (const entry of interview.coverage_map) coverageCounts[entry.status] += 1;
  return (
    <section className="surface-card job-summary" aria-labelledby="job-summary-title">
      <div className="job-summary-heading">
        <div>
          <p className="eyebrow">岗位概览</p>
          <h2 id="job-summary-title">要求与资料覆盖</h2>
        </div>
        <JDSourceBadge source={interview.jd_source} />
      </div>
      <div className="requirement-counts" aria-label="岗位要求分类统计">
        {Object.entries(counts).map(([tier, count]) => (
          <span key={tier}>
            <strong>{REQUIREMENT_TIER_COPY[tier as keyof typeof counts].count}</strong> {count}
          </span>
        ))}
      </div>
      <div className="coverage-counts" aria-label="资料覆盖统计">
        <span><strong>已有支持</strong> {coverageCounts.supported}</span>
        <span><strong>材料自述</strong> {coverageCounts.claimed}</span>
        <span><strong>待验证</strong> {coverageCounts.unverified}</span>
        <span><strong>材料未体现</strong> {coverageCounts.unknown}</span>
        <span><strong>存在冲突</strong> {coverageCounts.contradicted}</span>
      </div>
      <details className="requirement-details">
        <summary>
          查看完整岗位要求与覆盖详情（{interview.jd_requirements.length}）
        </summary>
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
          <h3>资料覆盖</h3>
          <ul className="requirement-list coverage-detail-list">
            {interview.coverage_map.map((entry) => (
              <li key={entry.competency_id}>
                <Tag>{coverageStatusText[entry.status]}</Tag>
                <span>
                  <strong>{requirementTitle(interview.jd_requirements, entry.requirement_ids)}</strong>
                  <small>{coverageExplanation(entry)}</small>
                </span>
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
      {interview ? (
        <header className="compact-page-heading prepare-ready-heading">
          <div>
            <p className="eyebrow">面试准备</p>
            <h1>{interviewRoleText(interview)}</h1>
            <p>
              {interview.jd_requirements.length} 项岗位要求
              {" · "}{interview.root_plan.slots.length} 个主问题方向
              {" · "}后续追问按回答动态决定
            </p>
          </div>
          <div className="heading-actions">
            <Tag>本场计划已准备</Tag>
            <Button
              type="primary"
              size="large"
              loading={busy && operation?.kind === "interview.start"}
              disabled={!serviceReady || busy || interview.status !== "ready"}
              onClick={startInterview}
            >
              开始模拟面试
            </Button>
          </div>
        </header>
      ) : (
        <div className="page-intro">
          <h1>输入目标岗位</h1>
          <p>填写真实岗位描述，或明确选择演示岗位配置后生成本场计划。</p>
        </div>
      )}
      <ErrorNotice error={error ?? operationError} onReload={() => void reload()} />
      {!interview ? (
        <JDInput disabled={!serviceReady} busy={busy} onGenerate={createPlan} />
      ) : (
        <>
          <div className="prepare-workspace">
            <JobSummary interview={interview} />
            <InterviewPlan
              slots={interview.root_plan.slots}
              requirements={interview.jd_requirements}
            />
          </div>
          <TechnicalDetails interview={interview} />
        </>
      )}
      <OperationStatus operation={operation} label={operation?.kind === "interview.start" ? "开始面试" : "生成面试计划"} />
    </main>
  );
}
