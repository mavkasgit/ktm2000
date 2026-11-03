#!/usr/bin/env node
// CLI машинного семафора: `node scripts/heavy.mjs -- <команда>`.
// Вся механика — в heavy-core.mjs (её проверяют scripts/heavy-core.test.js).
//
// Зачем свой, а не бинарь mokevnin/heavy: у heavy нет сборок под Windows, а
// `mise install` на windows-x64 падает («No matching asset found for platform
// windows-x64»). Node есть у всех, кому нужны задачи репозитория.

import { runHeavy } from "./heavy-core.mjs";

process.exitCode = await runHeavy(process.argv.slice(2));
