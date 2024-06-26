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
    ARENA_WALL_COLOR, ARENA_WALL_COLOR_SHADE, DISPLAY_WIDTH, DISPLAY_HEIGHT, FONT_SIZE, LARGE_FONT_SIZE, PLAYER_CIRCLE_RADIUS, PLAYER_SHADOW_COLOR, READY_INTERVAL, RIPPLE_LIFETIME, SHOCKWAVE_KNOCKBACK, TRACK_LIFETIME, SCREEN_HEIGHT, SCREEN_WIDTH, TRACK_INTERVAL
)
from shared import NON_LETHAL_LIFECYCLES, LifecycleType, ProjectileType, gaussian_value, get_distance, is_within_radius, lerp, outline, render_stack

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
        if self.knockback.length() < 20:
            self.knockback = pygame.Vector2(0,0)
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
        self.asset_loader = asset_loader
        self.font = pygame.font.Font(None, self.font_size)
        self.arena_font = asset_loader.fonts['arena-screen']

    def draw(self, players: list[ClientPlayer], lifecycle_state: LifecycleType, context: float, game: 'Game') -> None:
        position_map = [
            {"topleft": (10, 10)},
            {"topright": (game.display_resolution[0] - 10, 10)}
        ]

        bullet_icon_map = {
            ProjectileType.LASER: self.asset_loader.sprite_sheets['bullet-lazer'][4].copy(),
            ProjectileType.BULLET: self.asset_loader.sprite_sheets['bullet'][4].copy(),
            ProjectileType.SHOCKWAVE: self.asset_loader.sprite_sheets['bullet-shockwave'][4].copy(),
            ProjectileType.SNIPER: self.asset_loader.sprite_sheets['bullet-sniper'][4].copy(),
            ProjectileType.CLUSTER: self.asset_loader.sprite_sheets['bullet-cluster'][4].copy(),
        }
        for i, player in enumerate(players[:2]):
            player_text = self.font.render(
                f"Player {player.id}: {player.score}", True, (0, 0, 0))

            # Calculate text positions
            rect = player_text.get_rect(**position_map[i])

            # Blit texts onto the screen
            self.ui_screen.blit(player_text, rect)

        display_width, display_height = game.display_resolution
        #  TODO: this is not really 'UI' should be moved
        if lifecycle_state in [LifecycleType.NEW_ROUND, LifecycleType.STARTING]:
            now = time.time()
            countdown = context - now
            text = self.arena_font.render(f"{countdown:.0f}", True, (0, 0, 0))
            rect = text.get_rect(topleft=(
                display_width  // 2 - text.get_width() // 2, display_height  // 2 - text.get_height() // 2))

            self.ui_screen.blit(text, rect)

        #  TODO: this is not really 'UI' should be moved
        elif lifecycle_state in [LifecycleType.DONE]:
            # FIXME
            player = int(game.client.lifecycle_context)
            text = self.arena_font.render(f"Player {player} won!", True, (0, 0, 0))
            rect = text.get_rect(topleft=(
                display_width // 2 - text.get_width() // 2, display_height // 2 - text.get_height() // 2))

            self.ui_screen.blit(text, rect)

        #  TODO: this is not really 'UI' should be moved
        if game.client.spectating:
            rc_text = self.font.render(f"You are currently spectating you will join next round", True, (28, 28, 28))
            rect = rc_text.get_rect(topleft=(
                display_width // 2 - rc_text.get_width() // 2, 10))

            self.ui_screen.blit(rc_text, rect)


        elif lifecycle_state in [LifecycleType.WAITING_ROOM]:
            count_ready_players = len(list(filter(lambda x: x.ready, players)))
            rc_text = self.arena_font.render(f"{count_ready_players}/{len(players)}", True, (0, 0, 0) if not game.ready else (120, 220, 120))
            rect = rc_text.get_rect(topleft=(
                display_width // 2 - rc_text.get_width() // 2, display_height // 2 - rc_text.get_height() // 2))

            self.ui_screen.blit(rc_text, rect)

            text = self.font.render(f"[R] to {'un-ready' if game.ready else 'ready'}", True, (0, 0, 0, 120))
            rect = text.get_rect(topleft=(
                display_width // 2 - text.get_width() // 2, display_height // 2 + rc_text.get_height() // 2))

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

        pos = (display_width // 2 - cd_surf.get_width(),
               display_height - cd_surf.get_height())
        self.ui_screen.blit(cd_surf, pos)


class Game:
    def __init__(self) -> None:
        self.client = Client()
        self.asset_loader = AssetLoader()
        self.display_resolution = (DISPLAY_WIDTH, DISPLAY_HEIGHT)
        self.screen = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.display = pygame.display.set_mode(self.display_resolution)
        pygame.display.set_caption("Ptanks")
        self.frame_count = 0
        self.fullscreen = False

        tank_sprites = self.asset_loader.sprite_sheets['tank']
        tank_barrel_sprites = self.asset_loader.sprite_sheets['tank-barrel']
        tank_broken_sprites = self.asset_loader.sprite_sheets['tank-broken']

        self.ready = False
        self.player = Player(
            tank_sprites, tank_barrel_sprites, tank_broken_sprites)
        self.ui = UI(self.display, self.asset_loader)
        self.shoot_cooldown = [0.0, 0.0]
        self.running = False
        self.tracks: list[Track] = []  # x, y, time
        self.particles: list[Particle] = []

        arena_names = os.listdir('arenas')
        arena_names.sort()

        self.arenas = [Arena(os.path.join('arenas', file))
                       for file in arena_names]
        self.player.position = pygame.Vector2(
            random.choice(self.arena.spawn_positions))

    @property
    def arena(self) -> Arena:
        return self.arenas[int(self.client.current_arena)]

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
                offset_position = tile.position[0]+ 4, tile.position[1] + 8
                pygame.draw.ellipse(self.screen, PLAYER_SHADOW_COLOR, (*offset_position, 8, 8))


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
            case ProjectileType.SNIPER:
                surf = self.asset_loader.sprite_sheets['bullet-sniper']
            case ProjectileType.BULLET:
                surf = self.asset_loader.sprite_sheets['bullet']
            case ProjectileType.CLUSTER:
                surf = self.asset_loader.sprite_sheets['bullet-cluster']
            case _:
                surf = self.asset_loader.sprite_sheets['bullet']

        render_stack(
            dest,
            surf,
            pygame.Vector2(position),
            int(rotation)
        )

    def check_projectile_interaction(self, projectile: Projectile, interactable_tiles_list: list[Tile]) -> None:
        for tile in interactable_tiles_list:
            if (pygame.Rect(tile.position[0], tile.position[1], tile.width, tile.height)
                    .colliderect(pygame.Rect(projectile.position[0], projectile.position[1], 8, 8))):
                projectile.remaining_bounces = 0
                if projectile.sender_id == self.client.id:
                    try:
                        id = self.player.bullets.index(ProjectileType(int(projectile.projectile_type)))
                    except:
                        id = 0
                    self.player.bullets[id] = ProjectileType(int(tile.tile_type))

    def handle_event(self, event: Event) -> None:
        # FIXME breaking index error
        if event.event_type == EventType.FORCE_MOVE:
            self.player.position.x = event.data[0]
            self.player.position.y = event.data[1]
            self.player.rotation = event.data[2]
            self.player.barrel_rotation = event.data[3]
            self.player.knockback = pygame.Vector2(0,0)

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
                self.player.alive = self.client.lifecycle_state in NON_LETHAL_LIFECYCLES

        elif event.event_type == EventType.RESSURECT:
            self.player.alive = True

        elif event.event_type == EventType.WINNER:
            if event.data == self.client.id:
                # do something to celebrate a win
                print("you won!")

    def shoot(self, velocity: tuple[float, float], projectile_type: ProjectileType, target: tuple[float, float] | None = None) -> None:
        spark_pos = self.player.position.copy()
        spark_pos += pygame.Vector2(velocity[0], velocity[1]) * 8
        angle = math.atan2(velocity[1], velocity[0])
        spark_pos.y -= 0
        spark_pos.x += 8

        for i in range(2):
            self.particles.append(Spark(spark_pos.copy(), angle + (i / 3), (255, 255, 255), scale=.35, force=.15))

        pos = self.player.position
        if target and Projectile.is_lobbed(projectile_type):
            self.client.send_shoot((pos.x, pos.y), target, projectile_type)
        else:
            self.client.send_shoot((pos.x, pos.y), velocity, projectile_type)

    def draw_lobbed_projectile(self, projectile: Projectile) -> None:
        start_pos = projectile.start_position
        target_pos = projectile.velocity  # to simplify sockets we interchange velocity with target if lobbed

        max_distance = get_distance(projectile.start_position, target_pos)
        distance_from_start = get_distance(projectile.position, start_pos)
        # Calculate value based on linear curve
        half_distance = max_distance / 2
        if distance_from_start <= half_distance:
            # Increasing part of the curve (quadratic)
            height = 1 - ((half_distance - distance_from_start) / half_distance)**2
        else:
            # Decreasing part of the curve (quadratic)
            height  = 1 - ((distance_from_start - half_distance) / half_distance)**2

        draw_pos = projectile.position[0], projectile.position[1] - height * 32

        reticle_size = 16
        pygame.draw.ellipse(self.screen, (200, 0, 0), (target_pos[0] - reticle_size / 2, target_pos[1] - reticle_size / 2, reticle_size, reticle_size), width=2)

        pygame.draw.ellipse(self.screen, PLAYER_SHADOW_COLOR, (*projectile.position, 8, 8))
        self.draw_projectile(self.screen, draw_pos, 0, projectile.projectile_type)


    def incremenet_frame_count(self) -> None:
        self.frame_count += 1

    def run(self, address: str = "127.0.0.1") -> None:
        self.clock = pygame.Clock()
        self.client.connect(address)
        self.client.start()
        self.running = True
        self.ready_interval = READY_INTERVAL

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

            self.ready_interval = max(0, self.ready_interval - dt)
            if keys[pygame.K_r] and not self.ready_interval and self.client.lifecycle_state in [LifecycleType.STARTING, LifecycleType.WAITING_ROOM]:
                self.ready = not self.ready
                self.client.send_ready(self.ready)
                self.ready_interval = READY_INTERVAL

            if keys[pygame.K_F11]:
                self.fullscreen = not self.fullscreen
                if self.fullscreen:
                    fullscreen_res = pygame.display.list_modes()[0]
                    self.display_resolution = fullscreen_res
                    self.display = pygame.display.set_mode(self.display_resolution, pygame.NOFRAME)
                else:
                    self.display_resolution = DISPLAY_WIDTH, DISPLAY_HEIGHT
                    self.display = pygame.display.set_mode(self.display_resolution)

            if self.player.alive and not self.client.spectating:
                mouse = pygame.mouse.get_pressed()
                mouse_x, mouse_y = pygame.mouse.get_pos()
                mouse_x *= SCREEN_WIDTH / self.display_resolution[0]
                mouse_y *= SCREEN_HEIGHT / self.display_resolution[1]
                direction_vector = pygame.Vector2(
                    mouse_x, mouse_y) - self.player.position
                direction_vector = direction_vector.normalize()

                angle = math.atan2(-direction_vector[1], direction_vector[0])
                degrees = math.degrees(angle)
                self.player.barrel_rotation = (degrees + 360) % 360

                if mouse[0] and not self.shoot_cooldown[0]:
                    self.shoot((direction_vector.x, direction_vector.y), self.player.bullets[0], target = (mouse_x, mouse_y))
                    self.shoot_cooldown[0] = Projectile.get_cooldown(
                        self.player.bullets[0])
                    HIT_SOUND.play()

                if mouse[2] and not self.shoot_cooldown[1]:
                    self.shoot((direction_vector.x, direction_vector.y), self.player.bullets[1], target = (mouse_x, mouse_y))
                    self.shoot_cooldown[1] = Projectile.get_cooldown(
                        self.player.bullets[1])
                    HIT_SOUND.play()

                if not self.frame_count % TRACK_INTERVAL:
                    self.tracks.append(
                        Track(self.player.position.copy(), self.player.rotation))
                self.player.handle_input(keys, tile_collisions, dt)

            if not self.client.spectating:
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

            projs_to_cleanup = []
            for projectile in self.client.projectiles:
                if projectile.lobbed:
                    hit_pos = Projectile.update_lobbed_projectile(projectile, dt)
                    if hit_pos:
                        projectile.remaining_bounces = 0
                        self.check_projectile_interaction(projectile, interactable_tiles)
                        pos = pygame.Vector2(projectile.position)


                        if projectile.projectile_type == ProjectileType.SHOCKWAVE:
                            new_pos_x, new_pos_y = pos
                            #player_center_pos = self.player.position.x - 8, self.player.position.y - 8
                            player_center_pos = self.player.position.x, self.player.position.y
                            distance = player_center_pos[0] - new_pos_x, player_center_pos[1] - new_pos_y

                            radius = projectile.radius
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
                        else:
                            r = Ripple(pos.copy(), 20, force=1.5,
                                       color=pygame.Color(255, 255, 255), width=1)
                            r.lifetime = RIPPLE_LIFETIME * 1.3
                            self.particles.append(r)
                            self.particles.append(Ripple(pos.copy(), 25))

                            r = Ripple(pos.copy(), 20, force=1.5,
                                       color=pygame.Color(255, 189, 189), width=2)
                            r.lifetime = RIPPLE_LIFETIME * .7
                            self.particles.append(r)
                            self.particles.append(Ripple(pos.copy(), 25))

                            for i in range(7):
                                self.particles.append(Spark(pos.copy(), i, (255, 255, 255), 2, force=.9))
                                self.particles.append(Spark(pos.copy(), i + .5, (191, 80, 50), 1))

                            for i in range(6):
                                self.particles.append(
                                    Spark(pos.copy(), i + .5, (0, 0, 0), 1, force=.3))

                            for i in range(6):
                                self.particles.append(
                                    Spark(pos.copy(), i, (255, 255, 255), 1, force=.2))
                    self.draw_lobbed_projectile(projectile)

                else:
                    self.check_projectile_interaction(projectile, interactable_tiles)
                    hit_pos = Projectile.update_projectile(projectile, tile_collisions, dt)
                    if hit_pos is not None:
                        new_pos_x, new_pos_y = hit_pos
                        vel_x, vel_y = projectile.velocity
                        self.particles.append(Spark(pygame.Vector2(new_pos_x, new_pos_y), math.atan2(
                            vel_y + .20, vel_x + .20), (255, 255, 255, 120), .2, force=.12))
                        self.particles.append(Spark(pygame.Vector2(new_pos_x, new_pos_y), math.atan2(
                            vel_y - .20, vel_x - .20), (255, 255, 255, 120), .2, force=.12))

                    self.draw_projectile(self.screen, projectile.position, projectile.rotation, projectile.projectile_type)

                if projectile.remaining_bounces == 0:
                    projs_to_cleanup.append(projectile)

            for projectile in projs_to_cleanup:
                if projectile in self.client.projectiles:
                    self.client.projectiles.remove(projectile)

            self.shoot_cooldown[0] = max(0, self.shoot_cooldown[0] - dt / 10)
            self.shoot_cooldown[1] = max(0, self.shoot_cooldown[1] - dt / 10)

            pygame.transform.scale(
                self.screen, self.display_resolution, self.display)

            self.ui.draw(list(self.client.players.values()),
                         self.client.lifecycle_state,
                         self.client.lifecycle_context,
                         self
                         )

            pygame.display.flip()
            pygame.event.pump()  # process event queue

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False

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
