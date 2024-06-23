import pygame
import threading

from server import Server
from client import Client, Projectile
from client import Player as ClientPlayer

SCREEN_WIDTH, SCREEN_HEIGHT = 800, 600
FONT_SIZE = 32


def lerp(a: float, b: float, f: float):
    return a * (1.0 - f) + (b * f)


class Player:
    SPEED = 100

    def __init__(self) -> None:
        self.position = pygame.Vector2()

    def handle_input(self, keys, dt: float) -> None:
        # TODO: refactor
        velocity = self.SPEED * dt
        if keys[pygame.K_w]:
            self.position.y -= velocity
        if keys[pygame.K_s]:
            self.position.y += velocity
        if keys[pygame.K_a]:
            self.position.x -= velocity
        if keys[pygame.K_d]:
            self.position.x += velocity

    def draw(self, screen: pygame.Surface):
        # TODO: refactor
        surf = pygame.Surface((16, 16))
        surf.fill((0, 255, 0))
        screen.blit(surf, self.position)


class UI:
    def __init__(self, ui_screen: pygame.Surface) -> None:
        self.ui_screen = ui_screen
        self.font_size = FONT_SIZE
        self.font = pygame.font.Font(None, self.font_size)


    def draw(self, players: list[ClientPlayer]) -> None:
        position_map = [
            {"topleft": (10, 10)},
            {"topright": (SCREEN_WIDTH - 10, 10)}
        ]
        for i, player in enumerate(players[:2]):
            player_text = self.font.render(f"Player {i + 1}: {player.score}", True, (255, 255, 255))  # White text

            # Calculate text positions
            rect = player_text.get_rect(**position_map[i])

            # Blit texts onto the screen
            self.ui_screen.blit(player_text, rect)

class Game:
    SHOOT_COOLDOWN = .05
    def __init__(self) -> None:
        self.client = Client()
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.player = Player()
        self.ui = UI(self.screen)
        self.shoot_cooldown = 0

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

        surf = pygame.Surface((16, 16))
        surf.fill((255, 0, 0))
        self.screen.blit(surf, position)

    def draw_projectile(self, position: tuple[float, float]) -> None:
        surf = pygame.Surface((8, 8))
        surf.fill((255, 128, 0))
        self.screen.blit(surf, position)

    def update_projectile(self, projectile: Projectile, dt: float) -> None:
        x, y = projectile.position
        vel_x, vel_y = projectile.velocity

        pos_x = x + vel_x * dt * Projectile.SPEED
        pos_y = y + vel_y * dt * Projectile.SPEED

        projectile.position = (pos_x, pos_y)

    def shoot(self, velocity: tuple[float, float]) -> None:
        pos = self.player.position
        self.client.send_shoot((pos.x, pos.y), velocity)

    def run(self) -> None:
        self.clock = pygame.Clock()
        self.client.connect()
        self.client.start()

        while True:
            dt = self.clock.tick(120) / 1000
            self.screen.fill((128, 128, 128))

            keys = pygame.key.get_pressed()
            mouse = pygame.mouse.get_pressed()
            if mouse[0] and not self.shoot_cooldown:
                mouse_x, mouse_y = pygame.mouse.get_pos()
                direction_vector = pygame.Vector2(
                    mouse_x, mouse_y) - self.player.position
                direction_vector = direction_vector.normalize()
                self.shoot((direction_vector.x, direction_vector.y))
                self.shoot_cooldown = self.SHOOT_COOLDOWN

            self.player.handle_input(keys, dt)
            self.client.send_position(
                self.player.position.x, self.player.position.y)

            self.player.draw(self.screen)

            for id, player in self.client.players.items():
                self.draw_player(player) if id != self.client.id else ...

            for projectile in self.client.projectiles:
                self.update_projectile(projectile, dt)
                self.draw_projectile(projectile.position)

            self.shoot_cooldown = max(0, self.shoot_cooldown - dt / 10)

            self.ui.draw(list(self.client.players.values()))
            pygame.display.flip()
            pygame.event.pump()  # process event queue


if __name__ == "__main__":
    import sys
    pygame.init()
    game = Game()

    if '--local' in sys.argv:
        game.run_local()
    else:
        game.run()
