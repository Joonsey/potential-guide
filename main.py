import os
import time
import pygame
import threading
import sys
import math

from arena import Arena
from assets import AssetLoader
from server import Server
from client import Client, Event, EventType, Projectile
from client import Player as ClientPlayer
from settings import (
    ARENA_WALL_COLOR, ARENA_WALL_COLOR_SHADE, DISPLAY_WIDTH, DISPLAY_HEIGHT, FONT_SIZE, LARGE_FONT_SIZE, PLAYER_CIRCLE_RADIUS, RIPPLE_LIFETIME, SPARK_LIFETIME, TRACK_LIFETIME, SCREEN_HEIGHT, SCREEN_WIDTH, TRACK_INTERVAL
)
from shared import LifecycleType, ProjectileType, lerp, outline, render_stack

pygame.mixer.init()

VOLUME = .15

HIT_SOUND = pygame.mixer.Sound('assets/hit_1.wav')
EXPLOSION_SOUND = pygame.mixer.Sound('assets/explosion.wav')

HIT_SOUND.set_volume(VOLUME)
EXPLOSION_SOUND.set_volume(VOLUME)


class Track:
    def __init__(self, pos: pygame.Vector2, rotation: float) -> None:
        self.lifetime: float = TRACK_LIFETIME
        self.position = pos
        self.rotation = rotation


class Particle:
    def __init__(self) -> None:
        self.lifetime = RIPPLE_LIFETIME #FIXME

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
            [self.pos.x + math.cos(self.angle) * self.lifetime * self.scale, self.pos.y + math.sin(self.angle) * self.lifetime * self.scale],
            [self.pos.x + math.cos(self.angle + math.pi / 2) * self.lifetime * self.scale * 0.3, self.pos.y + math.sin(self.angle + math.pi / 2) * self.lifetime * self.scale * 0.3],
            [self.pos.x - math.cos(self.angle) * self.lifetime * self.scale * 3.5, self.pos.y - math.sin(self.angle) * self.lifetime * self.scale * 3.5],
            [self.pos.x + math.cos(self.angle - math.pi / 2) * self.lifetime * self.scale * 0.3, self.pos.y - math.sin(self.angle + math.pi / 2) * self.lifetime * self.scale * 0.3],
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
        h_to_w_coffactor = SCREEN_HEIGHT / SCREEN_WIDTH
        pygame.draw.ellipse(screen, self.color, (self.position.x - rad / 2, self.position.y - rad / 2, rad, rad), self.width)

    @property
    def radius(self) -> float:
        return self.max_radius * self.force * (1 - self.lifetime / RIPPLE_LIFETIME)


class Player:
    ACCELERATION = 100
    ROTATION_SPEED = 90
    MAX_SPEED = 120

    def __init__(self, sprites: list[pygame.Surface], barrel_sprites: list[pygame.Surface]) -> None:
        self.position = pygame.Vector2()
        self.rotation = 0
        self.barrel_rotation: float = 0
        self.velocity = pygame.Vector2()
        self.alive = True

        self.sprites = sprites
        self.barrel_sprites = barrel_sprites

    def handle_input(self, keys, collision_list: list[pygame.Rect], dt: float) -> None:
        # TODO: refactor
        rotation_speed = self.ROTATION_SPEED * dt

        rad = math.radians(self.rotation)
        vel_x, vel_y = math.sin(rad), -math.cos(rad)
        velocity = self.ACCELERATION * dt

        if keys[pygame.K_a]:
            self.rotation -= rotation_speed
        if keys[pygame.K_d]:
            self.rotation += rotation_speed

        start_pos = self.position.copy()

        if keys[pygame.K_w]:
            self.velocity.y = vel_y * velocity
            self.velocity.x = vel_x * velocity

        elif keys[pygame.K_s]:
            self.velocity.y = -vel_y * velocity
            self.velocity.x = -vel_x * velocity

        else:
            self.velocity *= .5

        self.position += self.velocity
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
        radius = PLAYER_CIRCLE_RADIUS

        if self.alive:
            pygame.draw.ellipse(screen, (0, 200, 0), (local_position.x - radius / 2,
                                local_position.y - radius / 2, 16 + radius, 16 + radius), 1)

            x_pos, y_pos = math.cos(math.radians(self.rotation - 90)) * 16, math.sin(math.radians(self.rotation - 90)) * 16
            left_point_x, left_point_y = math.cos(math.radians(self.rotation)) * 8, math.sin(math.radians(self.rotation)) * 8
            right_point_x, right_point_y  = math.cos(math.radians(self.rotation - 180)) * 8, math.sin(math.radians(self.rotation - 180)) * 8

            top_point = (x_pos + self.position.x + 8, y_pos + self.position.y + 8)
            left_point = (left_point_x + self.position.x + 8, left_point_y + self.position.y + 8)
            right_point = (right_point_x + self.position.x + 8, right_point_y + self.position.y + 8)

            pygame.draw.polygon(screen, (0, 200, 0), [
                top_point, left_point, right_point], 2) #pyright: ignore

        render_stack(screen, self.sprites, local_position, -self.rotation)

        barrel_pos = local_position.copy()
        barrel_pos.y -= 4
        render_stack(screen, self.barrel_sprites,
                     barrel_pos, int(self.barrel_rotation))



class UI:
    def __init__(self, ui_screen: pygame.Surface, asset_loader: AssetLoader) -> None:
        self.ui_screen = ui_screen
        self.font_size = FONT_SIZE
        self.font = pygame.font.Font(None, self.font_size)
        self.new_room_font = pygame.font.Font(None, LARGE_FONT_SIZE)
        self.asset_loader = asset_loader

    def draw(self, players: list[ClientPlayer], lifecycle_state: LifecycleType, context: float, game: 'Game') -> None:
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
                DISPLAY_WIDTH // 2 - text.get_width() // 2, DISPLAY_HEIGHT // 2 - text.get_height() // 2))

            self.ui_screen.blit(text, rect)

        bullet_sprite = self.asset_loader.sprite_sheets['bullet-lazer'][4].copy()
        cooldown_cover = pygame.Surface(bullet_sprite.get_size(), pygame.SRCALPHA)
        cooldown_cover.fill((255,255,255,200))
        bullet_sprite.blit(cooldown_cover, (0, -bullet_sprite.get_height() * (1 - (game.shoot_cooldown / game.SHOOT_COOLDOWN))))

        if not game.player.alive:
            cooldown_cover.fill((0, 0, 0, 200))
            bullet_sprite.blit(cooldown_cover, (0,0))

        bullet_sprite = pygame.transform.scale(bullet_sprite, (32, 32))

        pos = (DISPLAY_WIDTH // 2 - bullet_sprite.get_width(), DISPLAY_HEIGHT - bullet_sprite.get_height())
        self.ui_screen.blit(bullet_sprite, pos)


class Game:
    SHOOT_COOLDOWN = .05

    def __init__(self) -> None:
        self.client = Client()
        self.asset_loader = AssetLoader()
        self.screen = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.display = pygame.display.set_mode((DISPLAY_WIDTH, DISPLAY_HEIGHT))
        pygame.display.set_caption("Ptanks")
        self.frame_count = 0

        tank_sprites = self.asset_loader.sprite_sheets['tank']
        tank_barrel_sprites = self.asset_loader.sprite_sheets['tank-barrel']
        wall_sprites = self.asset_loader.sprite_sheets['wall']

        self.player = Player(tank_sprites, tank_barrel_sprites)
        self.ui = UI(self.display, self.asset_loader)
        self.shoot_cooldown = 0
        self.running = False
        self.tracks: list[Track] = []  # x, y, time
        self.particles: list[Particle] = []

        self.arenas = [Arena(os.path.join('arenas', file)) for file in os.listdir('arenas') ]
        self.player.position = pygame.Vector2(self.arena.spawn_positions[len(self.client.players) % self.arena.players_count])

    @property
    def arena(self) -> Arena:
        return self.arenas[self.client.current_arena]

    def run_local(self) -> None:
        s = Server()
        threading.Thread(target=s.start, daemon=True).start()

        self.run()

    def draw_and_update_tracks(self, dt) -> None:
        tracks_to_cleanup = []
        for i, track in enumerate(self.tracks):
            track_surf: pygame.Surface = self.asset_loader.sprite_sheets['track'][0].copy(
            )
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

        if player.alive:
            radius = PLAYER_CIRCLE_RADIUS
            pygame.draw.ellipse(self.screen, (200, 0, 0), (vec_pos.x - radius / 2,
                                vec_pos.y - radius / 2, 16 + radius, 16 + radius), 1)

            if not frame_count % TRACK_INTERVAL:
                self.tracks.append(Track(vec_pos.copy(), player.rotation))

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
        arena_surf.fill((0, 0, 0))
        arena_surf.set_colorkey((0, 0, 0))

        for i, tile in enumerate(self.arena.tiles):
            if tile.tile_type == "#":
                color = ARENA_WALL_COLOR

                surf = pygame.Surface((tile.width, tile.height))
                surf.fill(color)
                arena_surf.blit(surf, tile.position)

                if (i < len(self.arena.tiles) - self.arena.width):
                    if (self.arena.tiles[i + self.arena.width].tile_type == "#"):
                        ...
                    else:
                        shade_surf = pygame.Surface((tile.width, tile.height // 2))
                        shade_surf.fill(ARENA_WALL_COLOR_SHADE)
                        shade_position = tile.position[0], tile.position[1] + tile.height
                        arena_surf.blit(shade_surf, shade_position)


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
            self.particles.append(Spark(pygame.Vector2(new_pos_x, new_pos_y), math.atan2(vel_y + .20, vel_x + .20), (255, 255, 255, 120), .2, force = .12))
            self.particles.append(Spark(pygame.Vector2(new_pos_x, new_pos_y), math.atan2(vel_y - .20, vel_x - .20), (255, 255, 255, 120), .2, force = .12))
            if projectile.remaining_bounces == 0:
                self.client.projectiles.remove(projectile)
                return
            projectile.remaining_bounces -= 1

        projectile.position = (new_pos_x, new_pos_y)
        projectile.velocity = (vel_x, vel_y)

    def handle_event(self, event: Event) -> None:
        #FIXME breaking index error
        if event.event_type == EventType.FORCE_MOVE:
            self.player.position.x = event.data[0]
            self.player.position.y = event.data[1]
            self.player.rotation = event.data[2]
            self.player.barrel_rotation = event.data[3]

        elif event.event_type == EventType.HIT:
            proj_id, hit_id = event.data

            #FIXME hit_id out of range on windows
            proj_list = list(filter(lambda x: x.id == proj_id, self.client.projectiles))
            if not proj_list or len(self.client.players) >= hit_id:
                pass

            proj = proj_list[0]
            pos = self.client.players[hit_id].position

            player_pos = pygame.Vector2(pos[0] + 8, pos[1] + 8)
            self.client.projectiles.remove(proj)

            r = Ripple(player_pos.copy(), 20, force=1.5, color=pygame.Color(255, 255, 255), width=1)
            r.lifetime = RIPPLE_LIFETIME * 1.3
            self.particles.append(r)
            self.particles.append(Ripple(player_pos.copy(), 25))

            for i in range(-10, 10, 6):
                self.particles.append(Spark(player_pos.copy(), math.radians(- proj.rotation + i * 5), (255, 255, 255), 2, force=.9))
                self.particles.append(Spark(player_pos.copy(), math.radians(- proj.rotation + i * 5), (191, 80, 50), 2))

            for i in range(6):
                self.particles.append(Spark(player_pos.copy(), i + .5, (0, 0, 0), 1, force=.3))

            for i in range(6):
                self.particles.append(Spark(player_pos.copy(), i, (255, 255, 255), 1, force=.2))

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
                    self.shoot(
                        (direction_vector.x, direction_vector.y), ProjectileType.LASER)
                    self.shoot_cooldown = self.SHOOT_COOLDOWN
                    HIT_SOUND.play()

                if mouse[2] and not self.shoot_cooldown:
                    self.shoot((direction_vector.x, direction_vector.y),
                               ProjectileType.BULLET)
                    self.shoot_cooldown = self.SHOOT_COOLDOWN
                    HIT_SOUND.play()

                if not self.frame_count % TRACK_INTERVAL:
                    self.tracks.append(
                        Track(self.player.position.copy(), self.player.rotation))
                self.player.handle_input(keys, tile_collisions, dt)

            self.player.draw(self.screen)

            for id, player in self.client.players.items():
                self.draw_player(
                    player, self.frame_count) if id != self.client.id else ...


            cleanup = []
            for part in self.particles:
                part.update(dt)
                part.draw(self.screen)
                if part.lifetime == 0:
                    cleanup.append(part)

            for part in cleanup:
                self.particles.remove(part)

            for projectile in self.client.projectiles:
                self.update_projectile(projectile, tile_collisions, dt)
                self.draw_projectile(
                    projectile.position, projectile.rotation, projectile.projectile_type)

            self.shoot_cooldown = max(0, self.shoot_cooldown - dt / 10)

            pygame.transform.scale(
                self.screen, (DISPLAY_WIDTH, DISPLAY_HEIGHT), self.display)

            self.ui.draw(list(self.client.players.values()),
                         self.client.lifecycle_state,
                         self.client.lifecycle_context,
                         self
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
