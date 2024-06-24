import time
import pygame
import threading
import sys
import math

from arena import Arena
from assets import AssetLoader
from packet import LifecycleType
from server import Server
from client import Client, Event, EventType, Projectile
from client import Player as ClientPlayer

DISPLAY_WIDTH, DISPLAY_HEIGHT = 1080, 720
SCREEN_WIDTH, SCREEN_HEIGHT = 600, 420
FONT_SIZE = 32


pygame.mixer.init()

VOLUME = .15

HIT_SOUND = pygame.mixer.Sound('assets/hit_1.wav')
EXPLOSION_SOUND = pygame.mixer.Sound('assets/explosion.wav')

HIT_SOUND.set_volume(VOLUME)
EXPLOSION_SOUND.set_volume(VOLUME)


def lerp(a: float, b: float, f: float):
    return a * (1.0 - f) + (b * f)


def render_stack(surf: pygame.Surface, images: list[pygame.Surface], pos: pygame.Vector2, rotation: int):
    count = len(images)
    half_count = count // 2
    for i, img in enumerate(images):
        rotated_img = pygame.transform.rotate(img, rotation)
        surf.blit(rotated_img, (pos.x - rotated_img.get_width() // 2, pos.y - rotated_img.get_height() // 2 - i + half_count))


class Player:
    SPEED = 100
    ROTATION_SPEED = 90

    def __init__(self, sprites: list[pygame.Surface], barrel_sprites: list[pygame.Surface]) -> None:
        self.position = pygame.Vector2()
        self.rotation = 0
        self.barrel_rotation: float = 0
        self.alive = True

        self.sprites = sprites
        self.barrel_sprites = barrel_sprites

    def handle_input(self, keys, collision_list: list[pygame.Rect], dt: float) -> None:
        # TODO: refactor
        rotation_speed = self.ROTATION_SPEED * dt

        rad = math.radians(self.rotation)
        vel_x, vel_y = math.sin(rad), -math.cos(rad)
        velocity = self.SPEED * dt

        if keys[pygame.K_a]:
            self.rotation -= rotation_speed
        if keys[pygame.K_d]:
            self.rotation += rotation_speed

        start_pos = self.position.copy()

        if keys[pygame.K_w]:
            self.position.y += vel_y * velocity
            self.position.x += vel_x * velocity

        if keys[pygame.K_s]:
            self.position.y -= vel_y * velocity
            self.position.x -= vel_x * velocity

        for rect in collision_list:
            if self.check_collision(rect):
                self.position = start_pos


    def check_collision(self, other_rect: pygame.Rect) -> bool:
        rect = pygame.Rect(
            self.position.x, self.position.y,
            16, 16
        )

        return rect.colliderect(other_rect)

    def draw(self, screen: pygame.Surface):
        # TODO: collisions are weird now because of the rotation of the sprite
        render_stack(screen, self.sprites, self.position, -self.rotation)

        barrel_pos = self.position.copy()
        barrel_pos.y -= 4
        render_stack(screen, self.barrel_sprites, barrel_pos, int(self.barrel_rotation))


class UI:
    def __init__(self, ui_screen: pygame.Surface) -> None:
        self.ui_screen = ui_screen
        self.font_size = FONT_SIZE
        self.font = pygame.font.Font(None, self.font_size)
        self.new_room_font = pygame.font.Font(None, 72)

    def draw(self, players: list[ClientPlayer], lifecycle_state: LifecycleType, context: int) -> None:
        position_map = [
            {"topleft": (10, 10)},
            {"topright": (SCREEN_WIDTH - 10, 10)}
        ]
        for i, player in enumerate(players[:2]):
            player_text = self.font.render(
                f"Player {player.id}: {player.score}", True, (0, 0, 0))

            # Calculate text positions
            rect = player_text.get_rect(**position_map[i])

            # Blit texts onto the screen
            self.ui_screen.blit(player_text, rect)

        #  TODO: this is not really 'UI' should be moved
        if lifecycle_state in [LifecycleType.NEW_ROUND, LifecycleType.STARTING]:
            now = time.time()
            countdown = int(context - now)
            text = self.new_room_font.render(f"{countdown}", True, (0, 0, 0))
            rect = text.get_rect(topleft=(
                DISPLAY_WIDTH  // 2 - text.get_width() // 2, DISPLAY_HEIGHT // 2 - text.get_height() // 2))

            self.ui_screen.blit(text, rect)


class Game:
    SHOOT_COOLDOWN = .05

    def __init__(self) -> None:
        self.client = Client()
        self.asset_loader = AssetLoader()
        self.screen = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.display = pygame.display.set_mode((DISPLAY_WIDTH, DISPLAY_HEIGHT))

        tank_sprites = self.asset_loader.sprite_sheets['tank']
        tank_barrel_sprites = self.asset_loader.sprite_sheets['tank-barrel']

        self.player = Player(tank_sprites, tank_barrel_sprites)
        self.player.position = pygame.Vector2(
            SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        self.ui = UI(self.display)
        self.shoot_cooldown = 0
        self.running = False

        # TODO: REFACTOR
        self.arena = Arena('arena', (SCREEN_WIDTH, SCREEN_HEIGHT))

    def run_local(self) -> None:
        s = Server()
        threading.Thread(target=s.start, daemon=True)

        self.run()

    def draw_player(self, player: ClientPlayer) -> None:
        if player.old_position:
            pos_x = lerp(
                player.old_position[0], player.position[0], player.interpolation_t)
            pos_y = lerp(
                player.old_position[1], player.position[1], player.interpolation_t)
            player.interpolation_t = min(player.interpolation_t + .20, 1)
            position = pos_x, pos_y
        else:
            position = player.position

        vec_pos = pygame.Vector2(position)
        # TODO: collisions are weird now because of the rotation of the sprite
        render_stack(
            self.screen,
            self.asset_loader.sprite_sheets['tank'],
            vec_pos,
            -player.rotation
        )
        barrel_pos = vec_pos.copy()
        barrel_pos.y -= 4
        render_stack(
            self.screen,
            self.asset_loader.sprite_sheets['tank-barrel'],
            barrel_pos,
            int(player.barrel_rotation))

    def draw_arena(self) -> None:
        for tile in self.arena.tiles:
            if tile.tile_type == "#":
                surf = pygame.Surface((tile.width, tile.height))
                surf.fill((255, 255, 255))
                self.screen.blit(surf, tile.position)

    def draw_projectile(self, position: tuple[float, float], rotation: float) -> None:
        render_stack(
            self.screen,
            self.asset_loader.sprite_sheets['bullet-lazer'],
            pygame.Vector2(position),
            int(rotation)
        )

    def update_projectile(self, projectile: Projectile, collision_list: list[pygame.Rect], dt: float) -> None:
        x, y = projectile.position
        vel_x, vel_y = projectile.velocity

        # Calculate new potential position
        new_pos_x = x + vel_x * dt * Projectile.SPEED
        new_pos_y = y + vel_y * dt * Projectile.SPEED
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

        if colided:
            if projectile.remaining_bounces == 0:
                self.client.projectiles.remove(projectile)
                return
            projectile.remaining_bounces -= 1

        projectile.position = (new_pos_x, new_pos_y)
        projectile.velocity = (vel_x, vel_y)

    def handle_event(self, event: Event) -> None:
        if event.event_type == EventType.FORCE_MOVE:
            self.player.position.x = event.data[0]
            self.player.position.y = event.data[1]
            self.player.rotation = event.data[2]
            self.player.barrel_rotation = event.data[3]

        elif event.event_type == EventType.HIT:
            _, hit_id = event.data

            if hit_id == self.client.id:
                EXPLOSION_SOUND.play()
                self.player.alive = False

        elif event.event_type == EventType.RESSURECT:
            self.player.alive = True

    def shoot(self, velocity: tuple[float, float]) -> None:
        pos = self.player.position
        self.client.send_shoot((pos.x, pos.y), velocity)

    def run(self, address: str = "127.0.0.1") -> None:
        self.clock = pygame.Clock()
        self.client.connect(address)
        self.client.start()
        self.running = True

        while self.running:
            dt = self.clock.tick(120) / 1000
            self.screen.fill((128, 128, 128))
            self.draw_arena()


            event_queue = self.client.event_queue.copy()
            if event_queue:
                event = event_queue.pop()
                self.handle_event(event)
                self.client.event_queue = event_queue
            # We get them here every frame
            # Might not need to
            # Keep it for no until proven otherwise
            tile_collisions = [
                pygame.Rect(
                    tile.position[0], tile.position[1], tile.width, tile.height)
                for tile in self.arena.get_colliders()
            ]

            self.client.send_position(
                self.player.position.x, self.player.position.y,
                self.player.rotation, self.player.barrel_rotation
            )

            keys = pygame.key.get_pressed()

            if self.player.alive:
                mouse = pygame.mouse.get_pressed()
                mouse_x, mouse_y = pygame.mouse.get_pos()
                mouse_x *= SCREEN_WIDTH / DISPLAY_WIDTH
                mouse_y *= SCREEN_HEIGHT / DISPLAY_HEIGHT
                direction_vector = pygame.Vector2(
                    mouse_x, mouse_y) - self.player.position
                direction_vector = direction_vector.normalize()

                angle = math.atan2(-direction_vector[1], direction_vector[0])
                degrees = math.degrees(angle)
                self.player.barrel_rotation = (degrees + 360) % 360

                if mouse[0] and not self.shoot_cooldown:
                    self.shoot((direction_vector.x, direction_vector.y))
                    self.shoot_cooldown = self.SHOOT_COOLDOWN
                    HIT_SOUND.play()

                self.player.handle_input(keys, tile_collisions, dt)

            self.player.draw(self.screen)

            for id, player in self.client.players.items():
                self.draw_player(player) if id != self.client.id else ...

            for projectile in self.client.projectiles:
                self.update_projectile(projectile, tile_collisions, dt)
                self.draw_projectile(projectile.position, projectile.rotation)

            self.shoot_cooldown = max(0, self.shoot_cooldown - dt / 10)

            pygame.transform.scale(
                self.screen, (DISPLAY_WIDTH, DISPLAY_HEIGHT), self.display)

            self.ui.draw(list(self.client.players.values()),
                         self.client.lifecycle_state,
                         self.client.lifecycle_context
                         )


            pygame.display.flip()
            pygame.event.pump()  # process event queue

            if keys[pygame.K_q]:
                self.running = False

        self.client.disconnect()
        sys.exit()


if __name__ == "__main__":
    pygame.init()
    game = Game()

    if '--local' in sys.argv:
        game.run_local()
    elif '--join' in sys.argv:
        idx = sys.argv.index('--join')
        if len(sys.argv) < idx + 1:
            raise ValueError("missing argument to option --join")

        game.run(sys.argv[idx + 1])
    else:
        game.run()
