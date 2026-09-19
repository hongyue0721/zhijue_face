import { Button, Collapse } from "@any-design/anyui/react";
import { useState } from "react";
import type { InterviewView } from "../../api";

export function TechnicalDetails({ interview }: { interview: InterviewView }) {
  const [visible, setVisible] = useState(false);
  return (
    <section className="technical-details">
      <Button size="small" type="secondary" onClick={() => setVisible((current) => !current)}>
        {visible ? "收起技术明细" : "查看技术明细"}
      </Button>
      <Collapse visible={visible}>
        <div className="technical-details-body">
          <p>Planner：<code>{interview.root_plan.planner_version}</code></p>
          <p>Seed Bank：<code>{interview.root_plan.seed_bank_version}</code></p>
          {interview.root_plan.slots.map((slot, index) => (
            <div key={slot.slot_id} className="technical-slot">
              <strong>Slot {index + 1}</strong>
              <span>competency_id: <code>{slot.competency}</code></span>
              <span>priority: {slot.priority}</span>
              <span>reason_code: <code>{slot.reason_code}</code></span>
              <span>seed_id: <code>{slot.seed_id ?? "null"}</code></span>
            </div>
          ))}
          {interview.limitations.length > 0 ? (
            <ul>{interview.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
          ) : null}
        </div>
      </Collapse>
    </section>
  );
}
