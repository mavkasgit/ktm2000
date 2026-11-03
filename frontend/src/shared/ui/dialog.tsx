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

/**
 * Каркас окна: потолок высоты, прокрутка тела и кнопка закрытия.
 *
 * ПОТОЛОК ВЫСОТЫ И ПРОКРУТКА — в базовом наборе (ADR-0033). На телефоне окно
 * без потолка уходит нижним краем за экран, а прокрутить страницу под ним
 * нельзя: Radix блокирует прокрутку `body`. Поэтому `max-h-[calc(100dvh-2rem)]`
 * (экран минус поля) и `overflow-y-auto` стоят здесь, а не в каждом окне.
 * `cn` = `clsx` + `tailwind-merge`: окно, которому нужен другой потолок
 * (`max-h-screen` у шторки, `DIALOG_SIZES`, собственное `overflow-hidden` с
 * прокруткой внутри), перекрывает их своими классами — инлайновый стиль так
 * перекрыть было бы нельзя.
 *
 * ✕ ПРИ ПРОКРУТКЕ ТЕЛА (#344, ревью 6). Тело окна прокручивается самой рамкой,
 * а ✕ прижата к её верхнему правому углу: `absolute`-потомок скроллящегося
 * контейнера уезжает вместе с содержимым, и на высоком окне ✕ исчезала за
 * верхним краем экрана — закрыть мышью было нечего. `position: fixed` от этого
 * не лечит: трансформированная рамка (`translate-x/y-[-50%]`) становится для
 * него контейнером, и кнопка прокручивается ровно так же (замерено в Chromium).
 * Поэтому каркас догоняет прокрутку: `translateY` на величину `scrollTop`
 * рамки. При нулевой прокрутке смещение нулевое, то есть на десктопе и у окон с
 * внутренней прокруткой (`overflow-hidden` в классах вызывающего) ✕ стоит там
 * же, где стояла всегда.
 *
 * Почему слушателем, а не CSS: `position: sticky` вернул бы ✕ в поток — это
 * лишняя строка сетки (ломает окна с `grid-rows-[auto_minmax(0,1fr)_auto]`) и
 * лишний `gap` у всех остальных; перенос прокрутки с рамки на внутренний слой
 * ломает ~40 вызовов, чьи дети полагаются на то, что они непосредственные
 * flex/grid-потомки рамки.
 */
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
  const closeRef = React.useRef<HTMLButtonElement | null>(null)
  // Уборка за узлом. React 18 не вызывает функцию, возвращённую из
  // ref-колбэка (и предупреждает на сам возврат), поэтому убираем сами: и когда
  // узел менялся, и когда окно размонтировалось (`node === null`). Незакрытый
  // `ResizeObserver` держит узел в памяти, так что это не косметика.
  const detachRef = React.useRef<(() => void) | null>(null)

  const attachContent = React.useCallback(
    (node: HTMLDivElement | null) => {
      assignRef(forwardedRef, node)
      detachRef.current?.()
      detachRef.current = null
      if (!node) return
      const restore = (event: Event) => {
        const openedFrom = takeDialogTrigger()
        if (!openedFrom) return
        event.preventDefault()
        openedFrom.focus()
      }
      node.addEventListener(AUTOFOCUS_ON_UNMOUNT, restore)

      // ✕ догоняет прокрутку рамки (см. шапку компонента): смещение равно
      // `scrollTop`, поэтому при нулевой прокрутке кнопка не сдвинута.
      const pinClose = () => {
        const close = closeRef.current
        if (close) close.style.transform = `translateY(${node.scrollTop}px)`
      }
      // `scroll` ставится на саму рамку — он не всплывает, а `ResizeObserver`
      // пересинхронизирует смещение, когда высота рамки меняется и прокрутка
      // ужимается молча: поворот телефона, рост содержимого.
      node.addEventListener("scroll", pinClose, { passive: true })
      const resizeWatch =
        typeof ResizeObserver === "undefined"
          ? null
          : new ResizeObserver(pinClose)
      resizeWatch?.observe(node)
      pinClose()

      detachRef.current = () => {
        node.removeEventListener(AUTOFOCUS_ON_UNMOUNT, restore)
        node.removeEventListener("scroll", pinClose)
        resizeWatch?.disconnect()
      }
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
          "fixed left-[50%] top-[50%] z-50 grid w-auto translate-x-[-50%] translate-y-[-50%] gap-4 border bg-background p-6 shadow-lg sm:rounded-lg max-h-[calc(100dvh-2rem)] overflow-y-auto",
          className
        )}
        {...rest}
      >
        {children}
        <DialogPrimitive.Close
          ref={closeRef}
          className="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:pointer-events-none data-[state=open]:bg-accent data-[state=open]:text-muted-foreground"
        >
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
