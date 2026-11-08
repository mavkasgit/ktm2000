// Фото-плашка артикула: миниатюра или иконка-заглушка (общая для списка и карточки #152).
import { Image } from "lucide-react";
import { productPhotoUrl } from "./productPhotoUrl";
import { cn } from "@/shared/utils/cn";
import type { Product } from "@/shared/api/products";

export function ProductPhoto({ product, className }: { product: Product; className?: string }) {
  // Превью есть только при наличии thumb: full как заглушка в списке не нужен.
  const photoUrl = product.photo_thumb ? productPhotoUrl(product, "thumb") : null;

  return (
    <div className={cn("bg-muted rounded flex items-center justify-center overflow-hidden shrink-0", className ?? "w-10 h-10")}>
      {photoUrl ? (
        <img src={photoUrl} alt="" className="w-full h-full object-contain" />
      ) : (
        <Image className="h-5 w-5 text-muted-foreground" />
      )}
    </div>
  );
}
