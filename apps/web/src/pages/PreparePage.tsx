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
  type KnowledgePackList,
  type OperationView,
  type ProfileView,
} from "../api";
import { ErrorNotice } from "../components/common/ErrorNotice";
import { OperationStatus } from "../components/common/OperationStatus";
import { InterviewPlan } from "../components/prepare/InterviewPlan";
import { JDInput } from "../components/prepare/JDInput";
import { JDSourceBadge } from "../components/prepare/JDSourceBadge";
import { useOperationMonitor } from "../hooks/useOperationMonitor";
import { interviewPath, knowledgePacksPath, preparePath, startPath } from "../routing";
import {
  coverageExplanation,
  coverageStatusText,
  interviewRoleText,
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
  return (
    <section className="job-summary prepare-section" aria-labelledby="job-summary-title">
      <div className="job-summary-heading">
        <div>
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
            <h1>{interviewRoleText(interview)}</h1>
            <p>
              {interview.jd_requirements.length} 项岗位要求
              {" · "}{interview.root_plan.slots.length} 个主问题方向
              {" · "}后续追问按回答动态决定
            </p>
            {/* 本场包摘要来自冻结字段，不从“当前列表默认项”倒推（U7）。 */}
            <p className="interview-pack-line">
              {interview.knowledge_pack.binding === "frozen" ? (
                <>岗位知识包：{interview.knowledge_pack.name} v{interview.knowledge_pack.version}（本场冻结）</>
              ) : interview.knowledge_pack.binding === "frozen_unavailable" ? (
                <>本场冻结的岗位知识包当前不可用（内容缺失或损坏）；开始面试会被明确拒绝，不会换包顶替。</>
              ) : (
                <>历史绑定未确定：这场面试创建时没有可证实的岗位包绑定；报告仍完整可读，继续练习请重新创建计划。</>
              )}
            </p>
            {interview.knowledge_pack.binding === "frozen" ? (
              <details className="prepare-pack-details">
                <summary>岗位知识包技术详情</summary>
                <p className="technical-value">内容摘要：{interview.knowledge_pack.content_digest}</p>
              </details>
            ) : null}
          </div>
          {interview.status === "ready" ? (
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
        </header>
      ) : (
        <div className="page-intro">
          <h1>准备这场面试</h1>

        </div>
      )}
      {planNotice ? <Alert type="warn" title="面试计划需要重新确认">{planNotice}</Alert> : null}
      <ErrorNotice error={error ?? operationError} onReload={() => void reload()} />
      <OperationStatus
        operation={operation ?? settledOperation ?? planAttempt?.failure ?? null}
        label={(operation ?? settledOperation ?? planAttempt?.failure)?.kind === "interview.start" ? "开始面试" : "生成面试计划"}
      />
      {!draftStorageAvailable ? <Alert type="warn" title="浏览器暂存不可用">无法确认请求内容的临时保存或清除。请在离开或刷新前核对当前操作；需要移除旧副本时请清除此站点的浏览器数据。</Alert> : null}
      {submitting && (pendingPlan || pendingStart) ? (
        <Alert type="info" title={pendingPlan ? "正在提交面试计划" : "正在提交开始面试请求"}>
          正在等待服务端受理，请勿重复提交。
        </Alert>
      ) : null}
      {!submitting && !operationActive && (pendingPlan || pendingStart) ? (
        <Alert type="warn" title={error instanceof ApiError ? "请求尚未受理" : "上次请求未确认完成"}>
          {error instanceof ApiError
            ? "已保留这次的内容和操作，服务恢复后可原样重试。"
            : "已保留这次的内容和操作，点重试会原样续上，不会生成第二份计划或重复开始面试。"}
          {pendingPlan ? temporaryDraftsEnabled() && draftStorageAvailable
            ? "请求内容与重试标识已一同临时保存在本标签页，刷新后可恢复。"
            : "浏览器暂存未开启或不可用，请在刷新前重试确认结果。" : null}
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
        />
      ) : interview ? (
        <>
          <div className="prepare-workspace prepare-plan-review">
            <details className="prepare-context-disclosure">
              <summary>查看岗位原文与修改岗位</summary>
              <section className="prepare-job-context" aria-labelledby="prepare-job-title">
                <h2 id="prepare-job-title">{interviewRoleText(interview)}</h2>
                <JDSourceBadge source={interview.jd_source} />
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
            </details>
            <JobSummary interview={interview} />
            <InterviewPlan
              slots={interview.root_plan.slots}
              requirements={interview.jd_requirements}
            />
          </div>
        </>
      ) : null}
      {!interview || editing ? (
        <section className="pack-selector" aria-label="岗位知识包选择">
          <label className="field-label">
            本场新面试使用岗位知识包
            <select
              value={selectedPackId ?? ""}
              disabled={Boolean(pendingPlan || pendingStart)}
              onChange={(event) => {
                const id = event.target.value;
                setSelectedPackId(id || null);
                if (id) savePackSelection(id);
                else clearPackSelection();
              }}
            >
              <option value="">
                服务端默认（
                {packs?.items.find((item) => item.pack_release_id === packs?.default_pack_release_id)?.name
                  ?? (packsError ? "读取失败" : "读取中…")}
                ）
              </option>
              {(packs?.items ?? [])
                .filter((item) => item.selectable)
                .map((item) => (
                  <option key={item.pack_release_id} value={item.pack_release_id}>
                    {item.name} v{item.version}
                  </option>
                ))}
            </select>
          </label>
          <small>
            选择只影响新创建的面试；已创建的面试永远使用它当时冻结的包。
            {" "}
            <Button size="small" type="text" onClick={() => navigate(knowledgePacksPath(undefined, preparePath(profileId, interviewId ?? undefined)))}>
              管理岗位知识包
            </Button>
          </small>
          {packsError ? (
            <Alert type="warn" title="岗位知识包列表读取失败">
              无法确认哪些包可选；仍可尝试用服务端默认包生成，服务器受理时会再次校验。
            </Alert>
          ) : null}
        </section>
      ) : null}
    </main>
  );
}
