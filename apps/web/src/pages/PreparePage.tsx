import { Tag } from "@any-design/anyui/react";
import { Alert, Button } from "../components/common/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  api,
  newCommandKey,
  requestRetryReason,
  type CreateInterviewOptions,
  type CoverageEntryView,
  type InterviewView,
  type KnowledgePackList,
  type OperationView,
  type ProfileView,
} from "../api";
import { ErrorNotice } from "../components/common/ErrorNotice";
import { OperationStatus } from "../components/common/OperationStatus";
import { InterviewPlan } from "../components/prepare/InterviewPlan";
import { JDInput } from "../components/prepare/JDInput";
import { JDSourceBadge } from "../components/prepare/JDSourceBadge";
import { PackSelector } from "../components/prepare/PackSelector";
import { BackLink, PageHeading, PageNav } from "../components/layout/PageNav";
import { useOperationMonitor } from "../hooks/useOperationMonitor";
import { interviewPath, knowledgePacksPath, preparePath, startPath } from "../routing";
import {
  competencyDisplayName,
  frozenCompetencyLabels,
  coverageExplanation,
  coverageStatusText,
  interviewRoleText,
  reportLimitationText,
  requirementTitle,
} from "../presentation";
import {
  clearOperationId, loadOperationId, saveOperationId,
  clearRecoverableCommand, loadRecoverableCommand, saveRecoverableCommand,
  loadPackSelection, savePackSelection, clearPackSelection,
  type RecoverableCommand,
} from "../storage";
import { clearPrepareDraft, loadPrepareDraft, prepareDraftKey } from "../prepareDrafts";
import { clearTemporaryDraft, loadTemporaryDraft, saveTemporaryDraft, temporaryDraftsEnabled } from "../temporaryDrafts";

type PendingPlan = {
  profileId: string;
  revision: number;
  options: CreateInterviewOptions;
  key: string;
  draftKey: string;
};
type PendingStart = Extract<RecoverableCommand, { kind: "prepare-start" }>;
type PlanAttempt = {
  options: CreateInterviewOptions;
  failure: OperationView | null;
};
function loadPendingPlan(profileId: string): PendingPlan | null {
  const value = loadTemporaryDraft(`plan:${profileId}`) as PendingPlan | undefined;
  return value?.profileId === profileId && typeof value.key === "string"
    && typeof value.draftKey === "string" && Number.isInteger(value.revision)
    && value.options && typeof value.options.jd_text === "string"
    && typeof value.options.jd_source_name === "string" ? value : null;
}

function loadPlanAttempt(profileId: string): PlanAttempt | null {
  return loadTemporaryDraft(`plan-attempt:${profileId}`) as PlanAttempt | undefined ?? null;
}

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
  const coverageTone: Record<CoverageEntryView["status"], string> = {
    supported: "success",
    claimed: "primary",
    unverified: "primary",
    unknown: "warn",
    contradicted: "danger",
  };
  const competencyLabels = frozenCompetencyLabels(interview.knowledge_pack);
  return (
    <section className="job-summary prepare-section" aria-labelledby="job-summary-title">
      <div className="section-title">
        <h2 id="job-summary-title">要求与资料覆盖</h2>
        <JDSourceBadge source={interview.jd_source} />
      </div>
      <p className="requirement-counts" aria-label="岗位要求分类统计">
        {Object.entries(counts).map(([tier, count]) => (
          <span key={tier} className={count ? undefined : "is-zero"}>
            {REQUIREMENT_TIER_COPY[tier as keyof typeof counts].count} <strong>{count}</strong>
          </span>
        ))}
      </p>
      <ul className="coverage-counts" aria-label="资料覆盖统计">
        {(Object.keys(coverageCounts) as Array<CoverageEntryView["status"]>).map((status) => (
          <li key={status} className={`coverage-count coverage-count--${coverageTone[status]} ${coverageCounts[status] ? "" : "is-zero"}`}>
            <strong>{coverageCounts[status]}</strong>
            <span>{coverageStatusText[status]}</span>
          </li>
        ))}
      </ul>
      <p className="coverage-note">“材料未体现”只表示简历里没有写到，不代表不会；面试会请你用经历补充说明。</p>
      <details className="requirement-details compact-details">
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
                <Tag className={`status-tag--${coverageTone[entry.status]}`}>{coverageStatusText[entry.status]}</Tag>
                <span>
                  <strong>{competencyDisplayName(entry.competency_id, competencyLabels)}</strong>
                  <p>{requirementTitle(interview.jd_requirements, entry.requirement_ids)}</p>
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
  const draftKey = prepareDraftKey(profileId, interviewId);
  const [profile, setProfile] = useState<ProfileView | null>(null);
  const [interview, setInterview] = useState<InterviewView | null>(null);
  const [operationId, setOperationId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [settledOperation, setSettledOperation] = useState<OperationView | null>(null);
  const [planNotice, setPlanNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState(() => Boolean(interviewId && loadPrepareDraft(draftKey)));
  const [pendingPlan, setPendingPlan] = useState(() => loadPendingPlan(profileId));
  const [planAttempt, setPlanAttempt] = useState<PlanAttempt | null>(
    () => loadPlanAttempt(profileId),
  );
  const [pendingStart, setPendingStart] = useState<PendingStart | null>(() => {
    const stored = interviewId ? loadRecoverableCommand("prepare-start", interviewId) : null;
    return stored?.kind === "prepare-start" ? stored : null;
  });
  // 选择只影响新创建的面试；不阻塞列表/详情等其它入口（§6.4）。
  const [packs, setPacks] = useState<KnowledgePackList | null>(null);
  const [packsError, setPacksError] = useState<unknown>(null);
  const [selectedPackId, setSelectedPackId] = useState<string | null>(
    () => loadPackSelection(),
  );
  const [draftStorageAvailable, setDraftStorageAvailable] = useState(true);
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
    api.listKnowledgePacks(controller.signal)
      .then((next) => {
        setPacks(next);
        setPacksError(null);
      })
      .catch((nextError) => {
        if (nextError instanceof DOMException && nextError.name === "AbortError") return;
        setPacksError(nextError);
      });
    return () => controller.abort();
  }, []);

  // 选择的包被删除/未通过审核时回落到“服务端默认”，不静默用不可用包。
  useEffect(() => {
    if (!packs || !selectedPackId) return;
    const hit = packs.items.find((item) => item.pack_release_id === selectedPackId);
    if (!hit || !hit.selectable) setSelectedPackId(null);
  }, [packs, selectedPackId]);

  useEffect(() => {
    const controller = new AbortController();
    setInterview(null);
    setEditing(Boolean(interviewId && loadPrepareDraft(prepareDraftKey(profileId, interviewId))));
    setPendingPlan(loadPendingPlan(profileId));
    setPlanAttempt(loadPlanAttempt(profileId));
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
        clearTemporaryDraft(`plan-attempt:${profileId}`);
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
        const attempt = loadPlanAttempt(profileId);
        if (attempt) {
          const failedAttempt = { ...attempt, failure: settled };
          saveTemporaryDraft(`plan-attempt:${profileId}`, profileId, failedAttempt, false);
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
      profileId: profile.id, revision: profile.revision,
      options: {
        ...options,
        // 省略 = 服务端解析默认包；服务器受理时冻结实际 release。
        pack_release_id: selectedPackId ?? undefined,
      },
      draftKey,
      key: newCommandKey("plan"),
    };
    setDraftStorageAvailable(saveTemporaryDraft(`plan:${profile.id}`, profile.id, command));
    setPendingPlan(command);
    setSubmitting(true);
    requestInFlight.current = true;
    setSettledOperation(null);
    clearTemporaryDraft(`plan-attempt:${profile.id}`);
    setPlanAttempt(null);
    setPlanNotice(null);
    setError(null);
    try {
      const accepted = await api.createInterview(command.profileId, command.revision, command.options, command.key);
      const commandCleared = clearTemporaryDraft(`plan:${profile.id}`);
      setPendingPlan(null);
      setDraftStorageAvailable(clearPrepareDraft(command.draftKey) && commandCleared);
      setEditing(false);
      setInterview(null);
      saveOperationId("prepare", profile.id, accepted.operation_id);
      setOperationId(accepted.operation_id);
      const attempt = { options: command.options, failure: null };
      saveTemporaryDraft(`plan-attempt:${profile.id}`, profile.id, attempt, false);
      setPlanAttempt(attempt);
      navigate(preparePath(profile.id, accepted.resource_id), true);
    } catch (nextError) {
      setError(nextError);
      if (nextError instanceof ApiError && !requestRetryReason(nextError)) {
        setDraftStorageAvailable(clearTemporaryDraft(`plan:${profile.id}`));
        setPendingPlan(null);
      }
    } finally {
      setSubmitting(false);
      requestInFlight.current = false;
    }
  };

  const startInterview = async () => {
    // 已有计划使用其冻结快照；是否就绪由 start 接口按绑定快照校验。
    if (!interview || requestInFlight.current) return;
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

  if (profile && !profileReady && !interviewId && !interview && !pendingPlan && !pendingStart) {
    return (
      <main className="page-container narrow-page">
        <Alert type="warn" title="资料还没有准备完成">
          {profile.latest_snapshot_id
            ? "你确认的经历还在处理中。请回资料页查看进度，如果处理失败了可以在那里重试；准备完成后再来创建和开始面试。"
            : "请先回资料页核对并确认至少一条经历，等资料准备完成后再来。"}
        </Alert>
        <div className="button-row">
          <Button type="primary" onClick={() => navigate(startPath(profile.id))}>返回资料页</Button>
        </div>
      </main>
    );
  }

  const packSelector = (
    <PackSelector
      packs={packs}
      packsError={packsError}
      selectedPackId={selectedPackId}
      disabled={Boolean(pendingPlan || pendingStart)}
      onSelect={(id) => {
        setSelectedPackId(id);
        if (id) savePackSelection(id);
        else clearPackSelection();
      }}
      onManage={() => navigate(knowledgePacksPath(undefined, preparePath(profileId, interviewId ?? undefined)))}
    />
  );
  const competencyLabels = frozenCompetencyLabels(interview?.knowledge_pack);
  const planNotes = interview ? interview.limitations.map((note) => reportLimitationText(note, competencyLabels)) : [];

  return (
    <main className="page-container page-container--reading prepare-page">
      <PageNav label="准备页导航">
        <BackLink disabled={submitting || Boolean(pendingPlan || pendingStart)} onClick={() => navigate(startPath(profileId))}>返回资料</BackLink>
      </PageNav>
      {interview ? (
        <PageHeading
          className="prepare-ready-heading"
          eyebrow="面试计划已生成"
          title={interviewRoleText(interview)}
          aside={interview.status === "ready" ? (
            <Button
              type="primary"
              size="large"
              loading={busy && operation?.kind === "interview.start"}
              disabled={!serviceReady || busy || Boolean(pendingPlan || pendingStart)}
              onClick={startInterview}
            >
              开始模拟面试
            </Button>
          ) : null}
        >
          <ul className="plan-facts" aria-label="计划概况">
            <li><strong>{interview.jd_requirements.length}</strong> 项岗位要求</li>
            <li><strong>{interview.root_plan.slots.length}</strong> 个主问题方向</li>
            <li>追问按你的回答决定</li>
          </ul>
          {/* 本场包摘要来自冻结字段，不从“当前列表默认项”倒推（U7）。 */}
          <p className="interview-pack-line">
            {interview.knowledge_pack.binding === "frozen" ? (
              <>岗位知识包：{interview.knowledge_pack.name} v{interview.knowledge_pack.version}（本场固定使用）</>
            ) : interview.knowledge_pack.binding === "frozen_unavailable" ? (
              <>本场使用的岗位知识包当前不可用（内容缺失或损坏），开始面试会被拒绝，系统不会换用其他知识包。</>
            ) : (
              <>这场面试没有记录当时使用的岗位知识包版本；报告可以正常查看，继续练习请重新生成计划。</>
            )}
          </p>
          {interview.knowledge_pack.binding === "frozen" ? (
            <details className="prepare-pack-details compact-details">
              <summary>知识包版本标识</summary>
              <p className="technical-value">内容摘要：{interview.knowledge_pack.content_digest}</p>
              <p>能力规则版本：{interview.knowledge_pack.profile_version ?? "未提供"}</p>
              <p className="technical-value">规则摘要：{interview.knowledge_pack.profile_digest ?? "未提供"}</p>
            </details>
          ) : null}
        </PageHeading>
      ) : (
        <PageHeading eyebrow="面试准备" title="准备这场面试">
          <p>选择与目标岗位匹配的知识包，再填写岗位要求。能力与评分规则来自所选知识包；系统会对照你已确认的经历规划五道主问题。</p>
        </PageHeading>
      )}
      {planNotice ? <Alert type="warn" title="面试计划需要重新确认">{planNotice}</Alert> : null}
      <ErrorNotice error={error ?? operationError} onReload={() => void reload()} />
      <OperationStatus
        operation={operation ?? settledOperation ?? planAttempt?.failure ?? null}
        label={(operation ?? settledOperation ?? planAttempt?.failure)?.kind === "interview.start" ? "开始面试" : "生成面试计划"}
      />
      {!draftStorageAvailable ? <Alert type="warn" title="浏览器暂存不可用">暂存读写失败，刷新后内容可能无法恢复；如需移除旧副本，请清除本站的浏览器数据。</Alert> : null}
      {submitting && (pendingPlan || pendingStart) ? (
        <Alert type="info" title={pendingPlan ? "正在提交面试计划" : "正在提交开始面试请求"}>
          正在等待服务器接收，请不要重复点击。
        </Alert>
      ) : null}
      {!submitting && !operationActive && (pendingPlan || pendingStart) ? (
        <Alert type="warn" title={error instanceof ApiError ? "请求没有被接收" : "上次请求未确认完成"}>
          <p>
            {error instanceof ApiError
              ? "已保留这次的内容和操作，服务恢复后可原样重试。"
              : "已保留这次的内容和操作，点重试会原样续上，不会生成第二份计划或重复开始面试。"}
            {pendingPlan ? temporaryDraftsEnabled() && draftStorageAvailable
              ? "这次的内容已暂存在当前标签页，刷新后也能继续重试。"
              : "浏览器暂存没有开启，请在刷新页面前点重试。" : null}
          </p>
          <Button disabled={!serviceReady || busy} onClick={() => void (pendingPlan ? createPlan(pendingPlan.options) : startInterview())}>
            重试{pendingPlan ? "生成计划" : "开始面试"}
          </Button>
        </Alert>
      ) : null}
      {!interviewId || (interview && editing) ? (
        <JDInput
          key={draftKey}
          draftKey={draftKey}
          disabled={!serviceReady || !profileReady || Boolean(pendingPlan || pendingStart)}
          busy={busy}
          draftLocked={Boolean(pendingPlan || pendingStart)}
          initialOptions={interview ? {
            jd_source_name: interviewRoleText(interview),
            jd_text: interview.jd_text ?? "",
          } : pendingPlan?.options ?? planAttempt?.options}
          regenerating={Boolean(interview)}
          onCancel={interview ? () => { setDraftStorageAvailable(clearPrepareDraft(draftKey)); setEditing(false); } : undefined}
          onGenerate={createPlan}
          beforeActions={packSelector}
        />
      ) : interview ? (
        <div className="prepare-plan-review">
          <InterviewPlan
            slots={interview.root_plan.slots}
            requirements={interview.jd_requirements}
            competencyLabels={competencyLabels}
            notes={planNotes}
          />
          <JobSummary interview={interview} />
          <details className="prepare-context-disclosure">
            <summary>查看岗位原文与修改岗位</summary>
            <section className="prepare-job-context" aria-labelledby="prepare-job-title">
              <div className="prepare-job-context__heading">
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
              <Button type="secondary" disabled={busy || Boolean(pendingStart)} onClick={() => setEditing(true)}>修改岗位并生成新计划</Button>
            </section>
          </details>
        </div>
      ) : null}
    </main>
  );
}
