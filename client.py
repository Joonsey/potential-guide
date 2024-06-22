import random
import time
import socket
import logging
import threading

from packet import Packet, PacketType, PayloadFormat

BUFF_SIZE = 1024


LOGGER = logging.getLogger("Client")


class Projectile:
    SPEED = 200  # this needs to be synced in server.Projectile.SPEED
    def __init__(self) -> None:
        self.position: tuple[float, float] = (0, 0)
        self.velocity: tuple[float, float] = (0, 0)


class Player:
    def __init__(self) -> None:
        # used for interpolation
        self.old_position: tuple[float, float] | None = None
        self.position: tuple[float, float] = (0, 0)
        self.name = ""
        self.score = 0
        self.interpolation_t: float = 0

    def __repr__(self) -> str:
        return f"<Player {self.name}, {self.position}, {self.score}>"


class Client:
    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.address: str = "127.0.0.1"
        self.port: int = 5001
        self._sequence_number = 0
        self.players: dict[int, Player] = {}
        self.projectiles: list[Projectile] = []
        self.id = 0

    @property
    def sequence_number(self):
        """
        getting this property increments sequence_number
        """
        n = self._sequence_number
        self._sequence_number += 1
        return n

    def _send(self, data: bytes) -> None:
        self.sock.sendto(data, (self.address, self.port))

    def _send_packet(self, packet: Packet) -> None:
        self._send(packet.serialize())

    def connect(self) -> None:
        packet = Packet(PacketType.CONNECT,
                        self.sequence_number, b"connecting!")
        self._send_packet(packet)

    def handle_update_packet(self, packet: Packet) -> None:
        size = PayloadFormat.UPDATE.size
        player_count = len(packet.payload) // size

        for i in range(player_count):
            data = packet.payload[i * size: size + size * i]
            id, x, y, score = PayloadFormat.UPDATE.unpack(data)
            if id == self.id:
                continue

            if id in self.players.keys():
                player = self.players[id]
                player.old_position = player.position
                player.position = (x, y)
                player.interpolation_t = 0
            else:
                player = Player()
                player.position = (x, y)

            player.score = score
            self.players[id] = player

    def handle_response(self, data: bytes, addr) -> None:
        LOGGER.debug("handling data: %s from %s", data, addr)
        try:
            packet = Packet.deserialize(data)
        except ValueError as e:
            LOGGER.error(e)
            return

        if packet.packet_type == PacketType.UPDATE:
            self.handle_update_packet(packet)

        if packet.packet_type == PacketType.ONBOARD:
            id, = PayloadFormat.ONBOARD.unpack(packet.payload)
            self.id = id

        if packet.packet_type == PacketType.SHOOT:
            x_pos, y_pos, x_vel, y_vel = PayloadFormat.SHOOT.unpack(
                packet.payload)
            proj = Projectile()
            proj.position = (x_pos, y_pos)
            proj.velocity = (x_vel, y_vel)
            self.projectiles.append(proj)

    def listen(self) -> None:
        while True:
            data, addr = self.sock.recvfrom(BUFF_SIZE)
            threading.Thread(target=self.handle_response,
                             args=(data, addr)).start()

    def start(self) -> None:
        threading.Thread(target=self.listen, daemon=True).start()

    def send_position(self, x: float, y: float) -> None:
        packet = Packet(PacketType.COORDINATES, self.sequence_number,
                        PayloadFormat.COORDINATES.pack(
                            self.id, x, y
                        ))
        self._send_packet(packet)

    def send_shoot(self, position: tuple[float, float], velocity: tuple[float, float]) -> None:
        packet = Packet(PacketType.SHOOT, self.sequence_number,
                        PayloadFormat.SHOOT.pack(
                            position[0],
                            position[1],
                            velocity[0],
                            velocity[1],
                        ))
        self._send_packet(packet)


if __name__ == "__main__":
    s = Client()
    s.connect()
    s.start()

    while True:
        if random.randint(0, 100) > 80:
            s.send_position(random.randint(0, 100), random.randint(0, 100))

        time.sleep(.1)
