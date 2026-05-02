# References

Эти проекты используются как доменные референсы. Мы не копируем их архитектуру целиком.

## ERPNext

Используем как референс manufacturing-потока:

- Item / Product;
- BOM;
- Routing;
- Workstation;
- Production Plan;
- Work Order;
- Job Card;
- Stock Entry.

Полезная связка:

`Production Plan -> Work Order -> Job Card -> Stock Entry`

Ссылки:

- [ERPNext GitHub](https://github.com/frappe/erpnext)
- [ERPNext docs](https://docs.erpnext.com/)
- [ERPNext Routing docs](https://docs.frappe.io/erpnext/user/manual/en/routing)
- [ERPNext manufacturing overview](https://erpnext.com/manufacturing/open-source-integrated-manufacturing-software)

## frePPLe

Используем как референс планирования по операциям, ресурсам и календарям:

- Demand;
- Operation;
- Resource;
- Calendar;
- Buffer;
- OperationPlan.

Полезная связка:

`Demand -> Operation -> Resource -> Calendar -> OperationPlan`

Ссылки:

- [frePPLe website](https://frepple.com/)
- [frePPLe GitHub](https://github.com/frePPLe/frepple)
- [frePPLe operations docs](https://frepple.com/docs/current/model-reference/operations.php)
- [frePPLe resources docs](https://frepple.com/docs/current/model-reference/operation-resources.php)

## InvenTree

Используем как референс изделий, BOM, stock и build order:

- Part;
- BOMItem;
- StockItem;
- StockLocation;
- BuildOrder;
- StockAllocation;
- shortage / availability.

Полезная связка:

`Part -> BOM -> StockItem -> BuildOrder -> Allocation`

Ссылки:

- [InvenTree GitHub](https://github.com/inventree/InvenTree)
- [InvenTree website](https://inventree.org/)
- [InvenTree docs](https://docs.inventree.org/)
- [InvenTree build order API docs](https://docs.inventree.org/en/1.3.x/api/schema/build/)

