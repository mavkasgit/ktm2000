// Node 26 объявляет глобальные localStorage/sessionStorage только при запуске
// с --localstorage-file, иначе конфигурируемый геттер отдаёт undefined.
// happy-dom 20 не перезаписывает уже объявленный глобальный ключ, поэтому в
// тестах браузерные storage недоступны, а код (например, PlanModal) падает на
// setItem. Даём эквивалент браузерного Storage в памяти — тот же контракт:
// getItem/setItem/removeItem/clear/key/length.
class MemoryStorage {
  private readonly data = new Map<string, string>();

  get length(): number {
    return this.data.size;
  }

  clear(): void {
    this.data.clear();
  }

  getItem(key: string): string | null {
    return this.data.has(key) ? (this.data.get(key) as string) : null;
  }

  key(index: number): string | null {
    return Array.from(this.data.keys())[index] ?? null;
  }

  removeItem(key: string): void {
    this.data.delete(key);
  }

  setItem(key: string, value: string): void {
    this.data.set(String(key), String(value));
  }
}

for (const key of ["localStorage", "sessionStorage"] as const) {
  if (globalThis[key] === undefined) {
    Object.defineProperty(globalThis, key, {
      value: new MemoryStorage(),
      configurable: true,
      writable: true,
    });
  }
}
