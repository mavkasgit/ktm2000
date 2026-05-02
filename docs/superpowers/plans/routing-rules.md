# Routing Rules for Anodized Aluminum Profile Production

## Default MVP Route

WH → [DRILL | PRESS | ничего] → SHOT → ANOD → SAW → PACK

### Step-by-Step

1. **WH** (Склад) — Always first. Material issuance.
2. **DRILL** or **PRESS** — Alternative first production steps. Some articles skip both.
3. **SHOT** — Currently treated as default required, but future per-article routes may skip it.
4. **ANOD** — Always required. Anodization.
5. **SAW** — Always required. Cutting to length.
6. **PACK** — Always required. Packaging.

## Important Design Decisions

- **Do NOT hard-code SHOT as globally mandatory.**
  - Current behavior: SHOT is included by default.
  - Future behavior: per-article route configuration can omit SHOT.
  
- **DRILL and PRESS are alternatives, not sequential.**
  - An article uses either DRILL or PRESS as the first production step, or skips both.
  
- **Skipped operations = absence of route step, not a fake "SKIP" section.**
  - Never create a "SKIP" or "NONE" section in the database.
  
- **Section.obligatory does not exist.**
  - Obligatoriness is a property of the article-route-step relationship, not the section itself.
  - Future model: `article_route_steps(article_id, step_order, section_code, is_optional)`.

## Operations from Plan → Route Steps Mapping

| Excel Operation | Route Step |
|----------------|------------|
| окно | PRESS → ANOD → SAW → PACK |
| гребенка | PRESS → DRILL → ANOD → SAW → PACK |
| сверло | PRESS → DRILL → ANOD → SAW → PACK |
| клей | PRESS → ANOD → SAW → PACK |
| рассеиватель | PRESS → ANOD → SAW → PACK |

Note: For MVP, SHOT is inserted before ANOD for all routes.
