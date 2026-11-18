// @vitest-environment happy-dom

import { fireEvent, render, screen, act } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { TooltipProvider } from "../ui"
import { CopyButton } from "./ui-bits"

/**
 * Кнопка копирования — примитив из `@siberiacancode/reactuse` (#415).
 * Тест держит то, что зависит от проекта, а не от пакета: значение уходит в
 * буфер как есть, а галочка живёт ровно 1600 мс и возвращается к иконке сама.
 */
describe("CopyButton", () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  const checkIcon = (container: HTMLElement) => container.querySelector(".text-green-500")

  it("копирует значение и показывает галочку на 1600 мс", async () => {
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined)
    const { container } = render(
      <TooltipProvider>
        <CopyButton value="session-42" label="Копировать" copiedLabel="Скопировано" />
      </TooltipProvider>,
    )
    expect(checkIcon(container)).toBeNull()

    fireEvent.click(screen.getByRole("button", { name: "Копировать" }))
    await act(async () => {})

    expect(writeText).toHaveBeenCalledWith("session-42")
    expect(checkIcon(container)).not.toBeNull()

    act(() => {
      vi.advanceTimersByTime(1599)
    })
    expect(checkIcon(container)).not.toBeNull()

    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(checkIcon(container)).toBeNull()
  })

  it("не рисует галочку, если копирование не удалось", async () => {
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("denied"))
    const { container } = render(
      <TooltipProvider>
        <CopyButton value="session-42" label="Копировать" copiedLabel="Скопировано" />
      </TooltipProvider>,
    )

    fireEvent.click(screen.getByRole("button", { name: "Копировать" }))
    await act(async () => {})

    expect(checkIcon(container)).toBeNull()
  })
})
