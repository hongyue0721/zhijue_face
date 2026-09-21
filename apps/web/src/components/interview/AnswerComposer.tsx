import { Alert, Button, Spinner, Tag, Textarea } from "@any-design/anyui/react";
import { useEffect, useState } from "react";
import type { AcceptedAnswerView, QuestionView } from "../../api";

export function AnswerComposer({
  question,
  acceptedAnswer,
  submitting,
  serviceReady,
  pendingRetryText,
  retryReason,
  canRetryAnalysis,
  retryBudgetExhausted,
  onSubmit,
  onResetRetry,
  onRetryAnalysis,
}: {
  question: QuestionView;
  acceptedAnswer: AcceptedAnswerView | null;
  submitting: boolean;
  serviceReady: boolean;
  pendingRetryText: string | null;
  retryReason: "network" | "capacity" | "service" | null;
  canRetryAnalysis: boolean;
  retryBudgetExhausted: boolean;
  onSubmit: (text: string) => void;
  onResetRetry: () => void;
  onRetryAnalysis: () => void;
}) {
  const [text, setText] = useState("");
  const [validation, setValidation] = useState<string | null>(null);

  useEffect(() => {
    setText("");
    setValidation(null);
  }, [question.id]);

  const submit = () => {
    const value = (pendingRetryText ?? text).trim();
    if (!value) {
      setValidation("请填写回答后再提交。");
      return;
    }
    setValidation(null);
    onSubmit(value);
  };

  if (acceptedAnswer) {
    const processing = acceptedAnswer.evaluation_status === "processing";
    const failed = acceptedAnswer.evaluation_status === "failed";
    return (
      <section className="answer-composer accepted-answer" aria-labelledby="accepted-answer-title">
        <div className="answer-state-row">
          <h2 id="accepted-answer-title">已保存的回答</h2>
          <Tag className={`status-tag--${failed ? "danger" : processing ? "warn" : "success"}`}>
            {failed ? "分析失败" : processing ? "分析中" : "分析完成"}
          </Tag>
        </div>
        <p className="saved-answer-text">{acceptedAnswer.raw_text}</p>
        {processing ? <div className="loading-row"><Spinner size="small" />回答已保存，正在分析</div> : null}
        {failed ? (
          <Alert type="danger" title="分析失败，原回答已保留">
            {canRetryAnalysis
              ? "重试只会重新分析这条已保存回答，不会再次提交文本。"
              : retryBudgetExhausted
                ? "该失败操作的重试预算已用完；原回答仍保存在服务端，可跳过本题或提前结束。"
                : "当前没有可恢复的失败操作编号；原回答仍保存在服务端。"}
            {canRetryAnalysis ? (
              <Button type="primary" loading={submitting} disabled={!serviceReady || submitting} onClick={onRetryAnalysis}>
                重试分析
              </Button>
            ) : null}
          </Alert>
        ) : null}
      </section>
    );
  }

  const retry = pendingRetryText !== null && retryReason !== null;
  const value = pendingRetryText ?? text;
  const retryCopy = retryReason === "capacity"
    ? {
        title: "当前处理队列已满",
        detail: "服务端没有受理本次命令；稍后重试会复用同一组请求标识。",
      }
    : retryReason === "service"
      ? {
          title: "服务依赖暂未就绪",
          detail: "服务端没有受理本次命令；依赖恢复后可使用同一请求重试。",
        }
      : {
          title: "上次请求未取得明确响应",
          detail: "使用原请求重试会复用同一组请求标识。",
        };
  return (
    <section className="answer-composer" aria-labelledby="answer-title">
      <div className="answer-state-row">
        <h2 id="answer-title">你的回答</h2>
        <span>{value.length} / 6000</span>
      </div>
      <label className="field-label">
        <span className="visually-hidden">面试回答</span>
        <Textarea
          modelValue={value}
          onUpdateModelValue={setText}
          placeholder="请写下你的真实做法、排查过程和验证依据。"
          rows={5}
          maxlength={6000}
          readonly={retry}
          disabled={submitting || !serviceReady}
        />
      </label>
      {retry ? (
        <Alert type="warn" title={retryCopy.title}>
          {retryCopy.detail}
        </Alert>
      ) : null}
      <div className="field-footer">
        {retry ? (
          <Button type="secondary" disabled={submitting} onClick={onResetRetry}>修改回答</Button>
        ) : <span />}
        <Button type="primary" size="large" loading={submitting} disabled={submitting || !serviceReady} onClick={submit}>
          {retry ? "使用原请求重试" : "提交回答"}
        </Button>
      </div>
      {validation ? <p className="field-error" role="alert">{validation}</p> : null}
      <p className="privacy-note">回答正文仅发送到业务后端，不进入 URL、浏览器日志或分析提示外的展示区域。</p>
    </section>
  );
}
