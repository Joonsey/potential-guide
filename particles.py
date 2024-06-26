
import math
import pygame

from settings import RIPPLE_LIFETIME, SCREEN_HEIGHT, SCREEN_WIDTH, SPARK_LIFETIME, TRACK_LIFETIME


class Particle:
    def __init__(self) -> None:
        self.lifetime = RIPPLE_LIFETIME  # FIXME

    def update(self, dt: float) -> None:
        self.lifetime = max(0, self.lifetime - dt)

    def draw(self, screen: pygame.Surface) -> None:
        ...


class Spark(Particle):
    def __init__(self, pos: pygame.Vector2, angle, color, scale: float = 1, force: float = 1):
        super().__init__()
        self.lifetime: float = SPARK_LIFETIME
        self.pos = pos
        self.angle = angle
        self.scale = scale
        self.color = color
        self.force = force

    def calculate_movement(self, dt):
        return [math.cos(self.angle) * self.lifetime * dt * self.force, math.sin(self.angle) * self.lifetime * dt * self.force]

    def update(self, dt):
        super().update(dt)
        movement = self.calculate_movement(dt * 20)
        self.pos.x += movement[0]
        self.pos.y += movement[1]

        self.lifetime = max(0, self.lifetime - 2 * dt)

    def draw(self, screen: pygame.Surface):
        points = [
            [self.pos.x + math.cos(self.angle) * self.lifetime * self.scale,
             self.pos.y + math.sin(self.angle) * self.lifetime * self.scale],
            [self.pos.x + math.cos(self.angle + math.pi / 2) * self.lifetime * self.scale * 0.3,
             self.pos.y + math.sin(self.angle + math.pi / 2) * self.lifetime * self.scale * 0.3],
            [self.pos.x - math.cos(self.angle) * self.lifetime * self.scale * 3.5,
             self.pos.y - math.sin(self.angle) * self.lifetime * self.scale * 3.5],
            [self.pos.x + math.cos(self.angle - math.pi / 2) * self.lifetime * self.scale * 0.3,
             self.pos.y - math.sin(self.angle + math.pi / 2) * self.lifetime * self.scale * 0.3],
        ]
        pygame.draw.polygon(screen, self.color, points)  # pyright: ignore
        pygame.draw.polygon(screen, (255, 255, 255),
                            points, 1)  # pyright: ignore


class Ripple(Particle):
    def __init__(self, pos: pygame.Vector2, max_radius: float, force: float = 1, width: int = 3, color: pygame.Color = pygame.Color(222, 120, 22, 128)) -> None:
        self.lifetime: float = RIPPLE_LIFETIME
        self.position = pos
        self.color = color
        self.max_radius = max_radius
        self.width = width
        self.force = force

    def update(self, dt: float) -> None:
        super().update(dt)

    def draw(self, screen: pygame.Surface) -> None:
        rad = self.radius * 2
        ratio = 7 / 10
        pygame.draw.ellipse(screen, self.color, (self.position.x -
                            rad / 2, self.position.y - rad / 2, rad, rad * ratio), self.width)

    @property
    def radius(self) -> float:
        return self.max_radius * self.force * (1 - self.lifetime / RIPPLE_LIFETIME)


