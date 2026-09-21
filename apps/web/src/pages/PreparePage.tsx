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
// Private JD bodies survive in-app navigation only; never browser storage.
const pendingPlans = new Map<string, PendingPlan>();

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
  const [editing, setEditing] = useState(false);
  const [pendingPlan, setPendingPlan] = useState(() => pendingPlans.get(profileId) ?? null);
  const [pendingStart, setPendingStart] = useState<PendingStart | null>(() => {
    const stored = interviewId ? loadRecoverableCommand("prepare-start", interviewId) : null;
    return stored?.kind === "prepare-start" ? stored : null;
  });
  const requestInFlight = useRef(false);

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
    setInterview(null);
    setEditing(false);
    setPendingPlan(pendingPlans.get(profileId) ?? null);
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
      } else {
        // 失败/中断的旧计划操作：清掉恢复键，避免每次进页面重复拉取并短暂
        // 误锁 busy；用户下次显式生成会创建全新 operation。
        clearOperationId("prepare", profileId);
        setOperationId(null);
        if (interviewId && settled.kind !== "interview.plan") {
          applyInterview(await api.getInterview(interviewId));
        }
      }
    } catch (nextError) {
      setError(nextError);
    }
  }, [applyInterview, interviewId, navigate, profileId]);

  const { operation, error: operationError } = useOperationMonitor(operationId, operationSettled);
  const operationActive = Boolean(operationId) && (!operation || operation.status === "queued" || operation.status === "running");
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
    setError(null);
    try {
      const accepted = await api.createInterview(command.profileId, command.revision, command.options, command.key);
      pendingPlans.delete(profile.id);
      setPendingPlan(null);
      setEditing(false);
      setInterview(null);
      saveOperationId("prepare", profile.id, accepted.operation_id);
      setOperationId(accepted.operation_id);
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
        <Alert type="warn" title="资料快照尚未就绪">
          {profile.latest_snapshot_id
            ? "已确认的资料还未完成索引激活。请返回资料页查看进度或恢复失败操作，完成后再创建和开始面试。"
            : "请先返回资料页确认有效事实，生成并激活资料快照。"}
        </Alert>
        <Button type="primary" onClick={() => navigate(startPath(profile.id))}>返回资料并恢复</Button>
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
      <ErrorNotice error={error ?? operationError} onReload={() => void reload()} />
      {pendingPlan || pendingStart ? (
        <Alert type="warn" title="上次请求尚未取得明确受理结果">
          不会自动创建第二份计划。请使用原请求标识与原始内容重试；岗位正文只在本次页面会话内保留，刷新前请先恢复。
          <Button disabled={!serviceReady || busy} onClick={() => void (pendingPlan ? createPlan(pendingPlan.options) : startInterview())}>
            使用原请求重试{pendingPlan ? "生成计划" : "开始面试"}
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
          } : pendingPlan?.options}
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
                    ? "本场采用演示岗位配置，以下为计划使用的岗位要求。"
                    : "该历史会话未保存原始岗位输入。以下是已冻结要求，不冒充完整 JD 原文；修改时请重新粘贴原文。"}</p>
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
      <OperationStatus operation={operation} label={operation?.kind === "interview.start" ? "开始面试" : "生成面试计划"} />
    </main>
  );
}
