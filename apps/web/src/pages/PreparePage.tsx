import { Alert, Button, Tag } from "@any-design/anyui/react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  api,
  newCommandKey,
  requestRetryReason,
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
import {
  clearOperationId, loadOperationId, saveOperationId,
  clearRecoverableCommand, loadRecoverableCommand, saveRecoverableCommand,
  type RecoverableCommand,
} from "../storage";

type PendingPlan = {
  profileId: string;
  revision: number;
  options: CreateInterviewOptions;
  key: string;
};
type PendingStart = Extract<RecoverableCommand, { kind: "prepare-start" }>;
type PlanAttempt = {
  options: CreateInterviewOptions;
  failure: OperationView | null;
};
// Private JD bodies survive in-app route replacement only; never browser storage.
const pendingPlans = new Map<string, PendingPlan>();
const planAttempts = new Map<string, PlanAttempt>();

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
  const [settledOperation, setSettledOperation] = useState<OperationView | null>(null);
  const [planNotice, setPlanNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [pendingPlan, setPendingPlan] = useState(() => pendingPlans.get(profileId) ?? null);
  const [planAttempt, setPlanAttempt] = useState<PlanAttempt | null>(
    () => planAttempts.get(profileId) ?? null,
  );
  const [pendingStart, setPendingStart] = useState<PendingStart | null>(() => {
    const stored = interviewId ? loadRecoverableCommand("prepare-start", interviewId) : null;
    return stored?.kind === "prepare-start" ? stored : null;
  });
  const requestInFlight = useRef(false);

  const applyInterview = useCallback((next: InterviewView) => {
    setPlanNotice(null);
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
    if (!interviewId) return;
    try {
      applyInterview(await api.getInterview(interviewId));
    } catch (nextError) {
      if (nextError instanceof ApiError && nextError.code === "RESOURCE_NOT_FOUND") {
        setInterview(null);
        setPlanNotice("这个链接对应的面试计划不存在或没有生成成功，已返回岗位输入。");
        navigate(preparePath(profileId), true);
        return;
      }
      throw nextError;
    }
  }, [applyInterview, interviewId, navigate, profileId]);

  useEffect(() => {
    const controller = new AbortController();
    setInterview(null);
    setEditing(false);
    setPendingPlan(pendingPlans.get(profileId) ?? null);
    setPlanAttempt(planAttempts.get(profileId) ?? null);
    const storedStart = interviewId ? loadRecoverableCommand("prepare-start", interviewId) : null;
    setPendingStart(storedStart?.kind === "prepare-start" ? storedStart : null);
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
          const missingInterview = nextError instanceof ApiError
            && nextError.code === "RESOURCE_NOT_FOUND";
          if (missingInterview && storedOperationId) return;
          if (missingInterview) {
            setInterview(null);
            setPlanNotice("这个链接对应的面试计划不存在或没有生成成功，已返回岗位输入。");
            navigate(preparePath(profileId), true);
            return;
          }
          if (!(nextError instanceof DOMException && nextError.name === "AbortError")) {
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
        setSettledOperation(null);
        planAttempts.delete(profileId);
        setPlanAttempt(null);
        const next = await api.getInterview(settled.resource_id);
        clearOperationId("prepare", profileId);
        setOperationId(null);
        if (settled.kind === "interview.start") {
          navigate(interviewPath(next.id), true);
        } else {
          setInterview(next);
        }
        return;
      }

      // 终态失败要留在页面说明真实原因，但不能再把同一个 failed operation
      // 从 Interview.active_operation_id 挂回监控，否则会无限重读。
      setSettledOperation(settled);
      if (settled.kind === "interview.plan") {
        const attempt = planAttempts.get(profileId);
        if (attempt) {
          const failedAttempt = { ...attempt, failure: settled };
          planAttempts.set(profileId, failedAttempt);
          setPlanAttempt(failedAttempt);
        }
      }
      clearOperationId("prepare", profileId);
      setOperationId(null);
      if (settled.kind === "interview.plan") {
        setInterview(null);
        navigate(preparePath(profileId), true);
      } else if (interviewId) {
        setInterview(await api.getInterview(interviewId));
      }
    } catch (nextError) {
      setError(nextError);
    }
  }, [interviewId, navigate, profileId]);

  const operationUnavailable = useCallback(() => {
    clearOperationId("prepare", profileId);
    setOperationId(null);
    setSubmitting(false);
    setPlanNotice("上次处理记录已经不存在，页面已停止继续查询。请核对岗位内容后重新生成。");
    if (!interview) navigate(preparePath(profileId), true);
  }, [interview, navigate, profileId]);
  const { operation, error: operationError } = useOperationMonitor(
    operationId,
    operationSettled,
    operationUnavailable,
  );
  const operationActive = Boolean(operationId)
    && !operationError
    && (!operation || operation.status === "queued" || operation.status === "running");
  const busy = submitting || operationActive;
  const profileReady = Boolean(profile?.latest_snapshot_id
    && profile.snapshot_activation?.snapshot_id === profile.latest_snapshot_id
    && profile.snapshot_activation.status === "ready");

  const createPlan = async (options: CreateInterviewOptions) => {
    if (!profile || requestInFlight.current || (!pendingPlan && !profileReady)) return;
    const command = pendingPlan ?? {
      profileId: profile.id, revision: profile.revision, options, key: newCommandKey("plan"),
    };
    pendingPlans.set(profile.id, command);
    setPendingPlan(command);
    setSubmitting(true);
    requestInFlight.current = true;
    setSettledOperation(null);
    planAttempts.delete(profile.id);
    setPlanAttempt(null);
    setPlanNotice(null);
    setError(null);
    try {
      const accepted = await api.createInterview(command.profileId, command.revision, command.options, command.key);
      pendingPlans.delete(profile.id);
      setPendingPlan(null);
      setEditing(false);
      setInterview(null);
      saveOperationId("prepare", profile.id, accepted.operation_id);
      setOperationId(accepted.operation_id);
      const attempt = { options: command.options, failure: null };
      planAttempts.set(profile.id, attempt);
      setPlanAttempt(attempt);
      navigate(preparePath(profile.id, accepted.resource_id), true);
    } catch (nextError) {
      setError(nextError);
      if (nextError instanceof ApiError && !requestRetryReason(nextError)) {
        pendingPlans.delete(profile.id);
        setPendingPlan(null);
      }
    } finally {
      setSubmitting(false);
      requestInFlight.current = false;
    }
  };

  const startInterview = async () => {
    if (!interview || requestInFlight.current || (!pendingStart && !profileReady)) return;
    const command: PendingStart = pendingStart ?? {
      kind: "prepare-start", idempotencyKey: newCommandKey("start"),
      input: { expected_revision: interview.revision },
    };
    setPendingStart(command);
    saveRecoverableCommand("prepare-start", interview.id, command);
    setSubmitting(true);
    requestInFlight.current = true;
    setError(null);
    setSettledOperation(null);
    try {
      const accepted = await api.startInterview(interview.id, command.input.expected_revision, command.idempotencyKey);
      clearRecoverableCommand("prepare-start", interview.id);
      setPendingStart(null);
      saveOperationId("prepare", profileId, accepted.operation_id);
      setOperationId(accepted.operation_id);
    } catch (nextError) {
      setError(nextError);
      if (nextError instanceof ApiError && !requestRetryReason(nextError)) {
        clearRecoverableCommand("prepare-start", interview.id);
        setPendingStart(null);
      }
    } finally {
      setSubmitting(false);
      requestInFlight.current = false;
    }
  };

  if (profile && !profileReady && !pendingPlan && !pendingStart) {
    return (
      <main className="page-container narrow-page">
        <Alert type="warn" title="资料还没有准备完成">
          {profile.latest_snapshot_id
            ? "你确认的经历还在处理中。请回资料页查看进度，如果处理失败了可以在那里重试；准备完成后再来创建和开始面试。"
            : "请先回资料页核对并确认至少一条经历，等资料准备完成后再来。"}
        </Alert>
        <Button type="primary" onClick={() => navigate(startPath(profile.id))}>返回资料页</Button>
      </main>
    );
  }

  return (
    <main className="page-container prepare-page">
      <div className="prepare-navigation">
        <Button disabled={submitting || Boolean(pendingPlan || pendingStart)} onClick={() => navigate(startPath(profileId))}>返回资料</Button>
      </div>
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
            <Button disabled={busy || Boolean(pendingPlan || pendingStart)} onClick={() => setEditing(true)}>修改岗位 / JD</Button>
            <Button
              type="primary"
              size="large"
              loading={busy && operation?.kind === "interview.start"}
              disabled={!serviceReady || busy || editing || !profileReady || Boolean(pendingPlan || pendingStart) || interview.status !== "ready"}
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
      {planNotice ? <Alert type="warn" title="面试计划需要重新确认">{planNotice}</Alert> : null}
      <ErrorNotice error={error ?? operationError} onReload={() => void reload()} />
      <OperationStatus
        operation={operation ?? settledOperation ?? planAttempt?.failure ?? null}
        label={(operation ?? settledOperation ?? planAttempt?.failure)?.kind === "interview.start" ? "开始面试" : "生成面试计划"}
      />
      {pendingPlan || pendingStart ? (
        <Alert type="warn" title="上次请求未确认完成">
          已保留这次的内容和操作，点重试会原样续上，不会生成第二份计划或重复开始面试。岗位正文只存在本页面里，刷新前请先点重试。
          <Button disabled={!serviceReady || busy} onClick={() => void (pendingPlan ? createPlan(pendingPlan.options) : startInterview())}>
            重试{pendingPlan ? "生成计划" : "开始面试"}
          </Button>
        </Alert>
      ) : null}
      {!interview || editing ? (
        <JDInput
          key={interview?.id ?? "new"}
          disabled={!serviceReady || !profileReady || Boolean(pendingPlan || pendingStart)}
          busy={busy}
          initialOptions={interview ? {
            jd_source_name: interviewRoleText(interview),
            jd_text: interview.jd_text ?? "",
          } : pendingPlan?.options ?? planAttempt?.options}
          regenerating={Boolean(interview)}
          onCancel={interview ? () => setEditing(false) : undefined}
          onGenerate={createPlan}
        />
      ) : (
        <>
          <div className="prepare-workspace">
            <section className="surface-card prepare-job-context" aria-labelledby="prepare-job-title">
              <div className="section-heading compact">
                <p className="eyebrow">核对本场岗位</p>
                <h2 id="prepare-job-title">{interviewRoleText(interview)}</h2>
                <JDSourceBadge source={interview.jd_source} />
              </div>
              {interview.jd_text !== null ? (
                <p className="prepare-jd-original">{interview.jd_text}</p>
              ) : (
                <>
                  <p>{interview.jd_source.source_type === "synthetic_demo_jd"
                    ? "本场使用演示岗位配置，下面是计划采用的岗位要求。"
                    : "这场面试没有保存你当时粘贴的岗位原文。下面是当时提取并锁定的岗位要求，措辞可能与原文不完全一致；如需修改请重新粘贴完整原文。"}</p>
                  <ul className="requirement-list">
                    {interview.jd_requirements.filter((requirement) => requirement.tier === "required" || requirement.tier === "responsibility").map((requirement) => (
                      <li key={requirement.id}>{requirement.statement}</li>
                    ))}
                  </ul>
                </>
              )}
              <Button disabled={busy || Boolean(pendingStart)} onClick={() => setEditing(true)}>修改岗位并生成新计划</Button>
            </section>
            <JobSummary interview={interview} />
            <InterviewPlan
              slots={interview.root_plan.slots}
              requirements={interview.jd_requirements}
            />
          </div>
          <TechnicalDetails interview={interview} />
        </>
      )}
    </main>
  );
}
