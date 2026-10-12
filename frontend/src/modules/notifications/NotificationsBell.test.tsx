import { render, act } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { NotificationsBell } from "./NotificationsBell"
import type { NotificationsApi } from "./api/adapter"

describe("NotificationsBell visibilitychange polling", () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  function createMockApi(): NotificationsApi {
    return {
      list: vi.fn().mockResolvedValue({ items: [], total: 0, unread_count: 0 }),
      markRead: vi.fn().mockResolvedValue(undefined),
      close: vi.fn().mockResolvedValue(undefined),
    }
  }

  it("опрашивает сервер на видимой вкладке с заданным интервалом", async () => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    })
    const api = createMockApi()

    render(<NotificationsBell api={api} pollIntervalMs={10_000} />)

    // Даём завершиться первичному асинхронному запросу, чтобы inFlightRef стал false
    await act(async () => {})
    expect(api.list).toHaveBeenCalledTimes(1)

    // Спустя интервал поллинга
    await act(async () => {
      vi.advanceTimersByTime(10_000)
    })
    expect(api.list).toHaveBeenCalledTimes(2)

    await act(async () => {
      vi.advanceTimersByTime(10_000)
    })
    expect(api.list).toHaveBeenCalledTimes(3)
  })

  it("останавливает опрос при скрытии вкладки", async () => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    })
    const api = createMockApi()

    render(<NotificationsBell api={api} pollIntervalMs={10_000} />)
    expect(api.list).toHaveBeenCalledTimes(1)

    // Скрываем вкладку
    act(() => {
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        value: "hidden",
      })
      document.dispatchEvent(new Event("visibilitychange"))
    })

    // Время идёт, но запросы не должны отправляться
    await act(async () => {
      vi.advanceTimersByTime(30_000)
    })
    expect(api.list).toHaveBeenCalledTimes(1)
  })

  it("при возврате вкладки обновляет немедленно и перезапускает интервал", async () => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    })
    const api = createMockApi()

    render(<NotificationsBell api={api} pollIntervalMs={10_000} />)
    // На скрытой вкладке не загружает
    expect(api.list).toHaveBeenCalledTimes(0)

    // Возвращаем вкладку в visible
    await act(async () => {
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        value: "visible",
      })
      document.dispatchEvent(new Event("visibilitychange"))
    })

    // Сразу же вызвана загрузка (без ожидания следующего тика таймера)
    expect(api.list).toHaveBeenCalledTimes(1)

    // И интервал перезапущен: через 10с пойдёт следующий тик
    await act(async () => {
      vi.advanceTimersByTime(10_000)
    })
    expect(api.list).toHaveBeenCalledTimes(2)
  })

  it("снимает слушатель visibilitychange и таймер при размонтировании", async () => {
    const removeEventListenerSpy = vi.spyOn(document, "removeEventListener")
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    })
    const api = createMockApi()

    const { unmount } = render(<NotificationsBell api={api} pollIntervalMs={10_000} />)
    expect(api.list).toHaveBeenCalledTimes(1)

    unmount()

    expect(removeEventListenerSpy).toHaveBeenCalledWith(
      "visibilitychange",
      expect.any(Function),
    )

    // После размонтирования ни события, ни таймеры не вызывают api.list
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"))
      vi.advanceTimersByTime(20_000)
    })
    expect(api.list).toHaveBeenCalledTimes(1)
  })
})
