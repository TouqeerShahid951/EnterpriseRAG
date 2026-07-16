"""Connected-component detection for rendered PDF page masks."""

from __future__ import annotations


def connected_foreground_components(
    mask: object,
) -> list[tuple[int, int, int, int, int]]:
    width, height = mask.size
    data = mask.tobytes()
    visited = bytearray(len(data))
    components: list[tuple[int, int, int, int, int]] = []
    for index, value in enumerate(data):
        if value == 0 or visited[index]:
            continue
        stack = [index]
        visited[index] = 1
        min_x = max_x = index % width
        min_y = max_y = index // width
        count = 0
        while stack:
            current = stack.pop()
            count += 1
            x = current % width
            y = current // width
            if x < min_x:
                min_x = x
            elif x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            elif y > max_y:
                max_y = y
            for neighbor in foreground_neighbors(current, x, y, width, height):
                if not visited[neighbor] and data[neighbor] != 0:
                    visited[neighbor] = 1
                    stack.append(neighbor)
        components.append((min_x, min_y, max_x + 1, max_y + 1, count))
    return components


def foreground_neighbors(
    index: int, x: int, y: int, width: int, height: int
) -> tuple[int, ...]:
    neighbors: list[int] = []
    if x > 0:
        neighbors.append(index - 1)
    if x + 1 < width:
        neighbors.append(index + 1)
    if y > 0:
        neighbors.append(index - width)
    if y + 1 < height:
        neighbors.append(index + width)
    return tuple(neighbors)
