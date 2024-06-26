from __future__ import annotations
import math
import pygame

from enum import IntEnum, auto


class OnboardType(IntEnum):
    PLAY = auto()
    SPECTATE = auto()

class LifecycleType(IntEnum):
    STARTING = auto()
    PLAYING = auto()
    WAITING_ROOM = auto()
    NEW_ROUND = auto()
    DONE = auto()


class ProjectileType(IntEnum):
    LASER = auto()
    #BALL = auto()
    BULLET = auto()
    SHOCKWAVE = auto()
    SNIPER = auto()
    CLUSTER = auto()


class Projectile:
    SPEED = 200  # this needs to be synced in server.Projectile.SPEED

    def __init__(self, projectile_type: ProjectileType) -> None:
        self.id = 0
        self.position: tuple[float, float] = (0, 0)
        self.start_position = (self.position[0], self.position[1])
        self._velocity: tuple[float, float] = (0, 0)
        self.sender_id = 0
        self.grace_period = 0.15
        self.projectile_type = projectile_type
        self.rotation = 0
        self.lobbed = False
        self.hurts = True
        self.radius = 0
        self.remaining_bounces = 1

        match projectile_type:
            case ProjectileType.LASER:
                self.speed = self.SPEED * 2
                self.remaining_bounces = 2
                self.cooldown = .05
            case ProjectileType.SHOCKWAVE:
                self.speed = self.SPEED * 2
                self.cooldown = .15
                self.lobbed = True
                self.radius = 64
                self.hurts = False
            case ProjectileType.SNIPER:
                self.speed = self.SPEED * 3
                self.remaining_bounces = 4
                self.cooldown = .5
            case ProjectileType.CLUSTER:
                self.speed = self.SPEED
                self.cooldown = .5
                self.lobbed = True
                self.radius = 64
            case _:
                self.speed = self.SPEED
                self.remaining_bounces = 3
                self.cooldown = .075

    @property
    def velocity(self) -> tuple[float, float]:
        return self._velocity

    @velocity.setter
    def velocity(self, vel: tuple[float, float]):
        self._velocity = vel
        x_vel, y_vel = vel
        angle = math.atan2(-y_vel, x_vel)
        degrees = math.degrees(angle)
        self.rotation = degrees % 360

    @staticmethod
    def get_cooldown(projectile_type: ProjectileType) -> float:
        return Projectile(projectile_type).cooldown

    @staticmethod
    def is_lobbed(projectile_type: ProjectileType) -> bool:
        return Projectile(projectile_type).lobbed

    @staticmethod
    def update_lobbed_projectile(projectile: Projectile, dt: float) -> None | pygame.Vector2:
        target = pygame.Vector2(projectile.velocity)  # to simplify sockets we interchange velocity with target if lobbed
        start = pygame.Vector2(projectile.position)

        distance = get_distance((start.x, start.y), (target.x, target.y))

        magnitude = projectile.speed * dt

        if distance < magnitude:
            projectile.remaining_bounces -= 1
            return target

        direction = ((target[0] - start[0]) / distance, (target[1] - start[1]) / distance)
        new_position = (start[0] + direction[0] * magnitude, start[1] + direction[1] * magnitude)

        projectile.position = new_position

    @staticmethod
    def update_projectile(projectile: Projectile, collision_list: list[pygame.Rect], dt: float) -> None | pygame.Vector2:
        x, y = projectile.position
        vel_x, vel_y = projectile.velocity

        # Calculate new potential position
        new_pos_x = x + vel_x * dt * projectile.speed
        new_pos_y = y + vel_y * dt * projectile.speed
        colided = False

        # Check for vertical collisions


        if any(pygame.Rect(x, new_pos_y, 8, 8).colliderect(rect) for rect in collision_list):
            colided = True
            # Reflect the velocity on the y-axis
            vel_y = -vel_y
            # Set new position with reflected velocity
            new_pos_y = y + vel_y * dt * Projectile.SPEED

        # Check for horizontal collisions
        if any(pygame.Rect(new_pos_x, y, 8, 8).colliderect(rect) for rect in collision_list):
            colided = True
            # Reflect the velocity on the x-axis
            vel_x = -vel_x
            # Set new position with reflected velocity
            new_pos_x = x + vel_x * dt * Projectile.SPEED

        projectile.velocity = (vel_x, vel_y)

        if colided:
            projectile.remaining_bounces -= 1
            return pygame.Vector2(projectile.position)
        projectile.position = (new_pos_x, new_pos_y)

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

def is_within_radius(center1: tuple[float, float], center2: tuple[float, float], radius: float):
    distance = math.sqrt((center1[0] - center2[0]) ** 2 + (center1[1] - center2[1]) ** 2)
    return distance <= radius

def get_distance(start: tuple[float, float], target: tuple[float, float]) -> float:
    return math.sqrt((start[0] - target[0])**2 + (start[1] - target[1])**2)

def gaussian_value(midpoint: tuple[float, float], position: tuple[float, float], sigma: float):
    distance = math.sqrt((position[0] - midpoint[0])**2 + (position[1] - midpoint[1])**2)
    value = math.exp(-distance**2 / (2 * sigma**2))
    return value
