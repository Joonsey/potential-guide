import os
import time
import pygame
import threading
import sys
import math
import random

from arena import Arena, Tile
from assets import AssetLoader
from server import Server
from client import Client, Event, EventType, Projectile
from client import Player as ClientPlayer
from particles import Particle, Ripple, Spark
from settings import (
    ARENA_WALL_COLOR, ARENA_WALL_COLOR_SHADE, DISPLAY_WIDTH, DISPLAY_HEIGHT, FONT_SIZE, LARGE_FONT_SIZE, PLAYER_CIRCLE_RADIUS, PLAYER_SHADOW_COLOR, RIPPLE_LIFETIME, SHOCKWAVE_KNOCKBACK, TRACK_LIFETIME, SCREEN_HEIGHT, SCREEN_WIDTH, TRACK_INTERVAL
)
from shared import LifecycleType, ProjectileType, is_within_radius, lerp, outline, render_stack

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


class Player:
    ACCELERATION = 100
    ROTATION_SPEED = 120
    MAX_SPEED = 120

    def __init__(self, sprites: list[pygame.Surface], barrel_sprites: list[pygame.Surface], broken_sprites: list[pygame.Surface]) -> None:
        self.position = pygame.Vector2()
        self.rotation = 0
        self.barrel_rotation: float = 0
        self.velocity = pygame.Vector2()
        self.alive = True
        self.bullets = [ProjectileType.LASER, ProjectileType.SHOCKWAVE]
        self.knockback = pygame.Vector2()

        # refactor
        self.sprites = sprites
        self.barrel_sprites = barrel_sprites
        self.broken_sprites = broken_sprites

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

        damping_factor = 0.1  # Adjust this value between 0 and 1 for different damping rates
        self.knockback *= damping_factor ** dt
        self.position.x -= self.knockback.x * dt
        self.position.x += self.velocity.x

        for rect in collision_list:
            if self.check_collision(rect):
                self.position.x = start_pos.x

        self.position.y -= self.knockback.y * dt
        self.position.y += self.velocity.y
        for rect in collision_list:
            if self.check_collision(rect):
                self.position.y = start_pos.y

    def check_collision(self, other_rect: pygame.Rect) -> bool:
        rect = pygame.Rect(
            self.position.x, self.position.y,
            16, 16
        )

        return rect.colliderect(other_rect)

    def draw(self, screen: pygame.Surface):
        local_position = self.position
        radius = PLAYER_CIRCLE_RADIUS

        pygame.draw.ellipse(screen, PLAYER_SHADOW_COLOR, (local_position.x - radius / 2,
                                                          local_position.y - radius / 2, 16 + radius, 16 + radius), 0)

        if self.alive:
            pygame.draw.ellipse(screen, (0, 200, 0), (local_position.x - radius / 2,
                                local_position.y - radius / 2, 16 + radius, 16 + radius), 1)

            x_pos, y_pos = math.cos(math.radians(
                self.rotation - 90)) * 16, math.sin(math.radians(self.rotation - 90)) * 16
            left_point_x, left_point_y = math.cos(math.radians(
                self.rotation)) * 8, math.sin(math.radians(self.rotation)) * 8
            right_point_x, right_point_y = math.cos(math.radians(
                self.rotation - 180)) * 8, math.sin(math.radians(self.rotation - 180)) * 8

            top_point = (x_pos + self.position.x + 8,
                         y_pos + self.position.y + 8)
            left_point = (left_point_x + self.position.x + 8,
                          left_point_y + self.position.y + 8)
            right_point = (right_point_x + self.position.x + 8,
                           right_point_y + self.position.y + 8)

            pygame.draw.polygon(screen, (0, 200, 0), [
                top_point, left_point, right_point], 2)  # pyright: ignore

            render_stack(screen, self.sprites, local_position, -self.rotation)

            barrel_pos = local_position.copy()
            barrel_pos.y -= 4
            render_stack(screen, self.barrel_sprites,
                         barrel_pos, int(self.barrel_rotation))

        else:
            render_stack(screen, self.broken_sprites,
                         local_position, -self.rotation)


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

        bullet_icon_map = {
            ProjectileType.LASER: self.asset_loader.sprite_sheets['bullet-lazer'][4].copy(),
            ProjectileType.BULLET: self.asset_loader.sprite_sheets['bullet'][4].copy(),
            ProjectileType.SHOCKWAVE: self.asset_loader.sprite_sheets['bullet-shockwave'][4].copy(),
        }
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

        icon_size = 16
        bullet_count = len(game.player.bullets)
        cd_surf = pygame.Surface(
            (bullet_count * icon_size, bullet_count * icon_size))
        cd_surf.set_colorkey((0, 0, 0))
        for i, bullet in enumerate(game.player.bullets):
            bullet_sprite = bullet_icon_map[bullet]
            cooldown_cover = pygame.Surface(
                bullet_sprite.get_size(), pygame.SRCALPHA)
            cooldown_cover.fill((255, 255, 255, 200))
            bullet_sprite.blit(cooldown_cover, (0, -bullet_sprite.get_height()
                               * (1 - (game.shoot_cooldown[i] / Projectile.get_cooldown(bullet)))))

            if not game.player.alive:
                cooldown_cover.fill((0, 0, 0, 200))
                bullet_sprite.blit(cooldown_cover, (0, 0))

            bullet_sprite = pygame.transform.scale(
                bullet_sprite, (bullet_count * icon_size, bullet_count * icon_size))
            cd_surf.blit(bullet_sprite, (i * icon_size, 0))

        pos = (DISPLAY_WIDTH // 2 - cd_surf.get_width(),
               DISPLAY_HEIGHT - cd_surf.get_height())
        self.ui_screen.blit(cd_surf, pos)


class Game:
    def __init__(self) -> None:
        self.client = Client()
        self.asset_loader = AssetLoader()
        self.screen = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.display = pygame.display.set_mode((DISPLAY_WIDTH, DISPLAY_HEIGHT))
        pygame.display.set_caption("Ptanks")
        self.frame_count = 0

        tank_sprites = self.asset_loader.sprite_sheets['tank']
        tank_barrel_sprites = self.asset_loader.sprite_sheets['tank-barrel']
        tank_broken_sprites = self.asset_loader.sprite_sheets['tank-broken']

        self.player = Player(
            tank_sprites, tank_barrel_sprites, tank_broken_sprites)
        self.ui = UI(self.display, self.asset_loader)
        self.shoot_cooldown = [0.0, 0.0]
        self.running = False
        self.tracks: list[Track] = []  # x, y, time
        self.particles: list[Particle] = []

        self.arenas = [Arena(os.path.join('arenas', file))
                       for file in os.listdir('arenas')]
        self.player.position = pygame.Vector2(
            random.choice(self.arena.spawn_positions))

    @property
    def arena(self) -> Arena:
        return self.arenas[self.client.current_arena]

    def run_local(self) -> None:
        s = Server()
        threading.Thread(target=s.start, daemon=True).start()

        self.run()

    def draw_and_update_tracks(self, dt) -> None:
        tracks_to_cleanup = []
        for track in self.tracks:
            track_surf: pygame.Surface = self.asset_loader.sprite_sheets['track'][0].copy(
            )
            track_surf = pygame.transform.rotate(track_surf, -track.rotation)
            alpha = int(lerp(0, 255, track.lifetime / TRACK_LIFETIME))
            track_surf.set_alpha(alpha)
            self.screen.blit(track_surf, track.position)

            track.lifetime = max(0, track.lifetime - dt)
            if not track.lifetime:
                tracks_to_cleanup.append(track)

        for track in tracks_to_cleanup:
            self.tracks.remove(track)

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
        radius = PLAYER_CIRCLE_RADIUS
        pygame.draw.ellipse(self.screen, PLAYER_SHADOW_COLOR, (vec_pos.x - radius / 2,
                                                               vec_pos.y - radius / 2, 16 + radius, 16 + radius), 0)

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
                self.screen, self.asset_loader.sprite_sheets['tank-barrel'], barrel_pos, int(player.barrel_rotation))

        else:
            render_stack(
                self.screen,
                self.asset_loader.sprite_sheets['tank-broken'],
                vec_pos,
                -player.rotation
            )

    def draw_arena(self, dt: float) -> None:
        arena_surf = self.screen.copy()
        arena_surf.fill((0, 0, 0))
        arena_surf.set_colorkey((0, 0, 0))

        for i, tile in enumerate(self.arena.tiles):
            if tile.tile_type in [str(i) for i in range(0, len(ProjectileType) + 1)]:
                # render bullet select tile
                projectile_type = ProjectileType(int(tile.tile_type))

                rotation = self.frame_count
                self.draw_projectile(arena_surf, tile.position, rotation, projectile_type)
                pygame.draw.ellipse(self.screen, PLAYER_SHADOW_COLOR, (*tile.position, tile.width, tile.height))


            elif tile.tile_type == "#":
                color = ARENA_WALL_COLOR

                surf = pygame.Surface((tile.width, tile.height))
                surf.fill(color)
                arena_surf.blit(surf, tile.position)

                if (i < len(self.arena.tiles) - self.arena.width):
                    if (self.arena.tiles[i + self.arena.width].tile_type == "#"):
                        ...
                    else:
                        shade_surf = pygame.Surface(
                            (tile.width, tile.height // 2))
                        shade_surf.fill(ARENA_WALL_COLOR_SHADE)
                        shade_position = tile.position[0], tile.position[1] + tile.height
                        arena_surf.blit(shade_surf, shade_position)

        outline(arena_surf, self.screen, (0, 0), 2)

    def draw_projectile(self, dest: pygame.Surface, position: tuple[float, float], rotation: float, projectile_type: ProjectileType) -> None:

        match projectile_type:
            case ProjectileType.LASER:
                surf = self.asset_loader.sprite_sheets['bullet-lazer']
            case ProjectileType.SHOCKWAVE:
                surf = self.asset_loader.sprite_sheets['bullet-shockwave']
            case _:
                surf = self.asset_loader.sprite_sheets['bullet']

        render_stack(
            dest,
            surf,
            pygame.Vector2(position),
            int(rotation)
        )

    def update_projectile(self, projectile: Projectile, collision_list: list[pygame.Rect], interactable_tiles_list: list[Tile], dt: float) -> None:
        x, y = projectile.position
        vel_x, vel_y = projectile.velocity

        # Calculate new potential position
        new_pos_x = x + vel_x * dt * projectile.speed
        new_pos_y = y + vel_y * dt * projectile.speed
        colided = False

        # Check for vertical collisions

        for tile in interactable_tiles_list:
            if (pygame.Rect(tile.position[0], tile.position[1], tile.width, tile.height)
                    .colliderect(pygame.Rect(new_pos_x, new_pos_y, 8, 8))):
                colided = True
                projectile.remaining_bounces = 0
                if projectile.sender_id == self.client.id:
                    try:
                        id = self.player.bullets.index(ProjectileType(int(projectile.projectile_type)))
                    except:
                        id = 0
                    self.player.bullets[id] = ProjectileType(int(tile.tile_type))


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
            self.particles.append(Spark(pygame.Vector2(new_pos_x, new_pos_y), math.atan2(
                vel_y + .20, vel_x + .20), (255, 255, 255, 120), .2, force=.12))
            self.particles.append(Spark(pygame.Vector2(new_pos_x, new_pos_y), math.atan2(
                vel_y - .20, vel_x - .20), (255, 255, 255, 120), .2, force=.12))
            if projectile.remaining_bounces == 0:
                self.client.projectiles.remove(projectile)

                if projectile.projectile_type != ProjectileType.SHOCKWAVE:
                    return

                #player_center_pos = self.player.position.x - 8, self.player.position.y - 8
                player_center_pos = self.player.position.x, self.player.position.y
                distance = player_center_pos[0] - new_pos_x, player_center_pos[1] - new_pos_y

                radius = 20
                if is_within_radius(player_center_pos, (new_pos_x, new_pos_y), radius*2):
                    self.player.knockback = -pygame.Vector2(distance).normalize() * SHOCKWAVE_KNOCKBACK

                r = Ripple(pygame.Vector2(new_pos_x, new_pos_y), radius, color=pygame.Color(178,178,255,255), width=4)
                r.lifetime *= .8
                self.particles.append(r)

                r = Ripple(pygame.Vector2(new_pos_x, new_pos_y), radius, color=pygame.Color(255,255,255,255), width=1, force=1.2)
                r.lifetime *= 1
                self.particles.append(r)

                for i in range(0, 6):
                    self.particles.append(Spark(pygame.Vector2(new_pos_x, new_pos_y), i, (255, 255, 255, 120), .2, force=.12))

            projectile.remaining_bounces -= 1

        projectile.position = (new_pos_x, new_pos_y)
        projectile.velocity = (vel_x, vel_y)

    def handle_event(self, event: Event) -> None:
        # FIXME breaking index error
        if event.event_type == EventType.FORCE_MOVE:
            self.player.position.x = event.data[0]
            self.player.position.y = event.data[1]
            self.player.rotation = event.data[2]
            self.player.barrel_rotation = event.data[3]

        elif event.event_type == EventType.HIT:
            proj_id, hit_id = event.data

            # FIXME hit_id out of range on windows
            proj_list = list(
                filter(lambda x: x.id == proj_id, self.client.projectiles))

            proj = proj_list[0] if proj_list else None
            self.client.projectiles.remove(proj) if proj else ...

            player = self.client.players[hit_id]

            pos = player.position
            desired_rotation = proj.rotation if proj else player.rotation

            player_pos = pygame.Vector2(pos[0] + 8, pos[1] + 8)

            r = Ripple(player_pos.copy(), 20, force=1.5,
                       color=pygame.Color(255, 255, 255), width=1)
            r.lifetime = RIPPLE_LIFETIME * 1.3
            self.particles.append(r)
            self.particles.append(Ripple(player_pos.copy(), 25))

            for i in range(-10, 10, 6):
                self.particles.append(Spark(player_pos.copy(
                ), math.radians(- desired_rotation + i * 5), (255, 255, 255), 2, force=.9))
                self.particles.append(Spark(
                    player_pos.copy(), math.radians(- desired_rotation + i * 5), (191, 80, 50), 2))

            for i in range(6):
                self.particles.append(
                    Spark(player_pos.copy(), i + .5, (0, 0, 0), 1, force=.3))

            for i in range(6):
                self.particles.append(
                    Spark(player_pos.copy(), i, (255, 255, 255), 1, force=.2))

            if hit_id == self.client.id:
                EXPLOSION_SOUND.play()
                self.player.alive = self.client.lifecycle_state in [
                    LifecycleType.WAITING_ROOM, LifecycleType.STARTING]

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
            self.draw_arena(dt)

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
            interactable_tiles = list(filter(lambda x: x.interactable, self.arena.tiles))

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

                if mouse[0] and not self.shoot_cooldown[0]:
                    self.shoot(
                        (direction_vector.x, direction_vector.y), self.player.bullets[0])
                    self.shoot_cooldown[0] = Projectile.get_cooldown(
                        self.player.bullets[0])
                    HIT_SOUND.play()

                if mouse[2] and not self.shoot_cooldown[1]:
                    self.shoot((direction_vector.x, direction_vector.y), self.player.bullets[1])
                    self.shoot_cooldown[1] = Projectile.get_cooldown(
                        self.player.bullets[1])
                    HIT_SOUND.play()

                if not self.frame_count % TRACK_INTERVAL:
                    self.tracks.append(
                        Track(self.player.position.copy(), self.player.rotation))
                self.player.handle_input(keys, tile_collisions, dt)

            self.player.draw(self.screen)

            for id, player in self.client.players.copy().items():
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
                self.update_projectile(projectile, tile_collisions, interactable_tiles, dt)
                self.draw_projectile(
                    self.screen, projectile.position, projectile.rotation, projectile.projectile_type)

            self.shoot_cooldown[0] = max(0, self.shoot_cooldown[0] - dt / 10)
            self.shoot_cooldown[1] = max(0, self.shoot_cooldown[1] - dt / 10)

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
