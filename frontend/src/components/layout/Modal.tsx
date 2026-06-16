import { useEffect, useId, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

export function Modal({ children, description, icon, onClose, open, size = "md", title }: ModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (open && !dialog.open) {
      dialog.showModal();
      return;
    }

    if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      aria-describedby={description ? descriptionId : undefined}
      aria-labelledby={titleId}
      className={`sv-dialog sv-dialog-${size}`}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onMouseDown={(event) => {
        if (event.target === dialogRef.current) onClose();
      }}
    >
      <div className="sv-dialog-panel" onMouseDown={(event) => event.stopPropagation()}>
        <header className="sv-dialog-header">
          <div className="flex min-w-0 items-start gap-3">
            {icon ? <span className="sv-dialog-icon">{icon}</span> : null}
            <div className="min-w-0">
              <h2 id={titleId} className="sv-section-title">
                {title}
              </h2>
              {description ? (
                <p id={descriptionId} className="mt-1 text-body-md text-on-surface-variant">
                  {description}
                </p>
              ) : null}
            </div>
          </div>
          <button type="button" onClick={onClose} className="faham-icon-button" aria-label="Close dialog">
            <X size={17} />
          </button>
        </header>
        <div className="sv-dialog-body">{children}</div>
      </div>
    </dialog>
  );
}

type ModalProps = {
  children: ReactNode;
  description?: string;
  icon?: ReactNode;
  onClose: () => void;
  open: boolean;
  size?: "sm" | "md" | "lg";
  title: string;
};
