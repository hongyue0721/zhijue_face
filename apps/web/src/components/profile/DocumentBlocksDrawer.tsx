import { Button, Drawer, Spinner } from "@any-design/anyui/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type DocumentBlockView, type DocumentView } from "../../api";
import { ErrorNotice } from "../common/ErrorNotice";

export function DocumentBlocksDrawer({ document }: { document: DocumentView }) {
  const [open, setOpen] = useState(false);
  const [blocks, setBlocks] = useState<DocumentBlockView[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const triggerRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api.getDocumentBlocks(document.id, undefined, 100, controller.signal)
      .then((page) => setBlocks(page.items))
      .catch((nextError) => {
        if (!(nextError instanceof DOMException && nextError.name === "AbortError")) setError(nextError);
      })
      .finally(() => setLoading(false));
    // anyui Drawer 不处理键盘：对话框惯例要求 ESC 可关闭，由本组件接管。
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    // 打开后焦点进入对话框；关闭后还给触发按钮，键盘用户不落空。
    closeRef.current?.focus();
    return () => {
      controller.abort();
      window.removeEventListener("keydown", onKey);
      triggerRef.current?.focus();
    };
  }, [document.id, open]);

  const pages = useMemo(() => {
    const grouped = new Map<number | string, DocumentBlockView[]>();
    for (const block of blocks) {
      const page = block.page_number ?? "未标页码";
      grouped.set(page, [...(grouped.get(page) ?? []), block]);
    }
    return [...grouped.entries()];
  }, [blocks]);

  return (
    <>
      <div ref={triggerRef} tabIndex={-1} className="drawer-trigger">
        <Button size="small" type="secondary" onClick={() => setOpen(true)}>
          查看解析文本
        </Button>
      </div>
      {/* 条件挂载：anyui 的 leave 过渡在快速开关时会把遮罩滞留在页面上
          （面板已消失但全屏 mask 吞点击）。卸载整个 Drawer 换取确定性状态。 */}
      {open ? (
        <Drawer modelValue onUpdateModelValue={(next: boolean) => setOpen(next)} position="right" width="min(560px, 92vw)">
          <div className="drawer-content">
            <div className="drawer-heading">
              <div>
                <p className="eyebrow">解析结果</p>
                <h2>{document.filename_display}</h2>
              </div>
              <div ref={closeRef} tabIndex={-1}>
                <Button size="small" type="secondary" onClick={() => setOpen(false)}>关闭</Button>
              </div>
            </div>
            {loading ? <div className="loading-row"><Spinner />正在读取文本块</div> : null}
            <ErrorNotice error={error} />
            {!loading && !error && pages.length === 0 ? (
              <p className="empty-state">服务端没有返回可展示的文本块。</p>
            ) : null}
            {pages.map(([page, pageBlocks]) => (
              <section key={String(page)} className="document-page">
                <h3>{typeof page === "number" ? `第 ${page} 页` : page}</h3>
                {pageBlocks.map((block) => <p key={block.id}>{block.text}</p>)}
              </section>
            ))}
          </div>
        </Drawer>
      ) : null}
    </>
  );
}
