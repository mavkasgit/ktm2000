import { useMemo } from "react"
import multiavatar from "@multiavatar/multiavatar/esm"
import { User } from "lucide-react"
import { cn } from "@/shared/utils/cn"

type Fit = "cover" | "contain"

type UserAvatarProps = {
  seed?: string | number | null
  size?: number
  className?: string
  fit?: Fit
}

/** Multiavatar by seed; null → silhouette placeholder (same as HRMS). */
export function UserAvatar({ seed, size = 32, className, fit = "cover" }: UserAvatarProps) {
  const preserveAspectRatio = fit === "contain" ? "xMidYMid meet" : "xMidYMid slice"
  const isRounded = fit === "cover"

  const svg = useMemo(() => {
    if (seed == null || seed === "") return null
    try {
      return multiavatar(String(seed))
        .replace(/<\?xml[^>]*\?>/g, "")
        .replace(/<!--[\s\S]*?-->/g, "")
    } catch {
      return null
    }
  }, [seed])

  const dim = `${size}px`
  const iconSize = Math.max(12, Math.round(size * 0.5))

  if (svg) {
    return (
      <div
        className={cn(
          "relative inline-flex items-center justify-center overflow-hidden bg-muted shrink-0",
          isRounded && "rounded-full",
          className,
        )}
        style={{ width: dim, height: dim }}
        dangerouslySetInnerHTML={{
          __html: svg.replace(
            "<svg ",
            `<svg width="${size}" height="${size}" preserveAspectRatio="${preserveAspectRatio}" `,
          ),
        }}
        aria-hidden
      />
    )
  }

  return (
    <div
      className={cn(
        "inline-flex items-center justify-center rounded-full bg-muted text-muted-foreground/60 shrink-0 border border-border/60",
        className,
      )}
      style={{ width: dim, height: dim }}
      aria-hidden
    >
      <User style={{ width: iconSize, height: iconSize }} strokeWidth={1.75} />
    </div>
  )
}
