import { useState } from "react";

interface EntityTimelineProps {
  entityType: string;
  entityId: number;
  // Дополнительно можно передать исходную историю или загрузить внутри компонента
  historyLogs: any[];
}

export function EntityTimeline({ entityType, entityId, historyLogs }: EntityTimelineProps) {
  const [expandedLogId, setExpandedLogId] = useState<number | null>(null);

  const filteredLogs = historyLogs.filter(
    (log) =>
      log.entity_type === entityType &&
      (log.entity_id === entityId || String(log.entity_id) === String(entityId))
  );

  if (filteredLogs.length === 0) {
    return (
      <div className="text-center py-6 text-slate-400 text-xs">
        История изменений для данной сущности отсутствует.
      </div>
    );
  }

  const formatTime = (dateStr: string) => {
    const d = new Date(dateStr);
    return isNaN(d.getTime())
      ? dateStr
      : d.toLocaleDateString("ru-RU", {
          day: "2-digit",
          month: "2-digit",
          year: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        });
  };

  const getActionBadge = (action: string) => {
    switch (action) {
      case "create":
        return <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-100 uppercase">Создание</span>;
      case "update":
        return <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-50 text-blue-700 border border-blue-100 uppercase">Обновление</span>;
      case "delete":
        return <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-red-50 text-red-700 border border-red-100 uppercase">Удаление</span>;
      case "approve":
        return <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-teal-50 text-teal-700 border border-teal-100 uppercase">Утверждение</span>;
      case "cancel":
        return <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-50 text-amber-700 border border-amber-100 uppercase">Отмена</span>;
      case "restore":
        return <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-purple-50 text-purple-700 border border-purple-100 uppercase">Восстановление</span>;
      case "release":
        return <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-indigo-50 text-indigo-700 border border-indigo-100 uppercase">Выпуск</span>;
      default:
        return <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-50 text-slate-700 border border-slate-100 uppercase">{action}</span>;
    }
  };

  const renderChanges = (changes: any) => {
    if (!changes || typeof changes !== "object") return null;
    const before = changes.before || {};
    const after = changes.after || {};
    const changedKeys = Object.keys({ ...before, ...after });

    if (changedKeys.length === 0) return null;

    return (
      <div className="mt-2 bg-slate-50 border border-slate-100 rounded p-2.5 space-y-1.5 font-mono text-[11px] text-slate-700">
        <div className="grid grid-cols-3 font-bold border-b border-slate-200/60 pb-1 text-[9px] uppercase tracking-wider text-slate-400">
          <span>Поле</span>
          <span>Было</span>
          <span>Стало</span>
        </div>
        {changedKeys.map((key) => {
          const valBefore = before[key] !== undefined ? String(before[key]) : "—";
          const valAfter = after[key] !== undefined ? String(after[key]) : "—";
          return (
            <div key={key} className="grid grid-cols-3 py-0.5 border-b border-slate-100/60 last:border-0 items-center">
              <span className="font-semibold text-slate-600 truncate pr-1" title={key}>{key}</span>
              <span className="text-red-650 bg-red-50 px-1 rounded truncate mr-1" title={valBefore}>{valBefore}</span>
              <span className="text-emerald-700 bg-emerald-50 px-1 rounded truncate" title={valAfter}>{valAfter}</span>
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <div className="relative border-l border-slate-200 ml-3.5 my-3 pl-6 space-y-6">
      {filteredLogs.map((log) => {
        const isExpanded = expandedLogId === log.id;
        return (
          <div key={log.id} className="relative">
            {/* Timeline Node Icon */}
            <span className="absolute -left-[31px] top-1.5 flex h-4.5 w-4.5 items-center justify-center rounded-full border border-white bg-indigo-500 text-white shadow-sm ring-4 ring-white">
              <span className="h-1.5 w-1.5 rounded-full bg-white" />
            </span>

            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold text-slate-800">{log.title}</span>
                {log.action && getActionBadge(log.action)}
                <span className="text-[10px] text-slate-400 font-mono ml-auto">
                  {formatTime(log.created_at)}
                </span>
              </div>
              <p className="text-xs text-slate-600 font-medium leading-relaxed">
                {log.message}
              </p>
              {log.user_name && (
                <p className="text-[10px] text-slate-400 font-semibold">
                  Исполнитель: <span className="text-slate-600">👤 {log.user_name}</span>
                </p>
              )}
              {log.changes && (
                <div className="pt-1">
                  <button
                    type="button"
                    onClick={() => setExpandedLogId(isExpanded ? null : log.id)}
                    className="text-[10px] font-bold text-indigo-600 hover:text-indigo-800 focus:outline-none"
                  >
                    {isExpanded ? "Свернуть изменения" : "Показать изменения"}
                  </button>
                  {isExpanded && renderChanges(log.changes)}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
