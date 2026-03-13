from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    class Undefined: pass

@dataclass
class Foo:
    x: Undefined | None = None

print("Dataclass defined successfully")
