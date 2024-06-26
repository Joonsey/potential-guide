from settings import SCREEN_HEIGHT, SCREEN_WIDTH
from shared import ProjectileType


class Tile:
    def __init__(self) -> None:
        self.tile_type: str = ""  # TODO: refactor
        self.position: tuple[float, float] = (0, 0)
        self.height: float
        self.width: float
        self.has_collision = False
        self.interactable = False


class Arena:
    def __init__(self, path: str) -> None:
        self.height = 0
        self.width = 0
        self.map = []
        self.tiles: list[Tile] = []
        self.spawn_positions: list[tuple[float, float]] = []

        with open(path, 'r') as f:
            for line in f.readlines():
                self.height += 1
                self.width = len(
                    line.strip()) if not self.width else self.width
                self.map.append(list(line.strip()))

        width = SCREEN_WIDTH / self.width
        height = SCREEN_HEIGHT  / self.height

        for y, row in enumerate(self.map):
            for x, t in enumerate(row):
                tile = Tile()
                tile.tile_type = t
                tile.width = width + 1  # offset by one to avoid floating point erros during scaling
                tile.height = height + 1  # and to make hitboxes more generous
                tile.position = (width * x,  height * y)

                if t in ["#"]:
                    tile.has_collision = True

                if t in [str(i) for i in range(0, len(ProjectileType) + 1)]:
                    tile.interactable = True

                if t in ["@"]:
                    self.spawn_positions.append(tile.position)

                self.tiles.append(tile)

    @property
    def players_count(self) -> int:
        return len(self.spawn_positions)

    def get_colliders(self) -> list[Tile]:
        return list(filter(lambda x: x.has_collision, self.tiles))


if __name__ == "__main__":
    arena = Arena("arena")
    print(arena.map)
