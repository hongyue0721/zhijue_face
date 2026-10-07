import { Spinner } from "@any-design/anyui/react";
import { Alert } from "./ui";
import { useEffect, useState } from "react";
import type { OperationView } from "../../api";
import { operationStatusText } from "../../presentation";

function ElapsedTime({ createdAt }: { createdAt: string }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const started = Date.parse(createdAt);
  if (!Number.isFinite(started)) return null;
  const seconds = Math.max(0, Math.floor((now - started) / 1000));
  return <span className="operation-elapsed" aria-live="off">已等待 {seconds >= 60 ? `${Math.floor(seconds / 60)} 分 ` : ""}{seconds % 60} 秒</span>;
}

export function OperationStatus({ operation, label }: { operation: OperationView | null; label: string }) {
  if (!operation || operation.status === "succeeded") return null;
  const active = operation.status === "queued" || operation.status === "running";
  const type = active ? "info" : "danger";
  const automatic = active && operation.retry_trigger === "automatic";
  return (
    <Alert type={type} title={`${label} · ${automatic
      ? operation.retry_reason === "transient" ? "正在自动重试网络请求"
        : operation.retry_reason === "correction" ? "正在自动修正输出"
          : "正在自动重试"
      : operationStatusText[operation.status]}`}>
      {active ? (
        <div className="operation-feedback">
          <div className="operation-active">
            <Spinner size="small" />
            <ElapsedTime createdAt={operation.chain_started_at} />
          </div>
          <p>已开始处理。刷新页面也能接着看进度，不用重复提交。</p>
          {automatic ? <p>{operation.retry_reason === "transient"
            ? "上次请求遇到暂时性网络或服务故障，系统正在自动重试。"
            : operation.retry_reason === "correction"
              ? "上次输出未通过校验，系统正在自动修正；仍只使用你确认过的经历。"
              : "系统正在自动重试。"}不用再次提交。</p> : null}
          {operation.kind === "interview.answer" ? <p>回答原文已保存，正在等待分析结果。</p> : null}
          <p className="muted">等待时间不代表进度，完成后页面会自动更新。</p>
        </div>
      ) : null}
      {operation.attempt_limit !== null ? (
        <p>已尝试 {operation.attempts} 次，最多 {operation.attempt_limit} 次
          {operation.status === "queued" ? "；还在排队，尚未开始模型调用。" : "。"}
        </p>
      ) : null}
      {operation.error ? <p>{operation.error.message}</p> : null}
    </Alert>
  );
}
