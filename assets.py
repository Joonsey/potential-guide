import os
import pygame

class AssetLoader:
    def __init__(self, asset_dir: str ="assets"):
        self.asset_dir = asset_dir
        self.images = {}
        self.sounds = {}
        self.sprite_sheets = {
            "bullets" : self.load_spritesheet("sprites/bullets.png", 8),
            "tank" : self.load_spritesheet("sprites/tank.png", 16),
            "car": [pygame.image.load('assets/sprites/car/' + img) for img in os.listdir('assets/sprites/car')]
        }

    def load_image(self, filename: str, convert_alpha=False) -> pygame.Surface:
        path = os.path.join(self.asset_dir, filename)
        if path not in self.images:
            try:
                image = pygame.image.load(path)
                if convert_alpha:
                    image = image.convert_alpha()
                self.images[path] = image
            except pygame.error as e:
                print(f"Error loading image '{filename}': {e}")
                raise e
        return self.images[path]

    def load_spritesheet(self, filename: str, tile_size: int, convert_alpha=False) -> list[pygame.Surface]:
        spritesheet = self.load_image(filename, convert_alpha)
        if not spritesheet:
            return []

        sprite_width, sprite_height = tile_size, tile_size

        columns = spritesheet.get_width() // sprite_width
        rows = spritesheet.get_height() // sprite_height

        frames = []

        for row in range(rows):
            for col in range(columns):
                x = col * sprite_width
                y = row * sprite_height
                subsurface = spritesheet.subsurface((x, y, sprite_width, sprite_height))
                frames.append(subsurface)
        return frames

    def load_sound(self, filename: str) -> pygame.mixer.Sound:
        path = os.path.join(self.asset_dir, filename)
        if path not in self.sounds:
            try:
                sound = pygame.mixer.Sound(path)
                self.sounds[path] = sound
            except pygame.error as e:
                print(f"Error loading sound '{filename}': {e}")
                raise e
        return self.sounds[path]
