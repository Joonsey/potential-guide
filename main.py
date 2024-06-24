import time
import pygame
import threading
import sys
import math

from arena import Arena
from assets import AssetLoader
from packet import LifecycleType, ProjectileType
from server import Server
from client import Client, Event, EventType, Projectile
from client import Player as ClientPlayer
from settings import (
    DISPLAY_WIDTH, DISPLAY_HEIGHT, FONT_SIZE, LARGE_FONT_SIZE, TRACK_LIFETIME, SCREEN_HEIGHT, SCREEN_WIDTH, TRACK_INTERVAL
)

pygame.mixer.init()

VOLUME = .15

HIT_SOUND = pygame.mixer.Sound('assets/hit_1.wav')
EXPLOSION_SOUND = pygame.mixer.Sound('assets/explosion.wav')

HIT_SOUND.set_volume(VOLUME)
EXPLOSION_SOUND.set_volume(VOLUME)


class Track:
    def __init__(self, pos: pygame.Vector2, rotation: float) -> None:
        self.lifetime = TRACK_LIFETIME
        self.position = pos
        self.rotation = rotation


def lerp(a: float, b: float, f: float):
    return a * (1.0 - f) + (b * f)


def inverted(img: pygame.Surface):
   inv = pygame.Surface(img.get_rect().size, pygame.SRCALPHA)
   inv.fill((255,255,255,255))
   inv.blit(img, (0,0), None, pygame.BLEND_RGB_SUB)
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
    dest.blit(temp_surf, (0,0))

def render_stack(surf: pygame.Surface, images: list[pygame.Surface], pos: pygame.Vector2, rotation: int):
    count = len(images)
    for i, img in enumerate(images):
        rotated_img = pygame.transform.rotate(img, rotation)
        surf.blit(rotated_img, (pos.x - rotated_img.get_width() // 2 + count, pos.y - rotated_img.get_height() // 2 - i + count))


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
        local_position = self.position
        render_stack(screen, self.sprites, local_position, -self.rotation)

        barrel_pos = local_position.copy()
        barrel_pos.y -= 4
        render_stack(screen, self.barrel_sprites, barrel_pos, int(self.barrel_rotation))

class UI:
    def __init__(self, ui_screen: pygame.Surface) -> None:
        self.ui_screen = ui_screen
        self.font_size = FONT_SIZE
        self.font = pygame.font.Font(None, self.font_size)
        self.new_room_font = pygame.font.Font(None, LARGE_FONT_SIZE)

    def draw(self, players: list[ClientPlayer], lifecycle_state: LifecycleType, context: int) -> None:
        position_map = [
            {"topleft": (10, 10)},
            {"topright": (DISPLAY_WIDTH - 10, 10)}
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
        self.frame_count = 0

        tank_sprites = self.asset_loader.sprite_sheets['tank']
        tank_barrel_sprites = self.asset_loader.sprite_sheets['tank-barrel']
        wall_sprites = self.asset_loader.sprite_sheets['wall']

        self.player = Player(tank_sprites, tank_barrel_sprites)
        self.player.position = pygame.Vector2(
            SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        self.ui = UI(self.display)
        self.shoot_cooldown = 0
        self.running = False
        self.tracks: list[Track] = [] # x, y, time

        # TODO: REFACTOR
        self.arena = Arena('arena', (SCREEN_WIDTH, SCREEN_HEIGHT))
        self.wall_sprites = [pygame.transform.scale(sprite, (self.arena.tiles[0].width,  self.arena.tiles[0].height)) for sprite in wall_sprites]

    def run_local(self) -> None:
        s = Server()
        threading.Thread(target=s.start, daemon=True)

        self.run()

    def draw_and_update_tracks(self, dt) -> None:
        tracks_to_cleanup = []
        for i, track in enumerate(self.tracks):
            track_surf: pygame.Surface = self.asset_loader.sprite_sheets['track'][0].copy()
            track_surf = pygame.transform.rotate(track_surf, -track.rotation)
            alpha = int(lerp(0, 255, track.lifetime / TRACK_LIFETIME))
            track_surf.set_alpha(alpha)
            self.screen.blit(track_surf, track.position)

            track.lifetime = max(0, track.lifetime - dt)
            if not track.lifetime:
                tracks_to_cleanup.append(i)

        for i in tracks_to_cleanup:
            self.tracks.pop(i)

    def draw_player(self, player: ClientPlayer, frame_count: int) -> None:
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

        if player.alive and not frame_count % TRACK_INTERVAL: self.tracks.append(Track(vec_pos.copy(), player.rotation))

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
        arena_surf = self.screen.copy()
        arena_surf.fill((0,0,0))
        arena_surf.set_colorkey((0,0,0))

        for i, tile in enumerate(self.arena.tiles):
            if tile.tile_type == "#":
                color = (255, 255, 255)

                surf = pygame.Surface((tile.width, tile.height))
                if (i < len(self.arena.tiles) - self.arena.width):
                    if (self.arena.tiles[i + self.arena.width].tile_type == "#"):
                        ...
                    else:
                        color = (200, 200, 200)
                surf.fill(color)
                arena_surf.blit(surf, tile.position)

        outline(arena_surf, self.screen, (0, 0), 2)

    def draw_projectile(self, position: tuple[float, float], rotation: float, projectile_type: ProjectileType) -> None:

        match projectile_type:
            case ProjectileType.BALL:
                surf = self.asset_loader.sprite_sheets['bullet-ball']
            case ProjectileType.LASER:
                surf = self.asset_loader.sprite_sheets['bullet-lazer']
            case _:
                surf = self.asset_loader.sprite_sheets['bullet']

        render_stack(
            self.screen,
            surf,
            pygame.Vector2(position),
            int(rotation)
        )

    def update_projectile(self, projectile: Projectile, collision_list: list[pygame.Rect], dt: float) -> None:
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

    def shoot(self, velocity: tuple[float, float], projectile_type: ProjectileType) -> None:
        pos = self.player.position
        self.client.send_shoot((pos.x, pos.y), velocity, projectile_type)

    def incremenet_frame_count(self) -> None:
        self.frame_count += 1

    def run(self, address: str = "127.0.0.1") -> None:
        self.clock = pygame.Clock()
        self.client.connect(address)
        self.client.start()
        self.running = True

        while self.running:
            dt = self.clock.tick(120) / 1000
            self.frame_count += 1
            self.incremenet_frame_count()
            self.screen.fill((128, 128, 128))
            self.draw_and_update_tracks(dt)
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
                    self.shoot((direction_vector.x, direction_vector.y), ProjectileType.LASER)
                    self.shoot_cooldown = self.SHOOT_COOLDOWN
                    HIT_SOUND.play()

                if mouse[2] and not self.shoot_cooldown:
                    self.shoot((direction_vector.x, direction_vector.y), ProjectileType.BULLET)
                    self.shoot_cooldown = self.SHOOT_COOLDOWN
                    HIT_SOUND.play()

                if not self.frame_count % TRACK_INTERVAL: self.tracks.append(Track(self.player.position.copy(), self.player.rotation))
                self.player.handle_input(keys, tile_collisions, dt)

            self.player.draw(self.screen)

            for id, player in self.client.players.items():
                self.draw_player(player, self.frame_count) if id != self.client.id else ...

            for projectile in self.client.projectiles:
                self.update_projectile(projectile, tile_collisions, dt)
                self.draw_projectile(projectile.position, projectile.rotation, projectile.projectile_type)

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
