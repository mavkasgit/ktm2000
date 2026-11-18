import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DatePicker } from "./date-picker";

describe("DatePicker — календарная дата", () => {
  it("частичный ввод не сбрасывает поле и не отправляет недописанную дату", () => {
    const onChange = vi.fn();
    render(<DatePicker value="" onChange={onChange} />);
    const input = screen.getByLabelText("ДД.ММ.ГГГГ") as HTMLInputElement;

    fireEvent.change(input, { target: { value: "2902" } });

    expect(input.value).toBe("29.02");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("29.02.2024 — валидная дата", () => {
    const onChange = vi.fn();
    render(<DatePicker value="" onChange={onChange} />);
    const input = screen.getByLabelText("ДД.ММ.ГГГГ");

    fireEvent.change(input, { target: { value: "29022024" } });

    expect(onChange).toHaveBeenCalledWith("2024-02-29");
  });

  it("29.02.2025 не уходит на сервер, но остаётся в поле", () => {
    const onChange = vi.fn();
    render(<DatePicker value="" onChange={onChange} />);
    const input = screen.getByLabelText("ДД.ММ.ГГГГ") as HTMLInputElement;

    fireEvent.change(input, { target: { value: "29022025" } });

    expect(onChange).not.toHaveBeenCalled();
    expect(input.value).toBe("29.02.2025");
  });

  it("Enter во время IME-композиции не уводит фокус из поля", () => {
    // Enter, которым оператор подтверждает иероглиф в IME, — не команда полю:
    // blur посреди композиции обрывает набор.
    render(<DatePicker value="" onChange={vi.fn()} />);
    const input = screen.getByLabelText("ДД.ММ.ГГГГ");
    const blur = vi.spyOn(input, "blur");

    const composing = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
    Object.defineProperty(composing, "isComposing", { value: true });
    fireEvent(input, composing);

    const imeKeyCode = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
    Object.defineProperty(imeKeyCode, "keyCode", { value: 229 });
    fireEvent(input, imeKeyCode);

    expect(blur).not.toHaveBeenCalled();

    fireEvent.keyDown(input, { key: "Enter" });

    expect(blur).toHaveBeenCalled();
  });
});
