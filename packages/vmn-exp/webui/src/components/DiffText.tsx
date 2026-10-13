/** A unified diff as text, one row per line, classed by its role (file
 *  header, hunk, added, removed) — the code tab's and the run page's view. */
function lineClass(line: string): string {
  if (line.startsWith("+") && !line.startsWith("+++")) return "add";
  if (line.startsWith("-") && !line.startsWith("---")) return "del";
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("diff --git")) return "file";
  return "";
}

export default function DiffText({ text }: { text: string }) {
  return (
    <div className="diff">
      <pre>
        {text.split("\n").map((line, i) => (
          <div key={i} className={lineClass(line)}>{line || " "}</div>
        ))}
      </pre>
    </div>
  );
}
