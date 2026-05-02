import * as React from "react"
import { FileX } from "lucide-react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/shared/utils/cn"

const alertVariants = cva("relative w-full rounded-lg border p-4", {
  variants: {
    variant: {
      default: "bg-background text-foreground",
      destructive: "border-destructive/50 text-destructive",
    },
    tone: {
      info: "bg-background text-foreground",
      success: "border-green-200 bg-green-50 text-green-900",
      warning: "border-yellow-200 bg-yellow-50 text-yellow-900",
      danger: "border-destructive/50 text-destructive",
    },
  },
  defaultVariants: {
    variant: "default",
  },
})

const Alert = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof alertVariants>>(
  ({ className, variant, tone, ...props }, ref) => (
    <div ref={ref} role="alert" className={cn(alertVariants({ variant, tone }), className)} {...props} />
  ),
)
Alert.displayName = "Alert"

type EmptyStateProps = React.HTMLAttributes<HTMLDivElement> & {
  title?: string
  message?: string
  description?: string
  action?: React.ReactNode
}

function EmptyState({ className, title, message, description, action, ...props }: EmptyStateProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center rounded-lg border border-dashed py-12", className)} {...props}>
      <FileX className="mb-4 h-12 w-12 text-muted-foreground" />
      <h3 className="text-lg font-semibold">{title || message}</h3>
      {description ? <p className="mt-2 text-sm text-muted-foreground">{description}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  )
}

export { Alert, EmptyState }
