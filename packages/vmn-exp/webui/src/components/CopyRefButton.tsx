import { useCopied } from "./ui";
import { Icon } from "./shell/icons";
import "./CopyRefButton.css";

/** A small icon button copying a run's verstr (or any ref) next to the
 *  `@N name` that stands for it. */
export default function CopyRefButton({ text }: { text: string }) {
  const [copied, copy] = useCopied();
  return (
    <button
      type="button" className="link copy-ref" aria-label={`copy ${text}`}
      title={copied ?? `copy ${text}`} onClick={() => copy(text)}
    >
      <Icon name={copied === "copied" ? "check" : "copy"} size={12} />
    </button>
  );
}
