import { AlertTriangle, Circle, CircleSlash } from "lucide-react";
import type { ActionNode, PreviewBlocker } from "@/shared/api/actions";

/** Три зоны предпросмотра (ADR-0019 п.5 preview-first):
 *  🔴 отменится (revert) / ⚪ останется (stays) / 🚫 блокировки. */

function NodeLine({ node }: { node: ActionNode }) {
  return (
    <li className="text-sm text-slate-700">
      <span className="font-mono">#{node.id}</span>{" "}
      <span className="font-medium">{node.action_type}</span>
      {node.ref_id != null && (
        <span className="text-slate-500"> · объект #{node.ref_id}</span>
      )}
      <span className="ml-1 text-xs text-slate-400">({node.status})</span>
    </li>
  );
}

export function PreviewZones({
  revert,
  stays,
  blockers,
}: {
  revert: ActionNode[];
  stays: ActionNode[];
  blockers: PreviewBlocker[];
}) {
  return (
    <div className="space-y-3">
      <section data-testid="preview-zone-revert">
        <h4 className="text-sm font-semibold text-red-700">
          🔴 Отменится ({revert.length})
        </h4>
        {revert.length > 0 ? (
          <ul className="mt-1 space-y-0.5">
            {revert.map((n) => (
              <NodeLine key={n.id} node={n} />
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-xs text-slate-400">— пусто —</p>
        )}
      </section>

      <section data-testid="preview-zone-stays">
        <h4 className="text-sm font-semibold text-slate-600 flex items-center gap-1">
          ⚪ Останется ({stays.length})
        </h4>
        {stays.length > 0 ? (
          <ul className="mt-1 space-y-0.5">
            {stays.map((n) => (
              <NodeLine key={n.id} node={n} />
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-xs text-slate-400">— пусто —</p>
        )}
      </section>

      <section data-testid="preview-zone-blockers">
        <h4 className="text-sm font-semibold text-slate-800 flex items-center gap-1">
          🚫 Блокировки ({blockers.length})
        </h4>
        {blockers.length > 0 ? (
          <ul className="mt-1 space-y-1">
            {blockers.map((b, i) => (
              <li
                key={`${b.kind}-${b.node_id ?? i}`}
                className="flex items-start gap-1.5 rounded border border-red-100 bg-red-50/60 p-2 text-sm text-red-800"
              >
                {b.chain ? (
                  <CircleSlash className="mt-0.5 h-4 w-4 shrink-0" />
                ) : b.deficit ? (
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                ) : (
                  <Circle className="mt-0.5 h-4 w-4 shrink-0" />
                )}
                <span>
                  {b.detail}
                  {b.deficit && (
                    <span className="font-mono"> (дефицит {b.deficit})</span>
                  )}
                  {b.chain && (
                    <span className="font-mono">
                      {" "}
                      (цепочка:{" "}
                      {b.chain.map((id) => `#${id}`).join(" → ")})
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-xs text-slate-400">— нет —</p>
        )}
      </section>
    </div>
  );
}
