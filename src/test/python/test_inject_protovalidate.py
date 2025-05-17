"""
End-to-end tests for inject_protovalidate.py (pytest).

Run:  pytest -q
"""

from __future__ import annotations
import subprocess, sys, tempfile
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[2] / "main/python/inject_protovalidate.py").as_posix()

# ---------------------------------------------------------------------------
def _write(p: Path, text: str) -> None:
  p.parent.mkdir(parents=True, exist_ok=True)
  p.write_text(text, encoding="utf-8")

def _make_env(model: str, proto: str) -> tuple[Path, Path]:
  tmp = Path(tempfile.mkdtemp())
  sroot = tmp / "smithy"
  proot = tmp / "proto"
  _write(sroot / "model.smithy", model)
  _write(proot / "model.proto", proto)
  return sroot, proot

def _run(sroot: Path, proot: Path) -> None:
  subprocess.run(
    [sys.executable, SCRIPT, sroot.as_posix(), proot.as_posix()],
    check=True,
    text=True,
  )

# ---------------------------------------------------------------------------
def test_string_length_min_max():
  smithy = """
    namespace demo
    structure Msg {
      @length(min: 1, max: 100)
      content: String
    }
  """
  proto = """
    syntax = "proto3";
    message Msg {
      string content = 1;
    }
  """
  sroot, proot = _make_env(smithy, proto)
  _run(sroot, proot)
  out = (proot / "model.proto").read_text()

  assert "(buf.validate.field).string.min_len = 1" in out
  assert "(buf.validate.field).string.max_len = 100" in out
  # ensure there is NO bare “string.max_len” before the prefixed one
  head = out.split("(buf.validate.field).string.max_len")[0]
  assert "string.max_len" not in head


def test_numeric_range():
  smithy = """
    namespace demo
    structure Thermometer {
      @range(min: -40, max: 150)
      value: Integer
    }
  """
  proto = """
    syntax = "proto3";
    message Thermometer {
      int32 value = 1;
    }
  """
  sroot, proot = _make_env(smithy, proto)
  _run(sroot, proot)
  out = (proot / "model.proto").read_text()

  assert "(buf.validate.field).int32.gte = -40" in out
  assert "(buf.validate.field).int32.lte = 150" in out


def test_list_length_and_unique():
  smithy = """
    namespace demo
    list IdList {
      @length(min: 1, max: 10)
      @uniqueItems
      member: String
    }

    structure Bag {
      ids: IdList
    }
  """
  proto = """
    syntax = "proto3";
    message Bag {
      repeated string ids = 1;
    }
  """
  sroot, proot = _make_env(smithy, proto)
  _run(sroot, proot)
  out = (proot / "model.proto").read_text()

  assert "(buf.validate.field).repeated.min_items = 1" in out
  assert "(buf.validate.field).repeated.max_items = 10" in out
  assert "(buf.validate.field).repeated.unique = true" in out


def test_import_inserted_once():
  smithy = """
    namespace demo
    structure Msg {
      @length(max: 5)
      txt: String
    }
  """
  proto = '''
    syntax = "proto3";
    import "buf/validate/validate.proto";

    message Msg {
      string txt = 1;
    }
  '''
  sroot, proot = _make_env(smithy, proto)
  _run(sroot, proot)
  lines = (proot / "model.proto").read_text().splitlines()
  imports = [l for l in lines if l.strip() == 'import "buf/validate/validate.proto";']
  assert len(imports) == 1
