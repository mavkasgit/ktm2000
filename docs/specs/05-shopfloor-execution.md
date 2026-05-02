# 05. Shopfloor Execution

## Цель

Дать участкам рабочий экран задач и надежный учет факта: выдано, выполнено, передано, принято, забраковано, возвращено, выпущено.

## Рабочий экран мастера участка

Фильтры:

- участок;
- статус;
- изделие;
- срок;
- приоритет;
- есть доступное количество;
- есть просрочка;
- есть расхождение.

Колонки:

- SKU;
- изделие;
- операция;
- план;
- доступно;
- выдано;
- в работе;
- выполнено годное;
- передано;
- принято следующим участком;
- брак;
- остаток;
- статус;
- срок.

## Действия по задаче

### Принять от предыдущего участка

Доступно только для задач не первого этапа и только по созданной передаче.

Ввод:

- `transfer_id`;
- `accepted_quantity`;
- `rejected_quantity`;
- `comment`.

Результат:

- `transfer.status = accepted|partially_accepted|rejected`;
- создается `Movement(type='transfer_receive')` на принятое количество;
- при отклонении создается `Defect` или `Movement(type='reject')`;
- задача переходит в `ready`, если принятое количество > 0.

### Выдать в работу

Ввод:

- `task_id`;
- `quantity`;
- `comment`.

Правила:

- `quantity <= available_quantity - already_issued_open_quantity`;
- задача должна быть `ready`, `in_progress` или `partially_completed`.

Результат:

- создается `Movement(type='issue_to_work')`;
- задача переходит в `in_progress`.

### Отметить выполнение

Ввод:

- `task_id`;
- `good_quantity`;
- `defect_quantity`;
- `defect_reason`;
- `comment`.

Правила:

- `good_quantity + defect_quantity <= quantity_in_work`;
- если `defect_quantity > 0`, причина обязательна.

Результат:

- создается `Movement(type='complete')` на годное количество;
- при браке создается `Defect` в статусе `decision_required`;
- задача становится `partially_completed` или `completed`.

### Принять решение по браку

Ввод:

- `defect_id`;
- `decision`;
- `quantity`;
- `responsible_section_id`;
- `comment`.

Решения:

- `scrap` - списать окончательно;
- `rework_current` - создать задачу доработки на текущем участке;
- `return_previous` - создать задачу доработки или возврата на предыдущий участок;
- `quality_hold` - оставить на удержании до решения ОТК;
- `accept_with_deviation` - вернуть количество в годный поток с отметкой отклонения.

Результат:

- при списании создается `Movement(type='scrap')`;
- при доработке создается `ReworkTask`;
- при возврате создается `Movement(type='return_to_previous')` и задача/передача на предыдущий участок;
- при удержании количество не доступно следующему этапу;
- при принятии с отклонением количество может стать доступным следующему этапу, если роль пользователя это разрешает.

### Передать дальше

Доступно для не последнего этапа.

Ввод:

- `from_task_id`;
- `to_task_id`;
- `quantity`;
- `comment`.

Правила:

- `quantity <= completed_good_quantity - already_sent_quantity`;
- следующий этап должен принадлежать той же `PlanPosition`;
- нельзя передавать на произвольный участок вне маршрута.

Результат:

- создается `Transfer(status='sent')`;
- создается `Movement(type='transfer_send')`;
- следующая задача не получает доступность до приемки.

### Финальный выпуск

Доступно только для последнего этапа.

Ввод:

- `task_id`;
- `quantity`;
- `comment`.

Правила:

- `quantity <= completed_good_quantity - already_final_released_quantity`;

Результат:

- создается `Movement(type='final_release')`;
- обновляется прогресс позиции и производственного плана.

## Availability calculation

Для первого этапа:

`available = planned_quantity`

Для следующих этапов:

`available = accepted_from_previous - issued_to_work_on_current`

Для передачи:

`transferable = completed_good - transfer_send - final_release`

Для выполнения:

`in_work = issue_to_work - complete - reject - scrap - return_to_previous`

Кеш:

- `Movement` остается источником истины;
- `WorkTask` и `SectionPlanLine` хранят кеш итогов для быстрого отображения;
- кеш обновляется только backend-сервисом в одной транзакции с созданием движения;
- нужна служебная операция пересчета кеша из журнала движений.

## Обработка расхождений

Сценарий:

1. Участок A отправил 550.
2. Участок B принял 540.
3. 10 отклонено.

В системе:

- `Transfer.sent_quantity = 550`;
- `Transfer.accepted_quantity = 540`;
- `Transfer.rejected_quantity = 10`;
- движение `transfer_send` на 550;
- движение `transfer_receive` на 540;
- `Defect(reason='transfer_shortage')` или `Movement(type='reject')` на 10.

Следующая задача получает доступность 540.

## Корректировки

Корректировка нужна, потому что в реальном производстве будут пересчеты и ошибки ввода.

Корректировка факта:

- корректировку может делать только `admin` или `planner`;
- комментарий обязателен;
- корректировка создает `Movement(type='adjustment')`;
- корректировка не должна удалять исходные движения.

Корректировка плана:

- запущенная `PlanPosition` не меняется напрямую;
- изменение количества, срока или отмена остатка оформляется через `PlanAdjustment`;
- если по ошибочному запуску еще нет движений, можно отменить `ReleaseBatch` и создать новый;
- если движения есть, исправление идет через корректировку и новый пакет запуска.
