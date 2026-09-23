/** Display labels aligned with address-book / identity-access model. */

export const SITE_OPTIONS = [
  { value: "taiyuan", label: "太原" },
  { value: "shuozhou", label: "朔州" },
  { value: "suzhou", label: "苏州" },
];

export const SITE_LABEL = Object.fromEntries(SITE_OPTIONS.map((s) => [s.value, s.label]));

export const ORG_TYPE_OPTIONS = [
  { value: "company", label: "公司" },
  { value: "office", label: "办" },
  { value: "center", label: "中心" },
  { value: "dept", label: "部门/组" },
  { value: "committee", label: "委员会" },
];

export const ORG_TYPE_LABEL = Object.fromEntries(ORG_TYPE_OPTIONS.map((t) => [t.value, t.label]));

export const CLEARANCE_OPTIONS = [
  { value: "general", label: "一般" },
  { value: "core", label: "核心" },
];

export const CLEARANCE_LABEL = Object.fromEntries(CLEARANCE_OPTIONS.map((c) => [c.value, c.label]));

export function siteLabel(code) {
  return SITE_LABEL[code] || code || "—";
}

export function clearanceLabel(code) {
  return CLEARANCE_LABEL[code] || code || "—";
}

export function orgTypeLabel(type) {
  return ORG_TYPE_LABEL[type] || type || "—";
}

/** Depth-first order with indent level for tree display / selects. */
export function orderOrgUnitsTree(orgUnits) {
  const byParent = new Map();
  for (const unit of orgUnits) {
    const key = unit.parent_id || "";
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key).push(unit);
  }
  for (const list of byParent.values()) {
    list.sort((a, b) => String(a.code).localeCompare(String(b.code)));
  }
  const out = [];
  const walk = (parentId, depth) => {
    const kids = byParent.get(parentId || "") || [];
    for (const unit of kids) {
      out.push({ unit, depth });
      walk(unit.id, depth + 1);
    }
  };
  walk("", 0);
  // Orphans (parent missing from list) — append flat
  const seen = new Set(out.map((x) => x.unit.id));
  for (const unit of orgUnits) {
    if (!seen.has(unit.id)) out.push({ unit, depth: 0 });
  }
  return out;
}

export function orgOptionLabel(unit, depth = 0) {
  const pad = depth > 0 ? `${"—".repeat(depth)} ` : "";
  return `${pad}${unit.name}（${unit.code}）`;
}
