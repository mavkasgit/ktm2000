import * as React from "react"
import * as DialogPrimitive from "@radix-ui/react-dialog"
import { X } from "lucide-react"

import { cn } from "@/shared/utils/cn"
import { takeDialogTrigger } from "@/shared/lib/dialogFocus"

const Dialog = DialogPrimitive.Root
const DialogTrigger = DialogPrimitive.Trigger
const DialogClose = DialogPrimitive.Close
const DialogPortal = DialogPrimitive.Portal

/**
 * Radix отменяет возврат фокуса при закрытии окна только через это DOM-событие:
 * восстановление выполняется в `setTimeout(0)` уже после закрытия, а отменить
 * его можно лишь отменой события (внутренний проп `onUnmountAutoFocus` наружу
 * не выведен).
 */
const AUTOFOCUS_ON_UNMOUNT = "focusScope.autoFocusOnUnmount"

function assignRef<T>(ref: React.Ref<T> | undefined, node: T | null) {
  if (typeof ref === "function") ref(node)
  else if (ref) (ref as React.MutableRefObject<T | null>).current = node
}

const DialogOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      "fixed inset-0 z-50 bg-black/60",
      className
    )}
    {...props}
  />
))
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName

const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>((props, forwardedRef) => {
  // Возврат фокуса — на элемент, которым окно открыли (ADR-0033).
  //
  // Свой `onCloseAutoFocus` для этого не годится: Radix восстанавливает фокус
  // в `setTimeout(0)` уже после закрытия окна, то есть позже нашего обработчика,
  // и перебивает его. А то, что он восстанавливает, к тому моменту успело слететь
  // на `body`: между кликом и монтированием окна страница перерисовывается и
  // активный элемент теряет фокус, поэтому Radix честно возвращает фокус туда же.
  // Источник запоминается заранее (см. `shared/lib/dialogFocus`).
  //
  // Слушатель вешается в ref-колбэке, а не в эффекте: содержимое окна Radix
  // монтирует отдельным проходом, и в эффекте без зависимостей узла в этот
  // момент ещё нет, а повторно эффект уже не запустится.
  const attachContent = React.useCallback(
    (node: HTMLDivElement | null) => {
      assignRef(forwardedRef, node)
      if (!node) return
      const restore = (event: Event) => {
        const openedFrom = takeDialogTrigger()
        if (!openedFrom) return
        event.preventDefault()
        openedFrom.focus()
      }
      node.addEventListener(AUTOFOCUS_ON_UNMOUNT, restore)
      return () => node.removeEventListener(AUTOFOCUS_ON_UNMOUNT, restore)
    },
    [forwardedRef],
  )

  const { className, children, ...rest } = props
  return (
    <DialogPortal>
      <DialogOverlay />
      <DialogPrimitive.Content
        ref={attachContent}
        className={cn(
          "fixed left-[50%] top-[50%] z-50 grid w-auto translate-x-[-50%] translate-y-[-50%] gap-4 border bg-background p-6 shadow-lg sm:rounded-lg",
          className
        )}
        {...rest}
      >
        {children}
        <DialogPrimitive.Close className="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:pointer-events-none data-[state=open]:bg-accent data-[state=open]:text-muted-foreground">
          <X className="h-4 w-4" />
          <span className="sr-only">Закрыть</span>
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPortal>
  )
})
DialogContent.displayName = DialogPrimitive.Content.displayName

const DialogHeader = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn("flex flex-col space-y-1.5 text-center sm:text-left", className)}
    {...props}
  />
)
DialogHeader.displayName = "DialogHeader"

const DialogFooter = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn("flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2", className)}
    {...props}
  />
)
DialogFooter.displayName = "DialogFooter"

const DialogTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn("text-lg font-semibold leading-none tracking-tight", className)}
    {...props}
  />
))
DialogTitle.displayName = DialogPrimitive.Title.displayName

const DialogDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn("text-sm text-muted-foreground", className)}
    {...props}
  />
))
DialogDescription.displayName = DialogPrimitive.Description.displayName

export {
  Dialog,
  DialogTrigger,
  DialogClose,
  DialogPortal,
  DialogOverlay,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
}
