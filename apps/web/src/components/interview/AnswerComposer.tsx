import { Alert, Button, Spinner, Textarea } from "@any-design/anyui/react";
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
  const [text, setText] = useState(pendingRetryText ?? "");
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

  // “修改回答”清除重试暂存前，先把原文同步回编辑器；否则用户刚改的
  // 内容会被空的重试文本顶掉（编辑丢字）。
  const resetRetry = () => {
    if (pendingRetryText !== null) setText(pendingRetryText);
    onResetRetry();
  };

  if (acceptedAnswer) {
    const processing = acceptedAnswer.evaluation_status === "processing";
    const failed = acceptedAnswer.evaluation_status === "failed";
    return (
      <section className="answer-composer accepted-answer" aria-labelledby="accepted-answer-title">
        <div className="answer-state-row">
          <h2 id="accepted-answer-title">已保存的回答</h2>
        </div>
        <p className="saved-answer-text">{acceptedAnswer.raw_text}</p>
        {processing ? <div className="loading-row"><Spinner size="small" />回答已保存，正在分析</div> : null}
        {failed ? (
          <Alert type="danger" title="回答分析没有完成">
            {canRetryAnalysis
              ? "你的回答已经保存。可以重新分析这条回答，不会重复提交文本。"
              : retryBudgetExhausted
                ? "你的回答已经保存，但本次分析已达到重试上限。你可以跳过本题或提前结束面试。"
                : "你的回答已经保存，但这次失败无法直接恢复。你可以跳过本题或提前结束面试。"}
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
  const showCharacterCount = value.length >= 4800;
  const retryCopy = retryReason === "capacity"
    ? {
        title: "当前处理排队已满",
        detail: "这次回答还没有发送成功。稍等片刻再点重试即可，内容不会重复提交。",
      }
    : retryReason === "service"
      ? {
          title: "服务暂未就绪",
          detail: "这次回答还没有发送成功。等服务恢复后点重试即可，内容不会重复提交。",
        }
      : {
          title: "上次提交未确认成功",
          detail: "点重试会原样重新发送这条回答，不会产生第二份。",
        };
  return (
    <section className="answer-composer" aria-labelledby="answer-title">
      <div className="answer-state-row">
        <h2 id="answer-title">你的回答</h2>
        {showCharacterCount ? <span>{value.length} / 6000</span> : null}
      </div>
      <label className="field-label">
        <span className="visually-hidden">面试回答</span>
        <Textarea
          modelValue={value}
          onUpdateModelValue={setText}
          placeholder="写下你的真实做法、排查过程和验证依据；不确定的部分可以直接说明。"
          rows={8}
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
          <Button type="secondary" disabled={submitting} onClick={resetRetry}>修改回答</Button>
        ) : <span />}
        <Button type="primary" size="large" loading={submitting} disabled={submitting || !serviceReady} onClick={submit}>
          {retry ? "重新提交" : "提交回答"}
        </Button>
      </div>
      {validation ? <p className="field-error" role="alert">{validation}</p> : null}
    </section>
  );
}
