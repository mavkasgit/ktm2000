import * as React from "react"
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

export { Alert }
