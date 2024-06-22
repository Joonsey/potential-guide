import pygame
import threading

from server import Server
from client import Client, Projectile

SCREEN_WIDTH, SCREEN_HEIGHT = 800, 600


class Player:
    SPEED = 4

    def __init__(self) -> None:
        self.position = pygame.Vector2()

    def handle_input(self, keys, dt: int) -> None:
        # TODO: refactor
        velocity = self.SPEED * dt / 10
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


class Game:
    def __init__(self) -> None:
        self.client = Client()
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.player = Player()

    def run_local(self) -> None:
        s = Server()
        threading.Thread(target=s.start, daemon=True)

        self.run()

    def draw_player(self, position: tuple[float, float]) -> None:
        surf = pygame.Surface((16, 16))
        surf.fill((255, 0, 0))
        self.screen.blit(surf, position)

    def draw_projectile(self, position: tuple[float, float]) -> None:
        surf = pygame.Surface((8, 8))
        surf.fill((255, 128, 0))
        self.screen.blit(surf, position)

    def update_projectile(self, projectile: Projectile, dt: int) -> None:
        x, y = projectile.position
        vel_x, vel_y = projectile.velocity

        pos_x = x + vel_x * dt / 10
        pos_y = y + vel_y * dt / 10

        projectile.position = (pos_x, pos_y)

    def shoot(self, velocity: tuple[float, float]) -> None:
        pos = self.player.position
        self.client.send_shoot((pos.x, pos.y), velocity)

    def run(self) -> None:
        self.clock = pygame.Clock()
        self.client.connect()
        self.client.start()

        while True:
            dt = self.clock.tick(120)
            self.screen.fill((128, 128, 128))

            keys = pygame.key.get_pressed()
            mouse = pygame.mouse.get_pressed()
            if mouse[0]:
                mouse_x, mouse_y = pygame.mouse.get_pos()
                direction_vector = pygame.Vector2(
                    mouse_x, mouse_y) - self.player.position
                direction_vector = direction_vector.normalize()
                self.shoot((direction_vector.x, direction_vector.y))

            self.player.handle_input(keys, dt)
            self.client.send_position(
                self.player.position.x, self.player.position.y)

            self.player.draw(self.screen)

            for player in self.client.players:
                self.draw_player(player.position)

            for projectile in self.client.projectiles:
                self.update_projectile(projectile, dt)
                self.draw_projectile(projectile.position)

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
