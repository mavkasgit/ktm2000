"use strict";
// Общие мелочи форматирования для node-скриптов: без них `plural` и `isoDate`
// копируются в каждый CLI и расходятся в правилах (например, «файлов» против
// «файла»). Один источник — один ответ на один вопрос.

/** Русская форма счётного слова. */
function plural(count, one, few, many) {
  const tens = count % 100;
  const unit = count % 10;
  if (tens >= 11 && tens <= 14) return many;
  if (unit === 1) return one;
  if (unit >= 2 && unit <= 4) return few;
  return many;
}

/** Дата сегодня в форме ISO — сравнение датированных исключений по строкам. */
function isoDate(now = new Date()) {
  return now.toISOString().slice(0, 10);
}

module.exports = { plural, isoDate };
