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
  const dialogContentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    let disposed = false;
    setBlocks([]);
    setLoading(true);
    setError(null);

    const loadAllBlocks = async () => {
      const allBlocks: DocumentBlockView[] = [];
      const seenCursors = new Set<string>();
      let cursor: string | undefined;
      do {
        const page = await api.getDocumentBlocks(
          document.id,
          cursor,
          100,
          controller.signal,
        );
        if (disposed) return;
        allBlocks.push(...page.items);
        if (page.next_cursor === null) break;
        if (seenCursors.has(page.next_cursor)) {
          throw new Error("解析文本分页没有继续前进，已停止读取以避免重复内容。");
        }
        seenCursors.add(page.next_cursor);
        cursor = page.next_cursor;
      } while (!disposed);
      if (!disposed) setBlocks(allBlocks);
    };

    void loadAllBlocks()
      .catch((nextError) => {
        if (
          !disposed
          && !(nextError instanceof DOMException && nextError.name === "AbortError")
        ) {
          setError(nextError);
        }
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });

    const drawer = dialogContentRef.current?.closest<HTMLElement>(".a-drawer");
    drawer?.setAttribute("aria-modal", "true");
    drawer?.setAttribute("aria-labelledby", "document-drawer-title");
    closeRef.current?.querySelector<HTMLElement>("button, [role='button']")?.focus();
    return () => {
      disposed = true;
      controller.abort();
      triggerRef.current?.querySelector<HTMLElement>("button, [role='button']")?.focus();
    };
  }, [document.id, open]);

  const handleDialogKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      return;
    }
    if (event.key !== "Tab") return;
    const dialog = dialogContentRef.current;
    if (!dialog) return;
    const focusable = Array.from(
      dialog.querySelectorAll<HTMLElement>(
        "button:not([disabled]), [role='button']:not([aria-disabled='true']), "
        + "input:not([disabled]), textarea:not([disabled]), "
        + "summary, a[href], [tabindex]:not([tabindex='-1'])",
      ),
    ).filter((element) => element.getClientRects().length > 0);
    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && window.document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && window.document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

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
          <div ref={dialogContentRef} className="drawer-content" onKeyDown={handleDialogKeyDown}>
            <div className="drawer-heading">
              <div>
                <p className="eyebrow">解析结果</p>
                <h2 id="document-drawer-title">{document.filename_display}</h2>
              </div>
              <div ref={closeRef} tabIndex={-1}>
                <Button size="small" type="secondary" onClick={() => setOpen(false)}>关闭</Button>
              </div>
            </div>
            {loading ? <div className="loading-row"><Spinner />正在读取文本块</div> : null}
            <ErrorNotice error={error} />
            {!loading && !error && pages.length === 0 ? (
              <p className="empty-state">这份文件没有解析出可展示的文字。</p>
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
