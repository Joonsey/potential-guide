import math
import pygame

from enum import IntEnum, auto


class LifecycleType(IntEnum):
    STARTING = auto()
    PLAYING = auto()
    WAITING_ROOM = auto()
    NEW_ROUND = auto()
    DONE = auto()


class ProjectileType(IntEnum):
    LASER = auto()
    BALL = auto()
    BULLET = auto()


class Projectile:
    SPEED = 200  # this needs to be synced in server.Projectile.SPEED

    def __init__(self, projectile_type: ProjectileType) -> None:
        self.id = 0
        self.position: tuple[float, float] = (0, 0)
        self._velocity: tuple[float, float] = (0, 0)
        self.sender_id = 0
        self.grace_period = 0.1
        self.projectile_type = projectile_type
        self.rotation = 0

        match projectile_type:
            case ProjectileType.LASER:
                self.speed = self.SPEED * 2
                self.remaining_bounces = 1
            case _:
                self.speed = self.SPEED
                self.remaining_bounces = 2

    @property
    def velocity(self) -> tuple[float, float]:
        return self._velocity

    @velocity.setter
    def velocity(self, vel: tuple[float, float]):
        self._velocity = vel
        x_vel, y_vel = vel
        angle = math.atan2(-y_vel, x_vel)
        degrees = math.degrees(angle)
        self.rotation = (degrees + 360) % 360


def check_collision(rect: tuple[float, float, float, float], other_rect: tuple[float, float, float, float]) -> bool:
    x1, y1, w1, h1 = rect
    x2, y2, w2, h2 = other_rect

    overlap_x = (x1 < x2 + w2) and (x2 < x1 + w1)
    overlap_y = (y1 < y2 + h2) and (y2 < y1 + h1)
    return overlap_x and overlap_y


def lerp(a: float, b: float, f: float):
    return a * (1.0 - f) + (b * f)


def inverted(img: pygame.Surface):
   inv = pygame.Surface(img.get_rect().size, pygame.SRCALPHA)
   inv.fill((255, 255, 255, 255))
   inv.blit(img, (0, 0), None, pygame.BLEND_RGB_SUB)
   return inv


def outline(surf: pygame.Surface, dest: pygame.Surface, loc: tuple[int, int], depth: int = 1) -> None:
    temp_surf = surf.copy()
    inverted_surf = inverted(temp_surf)
    inverted_surf.set_colorkey((255, 255, 255))
    dest.blit(inverted_surf, (loc[0]-depth, loc[1]))
    dest.blit(inverted_surf, (loc[0]+depth, loc[1]))
    dest.blit(inverted_surf, (loc[0], loc[1]-depth))
    dest.blit(inverted_surf, (loc[0], loc[1]+depth))
    temp_surf.set_colorkey((0, 0, 0))
    dest.blit(temp_surf, (0, 0))


def render_stack(surf: pygame.Surface, images: list[pygame.Surface], pos: pygame.Vector2, rotation: int):
    count = len(images)
    for i, img in enumerate(images):
        rotated_img = pygame.transform.rotate(img, rotation)
        surf.blit(rotated_img, (pos.x - rotated_img.get_width() // 2 +
                  count, pos.y - rotated_img.get_height() // 2 - i + count))
