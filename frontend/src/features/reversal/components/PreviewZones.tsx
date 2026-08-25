import { AlertTriangle, Circle, CircleSlash, RefreshCw } from "lucide-react";
import type {
  ActionNode,
  PreviewBlocker,
  WillReplayItem,
} from "@/shared/api/actions";

/** Четыре зоны предпросмотра (ADR-0019 п.5 preview-first):
 *  🔴 отменится (revert) / ⚪ останется (stays) / 🚫 блокировки / 🟢 воспроизведётся (will_replay). */

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
  will_replay = [],
}: {
  revert: ActionNode[];
  stays: ActionNode[];
  blockers: PreviewBlocker[];
  will_replay?: WillReplayItem[];
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

      <section data-testid="preview-zone-replay">
        <h4 className="text-sm font-semibold text-green-700 flex items-center gap-1">
          🟢 Воспроизведётся ({will_replay.length})
        </h4>
        {will_replay.length > 0 ? (
          <ul className="mt-1 space-y-0.5">
            {will_replay
              .slice()
              .sort((a, b) => a.order - b.order)
              .map((r) => (
                <li
                  key={r.action_id}
                  className="text-sm text-slate-700"
                >
                  <RefreshCw className="mr-1 inline h-3.5 w-3.5 text-green-600" />
                  <span className="font-mono">#{r.action_id}</span>{" "}
                  <span className="font-medium">{r.action_type}</span>
                  {r.ref_id != null && (
                    <span className="text-slate-500"> · объект #{r.ref_id}</span>
                  )}
                  <span className="ml-1 text-xs text-slate-400">
                    (порядок {r.order})
                  </span>
                </li>
              ))}
          </ul>
        ) : (
          <p className="mt-1 text-xs text-slate-400">— пусто —</p>
        )}
      </section>
    </div>
  );
}
