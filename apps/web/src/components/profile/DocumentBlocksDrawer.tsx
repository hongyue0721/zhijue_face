import { Button, Drawer, Spinner } from "@any-design/anyui/react";
import { useEffect, useMemo, useState } from "react";
import { api, type DocumentBlockView, type DocumentView } from "../../api";
import { ErrorNotice } from "../common/ErrorNotice";

export function DocumentBlocksDrawer({ document }: { document: DocumentView }) {
  const [open, setOpen] = useState(false);
  const [blocks, setBlocks] = useState<DocumentBlockView[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

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
    return () => controller.abort();
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
      <Button size="small" type="secondary" onClick={() => setOpen(true)}>
        查看解析文本
      </Button>
      <Drawer
        modelValue={open}
        onUpdateModelValue={setOpen}
        position="right"
        width="min(560px, 92vw)"
      >
        <div className="drawer-content">
          <div className="drawer-heading">
            <div>
              <p className="eyebrow">解析结果</p>
              <h2>{document.filename_display}</h2>
            </div>
            <Button size="small" type="secondary" onClick={() => setOpen(false)}>关闭</Button>
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
    </>
  );
}
