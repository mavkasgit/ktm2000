// ПРОТОТИП #143 (throwaway) — хост вариантов страницы «Продукты».
// Три варианта на существующем маршруте /references/products, переключение
// через ?variant= (панель внизу, клавиши ←/→). Монтируется только в DEV.
// Вопрос и вердикт — README.md рядом. После решения варианта код удаляется из main.
import { useSearchParams } from "react-router-dom";
import { PrototypeSwitcher, FINISHED_GOODS_VARIANTS } from "./PrototypeSwitcher";
import { VariantA } from "./VariantA";
import { VariantB } from "./VariantB";
import { VariantC } from "./VariantC";

export function FinishedGoodsPrototype() {
  const [searchParams] = useSearchParams();
  const variant = searchParams.get("variant") ?? "A";

  return (
    <>
      {variant === "B" && <VariantB />}
      {variant === "C" && <VariantC />}
      {variant !== "B" && variant !== "C" && <VariantA />}
      <PrototypeSwitcher variants={FINISHED_GOODS_VARIANTS} current={variant} />
    </>
  );
}
