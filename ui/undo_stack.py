"""Full undo/redo stack for canvas state."""
import copy
import time
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CanvasState:
    polygons: list
    current_points: list
    timestamp: float = field(default_factory=time.time)


class UndoStack:
    def __init__(self, max_size: int = 100):
        self._stack: List[CanvasState] = []
        self._index: int = -1
        self._max = max_size

    def push(self, state: CanvasState) -> None:
        # Discard any redo history
        if self._index < len(self._stack) - 1:
            self._stack = self._stack[:self._index + 1]
        self._stack.append(state)
        if len(self._stack) > self._max:
            self._stack.pop(0)
        self._index = len(self._stack) - 1

    def undo(self) -> Optional[CanvasState]:
        if self._index > 0:
            self._index -= 1
            return copy.deepcopy(self._stack[self._index])
        return None

    def redo(self) -> Optional[CanvasState]:
        if self._index < len(self._stack) - 1:
            self._index += 1
            return copy.deepcopy(self._stack[self._index])
        return None

    def can_undo(self) -> bool:
        return self._index > 0

    def can_redo(self) -> bool:
        return self._index < len(self._stack) - 1

    def clear(self) -> None:
        self._stack.clear()
        self._index = -1
