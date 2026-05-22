import { renderIcon } from "@/shared/ui/EntityDialog";

interface RouteStep {
  section_id: number;
  section_icon: string | null;
  section_icon_color: string | null;
  sequence: number;
}

interface StepIndicatorProps {
  steps: RouteStep[];
  currentStageSequence: number | null;
  currentStageTaskStatus: string | null;
  sectionMetaById: Map<number, { icon: string | null; icon_color: string | null }>;
}

export function StepIndicator({
  steps,
  currentStageSequence,
  currentStageTaskStatus,
  sectionMetaById,
}: StepIndicatorProps) {
  if (steps.length === 0) return null;

  // If 5 or fewer steps, show all
  if (steps.length <= 5) {
    return (
      <div className="flex items-center gap-1.5">
        {steps.map((step) => {
          const { isCompleted, isCurrent, isInProgress, isReady } = getStepStatus(
            step.sequence,
            currentStageSequence,
            currentStageTaskStatus
          );
          const sectionMeta = sectionMetaById.get(step.section_id);
          const icon = step.section_icon || sectionMeta?.icon || null;
          const iconColor = step.section_icon_color || sectionMeta?.icon_color || "#2563EB";

          return (
            <StepDot
              key={step.section_id}
              step={step}
              icon={icon}
              iconColor={iconColor}
              isCompleted={isCompleted}
              isCurrent={isCurrent}
              isInProgress={isInProgress}
              isReady={isReady}
            />
          );
        })}
      </div>
    );
  }

  // Show up to 5 real steps around the current stage. Ellipses are intentionally
  // omitted because they consume the same space as useful step dots.
  const currentIndex = Math.max(
    0,
    steps.findIndex((step) => step.sequence === currentStageSequence),
  );
  const windowSize = 5;
  const startIndex = Math.min(
    Math.max(0, currentIndex - 2),
    Math.max(0, steps.length - windowSize),
  );
  const endIndex = Math.min(steps.length, startIndex + windowSize);

  const visibleSteps = steps.slice(startIndex, endIndex);

  return (
    <div className="flex items-center gap-1.5">
      {visibleSteps.map((step) => {
        const { isCompleted, isCurrent, isInProgress, isReady } = getStepStatus(
          step.sequence,
          currentStageSequence,
          currentStageTaskStatus
        );
        const sectionMeta = sectionMetaById.get(step.section_id);
        const icon = step.section_icon || sectionMeta?.icon || null;
        const iconColor = step.section_icon_color || sectionMeta?.icon_color || "#2563EB";

        return (
          <StepDot
            key={step.section_id}
            step={step}
            icon={icon}
            iconColor={iconColor}
            isCompleted={isCompleted}
            isCurrent={isCurrent}
            isInProgress={isInProgress}
            isReady={isReady}
          />
        );
      })}
    </div>
  );
}

function getStepStatus(
  sequence: number,
  currentStageSequence: number | null,
  currentStageTaskStatus: string | null
) {
  const isCompleted =
    currentStageSequence !== null &&
    (sequence < currentStageSequence ||
      (sequence === currentStageSequence && currentStageTaskStatus === "completed"));
  const isCurrent = currentStageSequence !== null && sequence === currentStageSequence;
  const isInProgress = isCurrent && currentStageTaskStatus === "in_progress";
  const isReady = isCurrent && currentStageTaskStatus === "ready";
  return { isCompleted, isCurrent, isInProgress, isReady };
}

function StepDot({
  step,
  icon,
  iconColor,
  isCompleted,
  isCurrent,
  isInProgress,
  isReady,
}: {
  step: RouteStep;
  icon: string | null;
  iconColor: string;
  isCompleted: boolean;
  isCurrent: boolean;
  isInProgress: boolean;
  isReady: boolean;
}) {
  let bgColor: string;
  let textColor: string;
  let borderColor: string | null = null;

  if (isCompleted) {
    bgColor = "#10B981";
    textColor = "#FFFFFF";
  } else if (isInProgress) {
    bgColor = "#3B82F6";
    textColor = "#FFFFFF";
  } else if (isReady) {
    bgColor = "transparent";
    textColor = "#3B82F6";
    borderColor = "#3B82F6";
  } else {
    bgColor = "#E5E7EB";
    textColor = "#9CA3AF";
  }

  return (
    <div
      className="relative group"
      title={`Этап #${step.sequence}`}
    >
      <div
        className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-medium transition-all ${
          isInProgress ? "ring-2 ring-blue-300 ring-offset-1" : ""
        } ${isReady ? "ring-2 ring-blue-300" : ""}`}
        style={{
          backgroundColor: bgColor,
          color: textColor,
          ...(borderColor ? { border: `2px solid ${borderColor}` } : {}),
        }}
      >
        {icon ? (
          <span
            className="inline-flex h-5 w-5 items-center justify-center"
            style={{ color: isCompleted || isInProgress ? "#FFFFFF" : iconColor }}
          >
            {renderIcon(icon, "h-3 w-3")}
          </span>
        ) : (
          step.sequence
        )}
      </div>
      {/* Tooltip */}
      <div className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover:block z-10">
        <div className="bg-gray-900 text-white text-xs rounded px-2 py-1 whitespace-nowrap">
          Этап #{step.sequence}
        </div>
        <div className="w-2 h-2 bg-gray-900 transform rotate-45 -translate-y-1 mx-auto"></div>
      </div>
    </div>
  );
}
