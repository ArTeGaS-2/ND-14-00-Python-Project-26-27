import math
import random

from PyQt6.QtCore import QPointF, QTimer
from PyQt6.QtGui import QColor, QPaintEvent, QPainter, QRadialGradient
from PyQt6.QtWidgets import QWidget


class AnimatedBackground(QWidget):
    """Темний фон із повільними неоновими переливами та частинками."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("animatedBackground")
        self._phase = 0.0
        self._particles: list[list[float]] = []

        for _ in range(42):
            self._particles.append(
                [
                    random.random(),
                    random.random(),
                    random.uniform(-0.00012, 0.00012),
                    random.uniform(-0.00012, 0.00012),
                    random.uniform(1.0, 2.2),
                    random.uniform(45.0, 100.0),
                    random.randrange(3),
                ]
            )

        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._advance_animation)
        self._animation_timer.start(40)

    def _advance_animation(self) -> None:
        self._phase += 0.008
        for particle in self._particles:
            particle[0] = (particle[0] + particle[2]) % 1.0
            particle[1] = (particle[1] + particle[3]) % 1.0
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#11141c"))

        width = self.width()
        height = self.height()
        glow_radius = max(width, height) * 0.62
        phase = self._phase

        self._draw_glow(
            painter,
            QPointF(width * (0.25 + 0.08 * math.sin(phase)), height * 0.30),
            glow_radius,
            (36, 190, 190),
            48,
        )
        self._draw_glow(
            painter,
            QPointF(width * (0.72 + 0.07 * math.cos(phase * 0.8)), height * 0.70),
            glow_radius,
            (126, 79, 205),
            43,
        )
        self._draw_glow(
            painter,
            QPointF(width * 0.52, height * (0.38 + 0.08 * math.sin(phase * 0.65))),
            glow_radius * 0.8,
            (44, 112, 190),
            30,
        )

        particle_colors = (
            (115, 225, 225),
            (175, 145, 255),
            (125, 175, 245),
        )
        painter.setPen(QColor(0, 0, 0, 0))
        for x, y, _dx, _dy, radius, opacity, color_index in self._particles:
            pulse = 0.75 + 0.25 * math.sin(phase * 2 + x * 12 + y * 8)
            red, green, blue = particle_colors[int(color_index)]
            painter.setBrush(QColor(red, green, blue, int(opacity * pulse)))
            painter.drawEllipse(
                QPointF(x * width, y * height),
                radius,
                radius,
            )

    @staticmethod
    def _draw_glow(
        painter: QPainter,
        center: QPointF,
        radius: float,
        color: tuple[int, int, int],
        opacity: int,
    ) -> None:
        red, green, blue = color
        gradient = QRadialGradient(center, radius)
        gradient.setColorAt(0.0, QColor(red, green, blue, opacity))
        gradient.setColorAt(0.55, QColor(red, green, blue, opacity // 3))
        gradient.setColorAt(1.0, QColor(red, green, blue, 0))
        painter.setPen(QColor(0, 0, 0, 0))
        painter.setBrush(gradient)
        painter.drawEllipse(center, radius, radius)
