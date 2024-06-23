class Tile:
    def __init__(self) -> None:
        self.tile_type: str = ""  # TODO: refactor
        self.position: tuple[float, float] = (0, 0)
        self.height: float
        self.width: float
        self.has_collision = False


class Arena:
    def __init__(self, path: str, dimension: tuple[float, float]) -> None:
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

        width = dimension[0] / self.width
        height = dimension[1] / self.height

        for y, row in enumerate(self.map):
            for x, t in enumerate(row):
                tile = Tile()
                tile.tile_type = t
                tile.width = width
                tile.height = height
                tile.position = (width * x,  height * y)

                if t in ["#"]:
                    tile.has_collision = True

                if t in ["@"]:
                    self.spawn_positions.append(tile.position)

                self.tiles.append(tile)

    @property
    def max_players(self) -> int:
        return len(self.spawn_positions)

    def get_colliders(self) -> list[Tile]:
        return list(filter(lambda x: x.has_collision, self.tiles))


if __name__ == "__main__":
    arena = Arena("arena", (1080, 720))
    print(arena.map)
