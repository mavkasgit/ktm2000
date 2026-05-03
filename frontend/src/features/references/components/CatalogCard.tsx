import React from "react";
import { Image } from "lucide-react";
import { Card, CardContent } from "@/shared/ui/Card";
import { Badge } from "@/shared/ui/Badge";
import { getPhotoUrl } from "./getPhotoUrl";
import type { Product, ProductType } from "@/shared/api/products";

const TYPE_LABELS: Record<ProductType, string> = {
  finished_good: "ГП",
  semi_finished: "П/ф",
  component: "Сырье",
  material: "Материал",
};

export function CatalogCard({
  product,
  onClick,
}: {
  product: Product;
  onClick: () => void;
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
            <div className="flex items-start justify-between">
              <h3 className="font-medium truncate text-sm">{product.sku}</h3>
            </div>
            <div className="flex gap-1 mt-2 flex-wrap">
              <Badge variant="outline" className="text-xs">{TYPE_LABELS[product.type]}</Badge>
              {product.profile_type && <Badge variant="secondary" className="text-xs">{product.profile_type}</Badge>}
              {product.color && <Badge variant="secondary" className="text-xs">{product.color}</Badge>}
              {product.is_catalog_item && <Badge variant="secondary" className="text-xs bg-blue-100">Сырье (каталог)</Badge>}
              {product.is_paired_profile && <Badge variant="secondary" className="text-xs bg-purple-100">Парный</Badge>}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
