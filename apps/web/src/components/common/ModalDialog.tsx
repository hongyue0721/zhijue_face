import { useEffect, useRef, type KeyboardEvent, type MouseEvent, type ReactNode, type SyntheticEvent } from "react";

interface FocusRef {
  readonly current: HTMLElement | null;
}

export function ModalDialog({
  isOpen,
  busy = false,
  titleId,
  title,
  returnFocusElement,
  initialFocusRef,
  onClose,
  children,
  footer,
}: {
  isOpen: boolean;
  busy?: boolean;
  titleId: string;
  eyebrow: string;
  title: string;
  returnFocusElement?: HTMLElement | null;
  initialFocusRef?: FocusRef;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const previousActiveElement = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    previousActiveElement.current = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) {
      dialog.showModal();
      const fallback = dialog.querySelector<HTMLElement>(
        "button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
      );
      (initialFocusRef?.current ?? fallback)?.focus();
    }
    return () => {
      if (dialogRef.current?.open) dialogRef.current.close();
      (returnFocusElement ?? previousActiveElement.current)?.focus?.();
    };
  }, [initialFocusRef, isOpen, returnFocusElement]);

  if (!isOpen) return null;

  const closeFromBackdrop = (event: MouseEvent<HTMLDialogElement>) => {
    if (event.target === dialogRef.current && !busy) onClose();
  };
  const closeFromEscape = (event: SyntheticEvent<HTMLDialogElement>) => {
    event.preventDefault();
    if (!busy) onClose();
  };
  const keepFocusInside = (event: KeyboardEvent<HTMLDialogElement>) => {
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(
        "button:not([disabled]), [role='button']:not([aria-disabled='true']), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), summary, a[href], [tabindex]:not([tabindex='-1'])",
      ) ?? [],
    ).filter((element) => element.getClientRects().length > 0);
    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <dialog
      ref={dialogRef}
      className="fact-modal-dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onClick={closeFromBackdrop}
      onCancel={closeFromEscape}
      onKeyDown={keepFocusInside}
    >
      <div className="fact-modal-card" onClick={(event) => event.stopPropagation()}>
        <header className="fact-modal-header">
          <div>

            <h2 id={titleId}>{title}</h2>
          </div>
          <button
            type="button"
            className="fact-modal-close-btn"
            aria-label="关闭对话框"
            disabled={busy}
            onClick={onClose}
          >
            ✕
          </button>
        </header>
        <div className="fact-modal-body">{children}</div>
        {footer ? <footer className="fact-modal-footer">{footer}</footer> : null}
      </div>
    </dialog>
  );
}
