"use strict";
// Как гейт собирает команду шага с `honorsStrict` (#368).
//
// Ловушка не теоретическая: `npm run check:что-то --strict` отдаёт флаг npm, а
// не скрипту — проверка продолжает исполняться без strict и молча остаётся
// зелёной там, где обязана краснеть. Разделитель `--` меняет это, и шаг-автору
// не нужно знать про npm: достаточно написать команду как обычно.

/** Флаг добавляется только шагам, которые его принимают. */
function buildStepCommand(step, strict) {
  if (!strict || !step.honorsStrict) return step.command;
  // Охватывает и `npm --prefix … run`: флаг съедается одинаково, где бы ни
  // стоял «npm» до «run».
  const viaNpm = /^npm\b[^\n]*\brun\b/.test(step.command);
  return step.command + (viaNpm ? " -- --strict" : " --strict");
}

module.exports = { buildStepCommand };
