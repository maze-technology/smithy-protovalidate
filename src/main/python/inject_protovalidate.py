#!/usr/bin/env python3

"""
inject_protovalidate.py
───────────────────────
Post-process .proto files generated by Disney's smithy-translate and add
protovalidate field options derived from Smithy traits.

Supported traits
  • @length(min/max)   → strings & lists
  • @range(min/max)    → numeric members and aliases
  • @uniqueItems       → lists

Usage:
    inject_protovalidate.py  <smithy-root-dir>  <proto-root-dir>
"""

from __future__ import annotations
import pathlib, re, sys, textwrap
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

# ─────────────────────────────── CLI ─────────────────────────────────────────
if len(sys.argv) != 3:
  sys.exit("Usage: inject_protovalidate.py <smithy-root-dir> <proto-root-dir>")

SMITHY_ROOT = pathlib.Path(sys.argv[1]).resolve()
PROTO_ROOT  = pathlib.Path(sys.argv[2]).resolve()

# ───────────────── Trait model ───────────────────────────────────────────────
@dataclass
class Constraints:
  str_min: Optional[str] = None
  str_max: Optional[str] = None
  num_min: Optional[str] = None
  num_max: Optional[str] = None
  rep_min: Optional[str] = None
  rep_max: Optional[str] = None
  unique : bool          = False

  def merge(self, other: "Constraints") -> "Constraints":
    return Constraints(
      str_min = other.str_min or self.str_min,
      str_max = other.str_max or self.str_max,
      num_min = other.num_min or self.num_min,
      num_max = other.num_max or self.num_max,
      rep_min = other.rep_min or self.rep_min,
      rep_max = other.rep_max or self.rep_max,
      unique  = self.unique or other.unique,
    )

  def __bool__(self) -> bool:
    return any((
      self.str_min, self.str_max,
      self.num_min, self.num_max,
      self.rep_min, self.rep_max,
      self.unique,
    ))

# ──────────────── Regex helpers ──────────────────────────────────────────────
RE_STRUCT        = re.compile(r"\bstructure\s+(\w+)\s*{", re.I)
RE_TRAIT         = re.compile(r"@\w+[^@{}]*")
RE_STRING_ALIAS  = re.compile(r"\bstring\s+(\w+)\b", re.I)
RE_LIST_ALIAS    = re.compile(r"\blist\s+(\w+)\s*{", re.I)

MEMBER_RX = re.compile(
  r'(?:\s*(?P<traits>(?:@\w+[^\n]*\n\s*)*))'   # 0-n trait lines
  r'\s*(?P<name>\w+)\s*:\s*(?P<target>\w+)',   # member line
  re.M,
)

MSG_RX   = re.compile(r"^\s*message\s+(\w+)\s*{", re.I)
FIELD_RX = re.compile(
  r"^\s*(repeated\s+|optional\s+)?(\w+)\s+(\w+)\s*=\s*(\d+)([^;]*);", re.I
)

# ──────────────── Trait extraction helpers ──────────────────────────────────
def _pick(blob: str, key: str) -> Optional[str]:
  m = re.search(fr"\b{key}\s*:\s*(-?[0-9]+(?:\.[0-9]+)?)", blob)
  return m.group(1) if m else None

def gather_constraints(trait_block: str) -> Constraints:
  c = Constraints()
  for trait in RE_TRAIT.findall(trait_block):
    if trait.startswith("@length"):
      inner = trait[8:].strip("()")
      c.str_min = _pick(inner, "min") or c.str_min
      c.str_max = _pick(inner, "max") or c.str_max
      c.rep_min = _pick(inner, "min") or c.rep_min
      c.rep_max = _pick(inner, "max") or c.rep_max
    elif trait.startswith("@range"):
      inner = trait[7:].strip("()")
      c.num_min = _pick(inner, "min") or c.num_min
      c.num_max = _pick(inner, "max") or c.num_max
    elif trait.startswith("@uniqueItems"):
      c.unique = True
  return c

# ──────────────── Pass 1 – alias-level constraints ──────────────────────────
alias_constraints: Dict[str, Constraints] = {}

for sm in SMITHY_ROOT.rglob("*.smithy"):
  txt = sm.read_text()

  # string aliases (traits live *before* the alias line)
  for m in RE_STRING_ALIAS.finditer(txt):
    alias_constraints[m.group(1)] = gather_constraints(txt[:m.start()])

  # list aliases (traits can be before *and/or* **inside** the block)
  for m in RE_LIST_ALIAS.finditer(txt):
    alias = m.group(1)
    brace_open = txt.find("{", m.end() - 1)
    brace_close = txt.find("}", brace_open)
    block = txt[m.start(): brace_close + 1] if brace_close != -1 else txt[m.start():]
    alias_constraints[alias] = gather_constraints(block)

# ──────────────── Pass 2 – member-level constraints ─────────────────────────
member_constraints: Dict[Tuple[str, str], Constraints] = {}

for sm in SMITHY_ROOT.rglob("*.smithy"):
  txt = sm.read_text()
  for st in RE_STRUCT.finditer(txt):
    struct = st.group(1)
    body   = txt[st.end(): txt.find("}", st.end())]
    for mem in MEMBER_RX.finditer(body):
      traits  = mem.group("traits") or ""
      name    = mem.group("name")
      target  = mem.group("target")

      cons = gather_constraints(traits)
      if target in alias_constraints:
        cons = alias_constraints[target].merge(cons)

      if cons:
        member_constraints[(struct, name)] = cons

# ──────────────── Option string builder ─────────────────────────────────────
def build_option(ftype: str, repeated: bool, c: Constraints) -> str:
  attrs: list[str] = []

  if repeated:
    if c.rep_min: attrs.append(f"repeated.min_items = {c.rep_min}")
    if c.rep_max: attrs.append(f"repeated.max_items = {c.rep_max}")
    if c.unique:  attrs.append("repeated.unique = true")

  elif ftype == "string":
    if c.str_min: attrs.append(f"string.min_len = {c.str_min}")
    if c.str_max: attrs.append(f"string.max_len = {c.str_max}")

  else:  # numeric groups
    cat = ("double" if ftype == "double"
           else "float"  if ftype == "float"
           else "int64"  if ftype.endswith("64")
           else "int32")
    if c.num_min: attrs.append(f"{cat}.gte = {c.num_min}")
    if c.num_max: attrs.append(f"{cat}.lte = {c.num_max}")

  if not attrs:
    return ""

  if len(attrs) == 1:
    return f" [((buf.validate.field).{attrs[0]})]".replace("((", "(")

  lined = ",\n  ".join(f"(buf.validate.field).{a}" for a in attrs)
  return f" [\n  {lined}\n]"

# ───────────────── Proto patching ───────────────────────────────────────────
patched_fields = total_proto = 0
IMPORT_RX = re.compile(r'\s*import\s+"buf/validate/validate\.proto";')

for proto in PROTO_ROOT.rglob("*.proto"):
  total_proto += 1
  lines = proto.read_text().splitlines()
  dirty = False
  ctx   = None

  for i, line in enumerate(lines):
    if (m := MSG_RX.match(line)):
      ctx = m.group(1)
      continue

    m = FIELD_RX.match(line)
    if not (ctx and m):
      continue

    rep_kw, ftype, fname, _tag, tail = m.groups()
    repeated = (rep_kw or "").strip() == "repeated"
    if "buf.validate.field" in tail:
      continue

    cons = member_constraints.get((ctx, fname))
    if not cons:
      continue

    option = build_option(ftype, repeated, cons)
    if not option:
      continue

    lines[i] = line.rstrip(";") + option + ";"
    dirty = True
    patched_fields += 1

  # normalise & deduplicate import lines
  imports = [idx for idx, l in enumerate(lines) if IMPORT_RX.fullmatch(l)]
  if imports:
    first = imports[0]
    lines[first] = 'import "buf/validate/validate.proto";'
    for idx in reversed(imports[1:]):
      del lines[idx]
  elif dirty:  # need to add one
    insert_at = (
      2 if len(lines) > 1 and lines[0].startswith("syntax")
           and lines[1].startswith("package")
      else 1
    )
    lines.insert(insert_at, 'import "buf/validate/validate.proto";')

  if dirty or imports:
    proto.write_text("\n".join(lines))

print(textwrap.dedent(f"""
  Patched {patched_fields} field(s)
  across  {total_proto} .proto file(s).
""").strip())
