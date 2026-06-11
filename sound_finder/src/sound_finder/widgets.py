from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDrag, QPainter, QPen
from PySide6.QtWidgets import QLabel, QTableWidget, QWidget


class ResultTable(QTableWidget):
    def startDrag(self, supported_actions: Qt.DropActions) -> None:
        paths = self.selected_paths()
        if not paths:
            return

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path) for path in paths])

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)

    def selected_paths(self) -> list[str]:
        rows = sorted({index.row() for index in self.selectedIndexes()})
        paths: list[str] = []
        for row in rows:
            item = self.item(row, 0)
            if item is None:
                continue
            path = item.data(Qt.UserRole) or ""
            if path:
                paths.append(path)
        if not paths:
            current = self.current_path()
            if current:
                paths.append(current)
        return paths

    def current_path(self) -> str:
        row = self.currentRow()
        if row < 0:
            return ""
        item = self.item(row, 0)
        if item is None:
            return ""
        return item.data(Qt.UserRole) or ""


class DragFileLabel(QLabel):
    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.path = ""
        self.paths: list[str] = []
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(58)
        self.setStyleSheet(
            """
            QLabel {
                border: 1px dashed #7b8495;
                border-radius: 6px;
                color: #d7deea;
                background: #202630;
                padding: 10px;
            }
            """
        )

    def set_path(self, path: str) -> None:
        self.set_paths([path] if path else [])

    def set_paths(self, paths: list[str]) -> None:
        self.paths = [path for path in paths if path]
        self.path = self.paths[0] if self.paths else ""
        if not self.paths:
            self.setText("选择一个或多个结果后可拖拽到 Reaper")
        elif len(self.paths) == 1:
            self.setText(f"拖拽到 Reaper\n{Path(self.paths[0]).name}")
        else:
            self.setText(f"拖拽 {len(self.paths)} 个音频到 Reaper\n{Path(self.paths[0]).name} ...")

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if not self.paths:
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path) for path in self.paths])
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)


class WaveformView(QWidget):
    seekRequested = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self.peaks: list[float] = []
        self.message = "未选择音频"
        self.playback_ratio = 0.0
        self.setMinimumHeight(112)
        self.setObjectName("waveformBox")

    def set_waveform(self, peaks: list[float], message: str = "") -> None:
        self.peaks = peaks
        self.message = message or ("波形预览" if peaks else "暂无波形数据")
        self.playback_ratio = 0.0
        self.update()

    def set_playback_ratio(self, ratio: float) -> None:
        self.playback_ratio = max(0.0, min(1.0, ratio))
        self.update()

    def clear(self) -> None:
        self.set_waveform([], "未选择音频")

    def content_rect(self):
        return self.rect().adjusted(11, 11, -11, -11)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.fillRect(rect, QColor("#11161d"))

        border = QPen(QColor("#465365"))
        border.setStyle(Qt.DashLine)
        painter.setPen(border)
        painter.drawRect(rect)

        inner = self.content_rect()
        center_y = inner.center().y()
        painter.setPen(QPen(QColor("#2f3b4a")))
        painter.drawLine(inner.left(), center_y, inner.right(), center_y)

        if not self.peaks:
            painter.setPen(QColor("#8795a8"))
            painter.drawText(inner, Qt.AlignCenter, self.message)
            return

        width = max(1, inner.width())
        count = len(self.peaks)
        usable_height = max(2, inner.height() // 2)
        painter.setPen(QPen(QColor("#74c0fc")))

        for pixel in range(width + 1):
            start = int(pixel * count / max(1, width))
            end = int((pixel + 1) * count / max(1, width))
            if end <= start:
                end = start + 1
            start = min(start, count - 1)
            end = min(end, count)
            peak = max(self.peaks[start:end])
            bar = max(1, int(min(1.0, peak) * usable_height))
            x = inner.left() + pixel
            painter.drawLine(x, center_y - bar, x, center_y + bar)

        pointer_x = inner.left() + int(self.playback_ratio * max(1, inner.width()))
        painter.setPen(QPen(QColor("#ff4d4f"), 2))
        painter.drawLine(pointer_x, inner.top(), pointer_x, inner.bottom())

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if not self.peaks:
            return
        inner = self.content_rect()
        x = event.position().x()
        ratio = (x - inner.left()) / max(1, inner.width())
        ratio = max(0.0, min(1.0, ratio))
        self.set_playback_ratio(ratio)
        self.seekRequested.emit(ratio)
