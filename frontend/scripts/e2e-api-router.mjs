/**
 * Роутер `/api` стенда E2E: один адрес на прогон, backend — по воркеру (#289).
 *
 * Зачем
 * -----
 * Изоляция #281 даёт прогону **свой клон БД**, но воркеры Playwright внутри
 * одного прогона делили его, а `apiResetAll()` — это `TRUNCATE … CASCADE`:
 * соседний воркер сносил данные другого прямо посреди теста (7/7 красных на
 * `--workers=2`, см. `docs/night/tickets/T-253-workers2-series.md`).
 *
 * Теперь у каждого воркера своя БД, а значит нужен свой backend. Один frontend
 * на всех (vite поднимать на каждый воркер дорого, а стенд один), поэтому
 * `/api` уводится сюда, и уже этот процесс решает, в какой backend идти.
 *
 * Почему не `router` в `server.proxy` vite
 * ---------------------------------------
 * Опция `router` есть у http-proxy, на который смотрит vite, но в сборке
 * vite 6.4.2 она **молча игнорируется**: все запросы уходят в `target`
 * (проверено пробой — заголовок `x-e2e-worker: 1` дошёл до backend 0). Тихий
 * увод в чужой backend здесь опаснее, чем отсутствие фичи: тест был бы зелёным
 * на данных соседа. Поэтому маршрутизация вынесена в отдельный процесс.
 *
 * Как выбирается backend
 * ---------------------
 * По заголовку `x-e2e-worker` (его ставит фикстура `extraHTTPHeaders` в
 * `e2e/fixtures.ts` значение `workerInfo.workerIndex`). Без заголовка — backend
 * 0: одиночный прогон и ручной стенд (`PW_REUSE_STACK=1`) не меняются.
 *
 * Что проксируется
 * ----------------
 * `/api` и `/static` — оба идут в backend (вторым отдаются загруженные файлы).
 * Тела и потоки не разбираются: запрос проксируется как есть, поэтому
 * `page.request`/`fetch` из теста и раздача `/static` работают одинаково.
 *
 * Адреса backend'ов приходят в `E2E_WORKER_API_URLS` (JSON), порт роутера —
 * в `E2E_ROUTER_PORT`; см. `scripts/run-e2e.mjs`.
 */
import http from "node:http";

const WORKER_HEADER = "x-e2e-worker";
const PROXY_PREFIXES = ["/api", "/static"];

function workerApiUrls() {
  const raw = process.env.E2E_WORKER_API_URLS;
  if (!raw) {
    throw new Error(
      "E2E_WORKER_API_URLS не задан — список адресов backend'ов даёт scripts/run-e2e.mjs",
    );
  }
  const parsed = JSON.parse(raw);
  if (!Array.isArray(parsed) || parsed.length === 0) {
    throw new Error(`E2E_WORKER_API_URLS — непустой массив адресов, получено: ${raw}`);
  }
  return parsed;
}

function backendFor(req, backends) {
  const raw = req.headers[WORKER_HEADER];
  const index = Number(Array.isArray(raw) ? raw[0] : raw ?? 0);
  if (!Number.isInteger(index) || index < 0) {
    throw new Error(`${WORKER_HEADER} должен быть неотрицательным целым, получено: ${raw}`);
  }
  // Заголовок может остаться от переиспользованного контекста, а backend'ов
  // меньше: молча уводить в чужой backend нельзя — это ровно тот класс
  // «зелёный тест на данных соседа». Такой запрос 500-им с внятным текстом.
  if (index >= backends.length) {
    throw new Error(
      `${WORKER_HEADER}=${index}, а backend'ов в прогоне ${backends.length}: ` +
        "слот воркера не соответствует прогону (см. docs/night/tickets/T-289-*.md)",
    );
  }
  return backends[index];
}

const backends = workerApiUrls().map((url) => new URL(url.replace(/\/$/, "")));
const port = Number(process.env.E2E_ROUTER_PORT);
if (!port) {
  throw new Error("E2E_ROUTER_PORT не задан — порт роутера выдаёт scripts/run-e2e.mjs");
}

const server = http.createServer((req, res) => {
  const pathname = req.url?.split("?", 1)[0] ?? "";
  if (!PROXY_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))) {
    res.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
    res.end("роутер стенда обслуживает только /api и /static");
    return;
  }

  let target;
  try {
    target = backendFor(req, backends);
  } catch (error) {
    res.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
    res.end(`e2e-api-router: ${error.message}`);
    return;
  }

  const headers = { ...req.headers };
  // Заголовок воркера на backend не нужен: там он ничего не значит. Именно
  // удалением, а не значением `undefined`: Node бросает на такой заголовок
  // `ERR_HTTP_INVALID_HEADER_VALUE` и роняет запрос.
  delete headers[WORKER_HEADER];

  const upstream = http.request(
    {
      hostname: target.hostname,
      port: target.port,
      path: req.url,
      method: req.method,
      headers,
    },
    (upstreamRes) => {
      res.writeHead(upstreamRes.statusCode ?? 502, upstreamRes.headers);
      upstreamRes.pipe(res);
    },
  );
  upstream.on("error", (error) => {
    if (res.headersSent) {
      res.destroy(error);
      return;
    }
    res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
    res.end(`e2e-api-router: backend ${target.port} недоступен: ${error.message}`);
  });
  req.pipe(upstream);
});

server.listen(port, "127.0.0.1", () => {
  console.log(
    `[e2e:router] /api и /static на свободном порту ${port} → ` +
      `${backends.length} backend(ов): ${backends.map((b) => b.port).join(", ")}`,
  );
});

for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => {
    server.close();
    process.exit(0);
  });
}