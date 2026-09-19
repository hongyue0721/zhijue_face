import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";

import {
  ApiError,
  api,
  type CoverageEntryView,
  type InterviewSlotView,
  type InterviewView,
  type OperationView,
  type ProfileView,
} from "./api";

type Phase = "idle" | "loading" | "confirming" | "planning" | "error";

const colors = {
  ink: "#17202a",
  muted: "#667085",
  border: "#d0d5dd",
  panel: "#ffffff",
  canvas: "#f5f7fa",
  primary: "#2457d6",
  warning: "#9a6700",
  warningBg: "#fff8c5",
  success: "#176b3a",
  successBg: "#e8f5ec",
  unknown: "#6941c6",
  unknownBg: "#f4f0ff",
};

const panelStyle: CSSProperties = {
  background: colors.panel,
  border: `1px solid ${colors.border}`,
  borderRadius: 12,
  padding: 20,
};

function sleep(ms: number): Promise<void> {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, ms);
  return promise;
}

async function waitForOperation(
  operationId: string,
  onUpdate: (operation: OperationView) => void,
): Promise<OperationView> {
  const source = new EventSource(api.eventsUrl(operationId));
  source.addEventListener("operation.completed", () => source.close());
  source.addEventListener("operation.failed", () => source.close());
  try {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const operation = await api.getOperation(operationId);
      onUpdate(operation);
      if (["succeeded", "failed", "interrupted", "canceled"].includes(operation.status)) {
        return operation;
      }
      await sleep(500);
    }
  } finally {
    source.close();
  }
  throw new Error("操作超时；没有收到服务端终态。请刷新后按操作 ID 恢复。");
}

function Badge({ children, tone = "neutral" }: { children: string; tone?: string }) {
  const palette =
    tone === "warning"
      ? [colors.warning, colors.warningBg]
      : tone === "success"
        ? [colors.success, colors.successBg]
        : tone === "unknown"
          ? [colors.unknown, colors.unknownBg]
          : [colors.ink, colors.canvas];
  return (
    <span
      style={{
        color: palette[0],
        background: palette[1],
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 700,
        padding: "3px 8px",
      }}
    >
      {children}
    </span>
  );
}

function SourceCard({ interview }: { interview: InterviewView }) {
  const source = interview.jd_source;
  return (
    <section style={panelStyle} data-testid="jd-source">
      <h2 style={{ marginTop: 0 }}>岗位来源</h2>
      <p>
        <Badge tone={source.is_synthetic ? "warning" : "success"}>
          {source.is_synthetic ? "合成演示配置" : source.source_type}
        </Badge>
      </p>
      {source.is_synthetic && (
        <p style={{ color: colors.warning, fontWeight: 700 }}>
          不是企业真实招聘公告，仅用于验证面试规划链路。
        </p>
      )}
      <dl style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: "8px 16px" }}>
        <dt>来源名称</dt>
        <dd style={{ margin: 0 }}>{source.source_name}</dd>
        <dt>内容哈希</dt>
        <dd style={{ margin: 0, fontFamily: "monospace" }}>{source.content_hash}</dd>
        <dt>要求数量</dt>
        <dd style={{ margin: 0 }}>{interview.jd_requirements.length}</dd>
      </dl>
    </section>
  );
}

function CoverageRow({ entry }: { entry: CoverageEntryView }) {
  const tone = entry.status === "unknown" ? "unknown" : "neutral";
  return (
    <li style={{ borderTop: `1px solid ${colors.border}`, padding: "14px 0" }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <strong>{entry.competency_id}</strong>
        <Badge tone={tone}>{entry.status}</Badge>
        <Badge>{entry.relation}</Badge>
      </div>
      <p style={{ color: colors.muted, marginBottom: 0 }}>{entry.note}</p>
      <small>
        直接证据 {entry.evidence_ids.length} 条 · 相关上下文 {entry.related_context_ids.length} 条
      </small>
    </li>
  );
}

function CoveragePanel({ entries }: { entries: CoverageEntryView[] }) {
  return (
    <section style={panelStyle} data-testid="coverage-map">
      <h2 style={{ marginTop: 0 }}>能力覆盖图</h2>
      <p style={{ color: colors.muted }}>
        unknown 表示材料未体现，不等于不会；related_context 不会被冒充为直接证据。
      </p>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {entries.map((entry) => (
          <CoverageRow key={entry.competency_id} entry={entry} />
        ))}
      </ul>
    </section>
  );
}

function SlotCard({ slot, index }: { slot: InterviewSlotView; index: number }) {
  return (
    <article
      style={{ ...panelStyle, borderLeft: `5px solid ${colors.primary}` }}
      data-testid={`plan-slot-${index + 1}`}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
        <div>
          <small style={{ color: colors.muted }}>验证槽位 {index + 1}</small>
          <h3 style={{ margin: "4px 0 8px" }}>{slot.competency}</h3>
        </div>
        <strong>优先级 {slot.priority}</strong>
      </div>
      <p>{slot.verification_goal}</p>
      <p style={{ color: colors.muted }}>{slot.structured_reason}</p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <Badge tone={slot.current_verification_status === "unknown" ? "unknown" : "neutral"}>
          {slot.current_verification_status}
        </Badge>
        <Badge>{slot.reason_code}</Badge>
        <Badge>{slot.difficulty}</Badge>
      </div>
    </article>
  );
}

function PlanPanel({ interview }: { interview: InterviewView }) {
  return (
    <section data-testid="interview-plan">
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ marginBottom: 4 }}>五题验证计划</h2>
        <p style={{ color: colors.muted, marginTop: 0 }}>
          当前展示服务端冻结的五题验证目标；开始操作后由后端绑定 approved Seed 或明确的非技术回退题。
        </p>
      </div>
      <div style={{ display: "grid", gap: 12 }}>
        {interview.root_plan.slots.map((slot, index) => (
          <SlotCard key={slot.slot_id} slot={slot} index={index} />
        ))}
      </div>
    </section>
  );
}

function QuestionReadiness({ interview }: { interview: InterviewView }) {
  return (
    <section style={panelStyle} data-testid="question-readiness">
      <h2 style={{ marginTop: 0 }}>当前题</h2>
      {interview.current_question ? (
        <p>题目已由后端准备；答题交互将在前端设计评审后接入。</p>
      ) : (
        <>
          <p>
            <Badge tone="warning">前端待设计</Badge>
          </p>
          <p style={{ fontWeight: 700 }}>当前计划尚未从本工作台启动。</p>
          <p style={{ color: colors.muted }}>
            六条 Seed 已 approved，后端 start/answer/retry 契约已就绪；本页面仍停在只读计划阶段，不把未设计的答题交互伪装成可用功能。
          </p>
        </>
      )}
    </section>
  );
}

interface ProfilePanelProps {
  profile: ProfileView;
  factText: string;
  phase: Phase;
  onFactText: (value: string) => void;
  onSubmitFact: () => void;
  onConfirm: (claimId: string, action: "accept" | "reject") => void;
  onPlan: () => void;
}

function ProfilePanel(props: ProfilePanelProps) {
  const { profile, factText, phase, onFactText, onSubmitFact, onConfirm, onPlan } = props;
  return (
    <section style={panelStyle} data-testid="profile-panel">
      <h2 data-testid="profile-summary">
        {profile.display_name} · revision {profile.revision}
      </h2>
      <p>
        快照：{profile.latest_snapshot_id ?? "尚未生成"} · 已确认 {profile.confirmed_claims.length} 条 · 待确认{" "}
        {profile.proposed_claims.length} 条
      </p>
      <label htmlFor="fact-text"><strong>补充一条待确认事实</strong></label>
      <textarea
        id="fact-text"
        aria-label="fact-text"
        value={factText}
        rows={2}
        style={{ boxSizing: "border-box", margin: "8px 0", padding: 10, width: "100%" }}
        onChange={(event) => onFactText(event.target.value)}
      />
      <button onClick={onSubmitFact} disabled={phase !== "idle"}>提交为待确认声明</button>
      <h3>材料中声明</h3>
      <ul data-testid="proposed">
        {profile.proposed_claims.map((claim) => (
          <li key={claim.id} style={{ marginBottom: 10 }}>
            {claim.text}{" "}
            <button onClick={() => onConfirm(claim.id, "accept")}>确认</button>{" "}
            <button onClick={() => onConfirm(claim.id, "reject")}>撤回</button>
          </li>
        ))}
        {profile.proposed_claims.length === 0 && <li>没有待确认声明</li>}
      </ul>
      <button
        data-testid="create-plan"
        onClick={onPlan}
        disabled={phase !== "idle" || profile.latest_snapshot_id === null}
        style={{ background: colors.primary, color: "white", padding: "10px 16px" }}
      >
        生成五题验证计划
      </button>
    </section>
  );
}

export default function App() {
  const query = useMemo(() => new URLSearchParams(window.location.search), []);
  const [profile, setProfile] = useState<ProfileView | null>(null);
  const [interview, setInterview] = useState<InterviewView | null>(null);
  const [factText, setFactText] = useState("我在项目里用 FreeRTOS Queue 传递采样数据");
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState("");
  const [operation, setOperation] = useState<OperationView | null>(null);
  const [readiness, setReadiness] = useState("检查中");

  const report = useCallback((error: unknown) => {
    setMessage(error instanceof Error ? error.message : "未知错误");
    setPhase("error");
  }, []);

  useEffect(() => {
    api.ready().then(
      (info) => setReadiness(`${String(info.run_mode)} / ${String(info.knowledge)}`),
      (error) => setReadiness(`未就绪（${error instanceof ApiError ? error.code : "错误"}）`),
    );
  }, []);

  useEffect(() => {
    const profileId = query.get("profile");
    if (!profileId) return;
    setPhase("loading");
    api.getProfile(profileId).then((value) => {
      setProfile(value);
      setPhase("idle");
    }, report);
  }, [query, report]);

  useEffect(() => {
    const interviewId = query.get("interview");
    if (!interviewId) return;
    api.getInterview(interviewId).then(setInterview, report);
  }, [query, report]);

  const replaceQuery = (profileId: string, interviewId?: string) => {
    const params = new URLSearchParams({ profile: profileId });
    if (interviewId) params.set("interview", interviewId);
    window.history.replaceState(null, "", `?${params}`);
  };

  const createProfile = async () => {
    setPhase("loading");
    try {
      const value = await api.createProfile(`演示档案 ${new Date().toLocaleTimeString()}`);
      replaceQuery(value.id);
      setProfile(value);
      setMessage("");
      setPhase("idle");
    } catch (error) {
      report(error);
    }
  };

  const submitFacts = async () => {
    if (!profile) return;
    setPhase("loading");
    try {
      setProfile(await api.addFacts(profile.id, profile.revision, [factText]));
      setMessage("");
      setPhase("idle");
    } catch (error) {
      report(error);
    }
  };

  const confirmClaim = async (claimId: string, action: "accept" | "reject") => {
    if (!profile) return;
    setPhase("confirming");
    try {
      const accepted = await api.confirm(profile.id, profile.revision, [{ claim_id: claimId, action }]);
      await waitForOperation(accepted.operation_id, setOperation);
      setProfile(await api.getProfile(profile.id));
      setMessage("");
      setPhase("idle");
    } catch (error) {
      report(error);
    }
  };

  const createPlan = async () => {
    if (!profile) return;
    setPhase("planning");
    try {
      const accepted = await api.createInterview(profile.id, profile.revision);
      const completed = await waitForOperation(accepted.operation_id, setOperation);
      if (completed.status !== "succeeded") {
        throw new Error(completed.error?.message ?? `计划操作终态：${completed.status}`);
      }
      const interviewId = String(completed.result?.interview_id ?? completed.resource_id);
      const value = await api.getInterview(interviewId);
      replaceQuery(profile.id, interviewId);
      setInterview(value);
      setMessage("");
      setPhase("idle");
    } catch (error) {
      report(error);
    }
  };

  return (
    <main style={{ background: colors.canvas, color: colors.ink, minHeight: "100vh", padding: "32px 20px" }}>
      <div style={{ margin: "0 auto", maxWidth: 1120 }}>
        <header style={{ marginBottom: 24 }}>
          <p style={{ color: colors.primary, fontWeight: 800, letterSpacing: 1 }}>ZHIJUE / M2-03</p>
          <h1 style={{ margin: "4px 0" }}>面试准备工作台</h1>
          <p data-testid="readiness" style={{ color: colors.muted }}>运行模式 / Knowledge：{readiness}</p>
        </header>

        {!profile && !interview && (
          <section style={panelStyle}>
            <h2>从资料确认开始</h2>
            <p>也可使用带 profile 与 interview 参数的地址恢复已有准备态。</p>
            <button onClick={createProfile} disabled={phase === "loading"}>新建演示档案</button>
          </section>
        )}

        {profile && (
          <ProfilePanel
            profile={profile}
            factText={factText}
            phase={phase}
            onFactText={setFactText}
            onSubmitFact={submitFacts}
            onConfirm={confirmClaim}
            onPlan={createPlan}
          />
        )}

        {interview && (
          <div style={{ display: "grid", gap: 20, marginTop: 20 }}>
            <SourceCard interview={interview} />
            <CoveragePanel entries={interview.coverage_map} />
            <PlanPanel interview={interview} />
            <QuestionReadiness interview={interview} />
          </div>
        )}

        {operation && (
          <p data-testid="operation" style={{ color: colors.muted }}>
            操作 {operation.id}：{operation.status}
            {operation.error ? ` · ${operation.error.code}：${operation.error.message}` : ""}
          </p>
        )}
        {phase === "error" && <p data-testid="error" style={{ color: "#b42318" }}>{message}</p>}
        {["loading", "confirming", "planning"].includes(phase) && <p>处理中…</p>}
      </div>
    </main>
  );
}
