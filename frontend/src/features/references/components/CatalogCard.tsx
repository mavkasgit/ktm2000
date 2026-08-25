import React from "react";
import { Image, Check, CheckCheck } from "lucide-react";
import { Card, CardContent } from "@/shared/ui/card";
import { Badge } from "@/shared/ui/badge";
import { getPhotoUrl } from "./getPhotoUrl";
import type { Product } from "@/shared/api/products";
import { productTypeLabels } from "@/shared/lib/generated-labels";

function getProductLengths(product: Product): number[] {
  return [...new Set([...(product.lengths_mm ?? []), product.length_mm ?? undefined].filter((v): v is number => typeof v === "number" && Number.isFinite(v) && v > 0))]
    .sort((a, b) => a - b);
}

export function CatalogCard({
  product,
  onClick,
  onSkuClick,
}: {
  product: Product;
  onClick: () => void;
  /** Если передан — артикул кликабелен (сводная информация), клик по карточке не срабатывает. */
  onSkuClick?: (sku: string) => void;
}) {
  const photoUrl = getPhotoUrl(product.photo_thumb);

  return (
    <Card className="cursor-pointer hover:shadow-md transition-shadow group" onClick={onClick}>
      <CardContent className="p-4">
        <div className="flex gap-3">
          <div className="w-16 h-16 bg-muted rounded flex items-center justify-center overflow-hidden flex-shrink-0">
            {photoUrl ? (
              <img src={photoUrl} alt={product.name} className="w-full h-full object-contain" />
            ) : (
              <Image className="w-6 h-6 text-muted-foreground" />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 justify-between">
              <div className="flex items-center gap-1.5 min-w-0">
                {onSkuClick ? (
                  <button
                    type="button"
                    className="font-medium truncate text-sm text-blue-700 hover:underline focus:outline-none"
                    title="Показать сводную информацию по артикулу"
                    onClick={(e) => {
                      e.stopPropagation();
                      onSkuClick(product.sku);
                    }}
                  >
                    {product.sku}
                  </button>
                ) : (
                  <h3 className="font-medium truncate text-sm">{product.sku}</h3>
                )}
                {product.code && (
                  <span className="text-xs text-muted-foreground bg-muted rounded px-1.5 py-0.5 shrink-0" title="Уникальный код">
                    {product.code}
                  </span>
                )}
                {product.has_standard_techcard && (
                  <span title="Есть стандартная техкарта">
                    <Check
                      className="h-3.5 w-3.5 text-emerald-600 flex-shrink-0"
                    />
                  </span>
                )}
                {product.has_paired_techcard && (
                  <span title="Есть парная техкарта">
                    <CheckCheck
                      className="h-3.5 w-3.5 text-violet-600 flex-shrink-0"
                    />
                  </span>
                )}
              </div>
            </div>
            <div className="flex gap-1 mt-2 flex-wrap">
              <Badge variant="outline" className="text-xs">{productTypeLabels[product.type]}</Badge>
              {product.profile_type && <Badge variant="secondary" className="text-xs">{product.profile_type}</Badge>}
              {product.color && <Badge variant="secondary" className="text-xs">{product.color}</Badge>}
              {(() => {
                const lengths = getProductLengths(product);
                return lengths.length ? <Badge variant="outline" className="text-xs">{lengths.join(", ")} мм</Badge> : null;
              })()}
              {product.is_catalog_item && <Badge variant="secondary" className="text-xs bg-blue-100">Сырье (каталог)</Badge>}
              {product.is_paired_profile && <Badge variant="secondary" className="text-xs bg-purple-100">Парный</Badge>}
              {product.is_laminated && <Badge variant="secondary" className="text-xs bg-green-100">Ламинируется</Badge>}
              {product.skip_shot_blast && <Badge variant="secondary" className="text-xs bg-amber-100">Без дробеструйки</Badge>}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
