import { FinishedGoodsPrototype } from "../prototype/finished-goods/FinishedGoodsPrototype";

const PROTOTYPE_STUB = (
  <div className="py-12 text-center text-muted-foreground">
    <h2 className="text-xl font-semibold mb-2">Справочник готовой продукции</h2>
    <p>Страница в разработке</p>
  </div>
);

// ПРОТОТИП #143 (throwaway): варианты страницы «Продукты» монтируются на этом
// маршруте только в DEV-сборке; вопрос и вердикт — в README прототипа.
export function FinishedGoodsPage() {
  if (!import.meta.env.DEV) {
    return PROTOTYPE_STUB;
  }
  return <FinishedGoodsPrototype />;
}
