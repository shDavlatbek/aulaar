"""Known AULA products and how to find their configuration interface."""

from __future__ import annotations

from dataclasses import dataclass

from . import hidraw
from .protocol import evision

VENDOR_ID = 0x320F


@dataclass(frozen=True)
class Product:
    pid: int
    name: str
    link: int  # evision.WIRED / evision.WIRELESS
    backend: str = "evision"

    @property
    def is_receiver(self) -> bool:
        return self.link == evision.WIRELESS


PRODUCTS = {
    p.pid: p
    for p in (
        Product(0x22A0, "AULA 8K Dongle", evision.WIRELESS),
        Product(0x22BA, "AULA 2.4G Dongle", evision.WIRELESS),
        Product(0x22B6, "AULA X9 series", evision.WIRED),
        Product(0x22B7, "AULA V9+ series", evision.WIRED),
        Product(0x22B8, "AULA V9 series", evision.WIRED),
    )
}


@dataclass(frozen=True)
class Model:
    name: str
    has_body_lighting: bool = True


# Base-info byte 7 ("configId") → model. Several models share one USB product ID.
MODELS = {
    0: Model("AULA X9 Pro", has_body_lighting=False),
    1: Model("AULA X9", has_body_lighting=False),
    2: Model("AULA X9 Ultra", has_body_lighting=False),
    3: Model("AULA V9+"),
    4: Model("AULA V9 Pro+"),
    5: Model("AULA V9 Ultra+"),
    6: Model("AULA V9"),
    7: Model("AULA V9 Pro"),
    8: Model("AULA V9 Ultra"),
    9: Model("AULA V9 Max+"),
    10: Model("AULA V9 Max"),
    11: Model("AULA X9 Max", has_body_lighting=False),
}


def model_for(config_id: int | None) -> Model | None:
    return MODELS.get(config_id) if config_id is not None else None


@dataclass(frozen=True)
class Found:
    node: hidraw.HidrawNode
    product: Product


def find(nodes: list[hidraw.HidrawNode] | None = None) -> list[Found]:
    """Every connected AULA config interface we know how to drive."""
    if nodes is None:
        nodes = hidraw.enumerate_nodes()
    found = []
    for node in nodes:
        product = PRODUCTS.get(node.pid) if node.vid == VENDOR_ID else None
        if product and node.has_collection(evision.USAGE_PAGE, evision.USAGE):
            found.append(Found(node, product))
    return found
