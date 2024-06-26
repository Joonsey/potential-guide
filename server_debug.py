import pygame
import threading

from server import Server


s = Server()
threading.Thread(target=s.start, daemon=True).start()


pygame.init()
clock = pygame.Clock()
screen = pygame.display.set_mode((1080, 720))
while True:
    dt = clock.tick(120) / 1000
    screen.fill((0,0,0))

    for projectile in s.projectiles.values():
        surf = pygame.surface.Surface((8, 8))
        surf.fill((0, 100, 0))

        screen.blit(surf, projectile.position)

    for player in s.connections.values():
        surf = pygame.surface.Surface((16, 16))
        surf.fill((0, 0, 100))

        screen.blit(surf, player.position)

    for tile in list(filter(lambda x: x.tile_type == "#", s.arena.tiles)):
        surf = pygame.surface.Surface((tile.width, tile.height))
        surf.fill((255, 255, 255))

        screen.blit(surf, tile.position)

    for tile in list(filter(lambda x: x.interactable, s.arena.tiles)):
        surf = pygame.surface.Surface((tile.width, tile.height))
        surf.fill((205, 205, 255))

        screen.blit(surf, tile.position)

    pygame.display.flip()
