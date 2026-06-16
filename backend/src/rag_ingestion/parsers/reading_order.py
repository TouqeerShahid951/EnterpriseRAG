"""Geometry-based reading order helpers for native PDF extraction."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Callable, Sequence, TypeVar

from .models import BBox

T = TypeVar("T")


@dataclass(frozen=True)
class _Positioned:
    index: int
    bbox: BBox

    @property
    def x0(self) -> float:
        return self.bbox[0]

    @property
    def y0(self) -> float:
        return self.bbox[1]

    @property
    def x1(self) -> float:
        return self.bbox[2]

    @property
    def y1(self) -> float:
        return self.bbox[3]

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass(frozen=True)
class _PageGeometry:
    left: float
    right: float
    mid: float
    content_width: float


def page_width(page: object) -> float:
    rect = getattr(page, "rect", None)
    width = getattr(rect, "width", None)
    return float(width) if isinstance(width, (int, float)) else 0.0


def column_aware_reading_order(
    items: Sequence[T],
    *,
    bbox_for: Callable[[T], BBox | None],
    page_width_value: float = 0.0,
) -> list[T]:
    """Order items by PDF reading flow, including common two-column pages."""

    row_indexes = sorted(range(len(items)), key=lambda index: _row_key(bbox_for(items[index])))
    row_order = [items[index] for index in row_indexes]
    positioned = [_Positioned(index=index, bbox=bbox) for index, item in enumerate(items) if (bbox := bbox_for(item)) is not None]
    if len(positioned) < 4:
        return row_order
    geometry = _page_geometry(positioned, page_width_value)
    if not _looks_two_column(positioned, geometry):
        return row_order
    first_side_y = min((position.y0 for position in positioned if _side(position, geometry) in {"left", "right"}), default=0.0)
    anchors = {
        position.index
        for position in positioned
        if _is_flow_anchor(position, geometry, first_side_y)
    }
    ordered_indexes = _ordered_column_indexes(positioned, anchors, geometry)
    ordered_index_set = set(ordered_indexes)
    ordered = [items[index] for index in ordered_indexes]
    ordered.extend(items[index] for index in row_indexes if index not in ordered_index_set)
    return ordered


def _row_key(bbox: BBox | None) -> tuple[float, float]:
    if bbox is None:
        return (0.0, 0.0)
    return (round(bbox[1], 1), round(bbox[0], 1))


def _page_geometry(positioned: list[_Positioned], page_width_value: float) -> _PageGeometry:
    left = min(position.x0 for position in positioned)
    right = max(position.x1 for position in positioned)
    if page_width_value > 0:
        mid = page_width_value / 2
        content_width = max(1.0, right - left)
    else:
        content_width = max(1.0, right - left)
        mid = left + (content_width / 2)
    return _PageGeometry(left=left, right=right, mid=mid, content_width=content_width)


def _looks_two_column(positioned: list[_Positioned], geometry: _PageGeometry) -> bool:
    left = [position for position in positioned if _side(position, geometry) == "left" and not _is_wide(position, geometry)]
    right = [position for position in positioned if _side(position, geometry) == "right" and not _is_wide(position, geometry)]
    if len(left) < 2 or len(right) < 2:
        return False
    left_x = median(position.x0 for position in left)
    right_x = median(position.x0 for position in right)
    return (right_x - left_x) >= geometry.content_width * 0.25


def _ordered_column_indexes(
    positioned: list[_Positioned],
    anchors: set[int],
    geometry: _PageGeometry,
) -> list[int]:
    by_index = {position.index: position for position in positioned}
    anchor_positions = sorted((by_index[index] for index in anchors), key=lambda position: (position.y0, position.x0))
    ordered: list[int] = []
    emitted: set[int] = set()
    band_top = float("-inf")
    for anchor in anchor_positions:
        ordered.extend(_band_order(positioned, anchors, geometry, band_top, anchor.y0, emitted))
        ordered.append(anchor.index)
        emitted.add(anchor.index)
        band_top = max(band_top, anchor.y1)
    ordered.extend(_band_order(positioned, anchors, geometry, band_top, float("inf"), emitted))
    return ordered


def _band_order(
    positioned: list[_Positioned],
    anchors: set[int],
    geometry: _PageGeometry,
    top: float,
    bottom: float,
    emitted: set[int],
) -> list[int]:
    band = [
        position
        for position in positioned
        if position.index not in anchors
        and position.index not in emitted
        and position.y0 >= top
        and position.y0 < bottom
    ]
    left = sorted((position for position in band if _side(position, geometry) != "right"), key=lambda position: (position.y0, position.x0))
    right = sorted((position for position in band if _side(position, geometry) == "right"), key=lambda position: (position.y0, position.x0))
    indexes = [position.index for position in [*left, *right]]
    emitted.update(indexes)
    return indexes


def _is_flow_anchor(position: _Positioned, geometry: _PageGeometry, first_side_y: float) -> bool:
    if _is_wide(position, geometry) and position.x0 < geometry.mid < position.x1:
        return True
    centered = abs(position.center_x - geometry.mid) <= geometry.content_width * 0.12
    return centered and position.y0 < first_side_y


def _is_wide(position: _Positioned, geometry: _PageGeometry) -> bool:
    return position.width >= geometry.content_width * 0.60


def _side(position: _Positioned, geometry: _PageGeometry) -> str:
    center_margin = geometry.content_width * 0.05
    if position.center_x < geometry.mid - center_margin:
        return "left"
    if position.center_x > geometry.mid + center_margin:
        return "right"
    return "center"
