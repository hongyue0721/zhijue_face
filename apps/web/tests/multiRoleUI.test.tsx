// @vitest-environment happy-dom
import { act, type ReactNode, type MouseEventHandler } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { api, type InterviewSlotView, type InterviewView, type KnowledgePackItem, type KnowledgePackList, type QuestionView } from "../src/api";
import { EvidencePanel } from "../src/components/interview/EvidencePanel";
import { InterviewPlan } from "../src/components/prepare/InterviewPlan";
import { PackSelector } from "../src/components/prepare/PackSelector";
import { KnowledgePacksPage } from "../src/pages/KnowledgePacksPage";
import { frozenCompetencyLabels } from "../src/presentation";

vi.mock("@any-design/anyui/react", () => ({
  Tag: ({ children, className }: { children?: ReactNode; className?: string }) => <span className={className}>{children}</span>,
  Button: ({ children, disabled, onClick }: { children?: ReactNode; disabled?: boolean; onClick?: MouseEventHandler<HTMLButtonElement> }) => <button disabled={disabled} onClick={onClick}>{children}</button>,
  Alert: ({ children, title }: { children?: ReactNode; title?: string }) => <section role="alert"><h2>{title}</h2>{children}</section>,
  Spinner: () => <span role="status" />,
}));

const capability = { competency_id: "python.mutable", label: "由服务端提供的能力名称" };
const frozenPack: InterviewView["knowledge_pack"] = {
  binding: "frozen", pack_release_id: "kpr_0123456789abcdef", name: "测试岗位包",
  profile_version: "7.8.9", profile_digest: "sha256:frozen-rules", capabilities: [capability],
};
const slot: InterviewSlotView = {
  schema_version: "1.0.0", slot_id: "slot", competency: capability.competency_id,
  jd_requirement_ids: [], candidate_evidence_ids: [], current_verification_status: "unknown",
  verification_goal: "核对边界", priority: 1, difficulty: "easy", reason_code: "test",
  structured_reason: "test", seed_id: null,
};
const interview: InterviewView = {
  id: "interview", revision: 1, status: "active", run_mode: "fixture", profile_id: "profile",
  profile_snapshot_id: "snapshot", jd_text: null, jd_requirements: [], jd_source: {
    id: "jd", source_type: "synthetic_demo_jd", source_name: "合成测试岗位", content_hash: "hash",
    imported_at: "2026-10-06", version: 1, status: "ready", is_synthetic: true,
    source_url: null, retrieved_at: null, derived: false, upstream_source_name: null,
    upstream_url: null, upstream_retrieved_at: null, upstream_content_hash: null,
    derived_artifact_path: null, derived_content_hash: null, transformation_note: null,
  },
  root_plan: { slots: [slot], planner_version: "test", seed_bank_version: "test" },
  coverage_map: [], current_question: null, root_results: [], active_operation_id: null,
  stop_requested: false, report_id: null, limitations: [], knowledge_pack: frozenPack,
};
const question: QuestionView = {
  id: "question", root_id: "question", kind: "main", seed_id: null, wording: "测试问题",
  basis: { competency_id: capability.competency_id }, order_index: 0, accepted_answer: null,
};
const item: KnowledgePackItem = {
  pack_release_id: frozenPack.pack_release_id!, pack_id: "test-pack", name: frozenPack.name!, version: "1.0.0",
  content_digest: "sha256:pack", format_version: "1.0.0", competency_profile_id: "test-profile",
  profile_version: frozenPack.profile_version!, profile_digest: frozenPack.profile_digest!, rules_reviewed: false,
  scope_summary: "test", unsupported_scope: "test", validation_status: "passed", review_status: "approved",
  selectable: false, blocked_reasons: [], seed_count: 1, approved_seed_count: 1, source_count: 1,
  capabilities: [{ ...capability, technical_seed_available: true }], review_summary: null,
};
const packs: KnowledgePackList = {
  items: [item], default_pack_release_id: item.pack_release_id,
  import_limits: { max_upload_bytes: 100, max_extracted_total_bytes: 100, max_single_file_bytes: 100, max_entries: 10, max_path_depth: 5 },
};

function markup(node: ReactNode): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(node);
  return host;
}

describe("server-defined role capabilities", () => {
  it("renders plan names from the frozen profile and preserves unknown identifiers", () => {
    const plan = markup(<InterviewPlan slots={[slot]} requirements={[]} competencyLabels={frozenCompetencyLabels(frozenPack)} />);
    expect(plan.querySelector(".slot-body strong")?.textContent).toBe(capability.label);
    const historical = markup(<InterviewPlan slots={[slot]} requirements={[]} competencyLabels={frozenCompetencyLabels({ ...frozenPack, binding: "frozen_unavailable" })} />);
    expect(historical.querySelector(".slot-body strong")?.textContent).toBe(capability.competency_id);
  });

  it("prefers the question basis label, otherwise uses only the frozen profile", () => {
    const fromPack = markup(<EvidencePanel interview={interview} question={question} />);
    expect(fromPack.textContent).toContain(capability.label);
    const basisLabel = "这道题的冻结能力名称";
    const fromBasis = markup(<EvidencePanel interview={interview} question={{ ...question, basis: { ...question.basis, competency_label: basisLabel } }} />);
    expect(fromBasis.textContent).toContain(basisLabel);
    expect(fromBasis.textContent).not.toContain(capability.label);
    const historical = markup(<EvidencePanel interview={{ ...interview, knowledge_pack: { ...frozenPack, binding: "legacy_unresolved", capabilities: [] } }} question={question} />);
    expect(historical.textContent).toContain(capability.competency_id);
    expect(historical.textContent).not.toContain(capability.label);
  });

  it("shows selected pack capabilities and rule identity without making a seed-approved pack selectable", () => {
    const selector = markup(<PackSelector packs={packs} packsError={null} selectedPackId={null} disabled={false} onSelect={vi.fn()} onManage={vi.fn()} />);
    expect(selector.textContent).toContain(capability.label);
    expect(selector.textContent).toContain(item.profile_version);
    expect(selector.textContent).toContain(item.profile_digest);
    expect(selector.querySelectorAll("option")).toHaveLength(1);
    const loading = markup(<PackSelector packs={null} packsError={null} selectedPackId={item.pack_release_id} disabled={false} onSelect={vi.fn()} onManage={vi.fn()} />);
    expect(loading.querySelector("details")).toBeNull();
    expect(loading.textContent).not.toContain(capability.label);
  });

  it("renders the Python package detail using backend capabilities and independent rule-review facts", async () => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    sessionStorage.clear();
    const listRequest = vi.spyOn(api, "listKnowledgePacks").mockResolvedValue(packs);
    const detailRequest = vi.spyOn(api, "getKnowledgePack").mockResolvedValue({
      ...item, sources: [], validation_checks: [], limitations_note: "test",
    });
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    try {
      await act(async () => root.render(<KnowledgePacksPage releaseId={item.pack_release_id} returnTo="/start" navigate={vi.fn()} />));
      expect(host.querySelector(".pack-capability-list li span")?.textContent).toBe(capability.label);
      expect(host.querySelector(".pack-scope")?.textContent).toContain(item.profile_version);
      expect(host.querySelector(".pack-scope")?.textContent).toContain(item.profile_digest);
      expect(host.querySelector(".pack-list-tags .status-tag--warn")).not.toBeNull();
      expect(host.querySelector<HTMLButtonElement>(".pack-detail-actions button")?.disabled).toBe(true);
    } finally {
      await act(async () => root.unmount());
      host.remove();
      listRequest.mockRestore();
      detailRequest.mockRestore();
      vi.unstubAllGlobals();
    }
  });
});
