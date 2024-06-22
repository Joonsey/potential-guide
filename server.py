import socket
import threading
import time
import logging

# TODO: remove

from packet import Packet, PacketType, PayloadFormat

BUFF_SIZE = 1024


LOGGER = logging.getLogger("Server")


class Connection:
    def __init__(self, addr) -> None:
        self.addr = addr
        self.id = 0
        self.position = (0, 0)
        self.name = ""
        self.score = 0

class Projectile:
    SPEED = 200  # this needs to be synced in client.Projectile.SPEED
    def __init__(self) -> None:
        self.position: tuple[float, float] = (0, 0)
        self.velocity = (0, 0)
        self.alive = True

class Server:
    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.running = False
        self.tick_rate = 20
        self.connections: dict[tuple[str, int], Connection] = {}
        self.projectiles: dict[int, Projectile] = {}
        self._player_index = 0

    def _send(self, data: bytes, address: tuple[str, int]) -> None:
        self.sock.sendto(data, address)

    def _send_packet(self, packet: Packet, address: tuple[str, int]) -> None:
        self._send(packet.serialize(), address)

    def send_hit(self):
        ...

    def update_projectiles(self, delta_time: float) -> None:
        for _, proj in self.projectiles.items():
            if not proj.alive:
                continue

            x, y = proj.position
            vel_x, vel_y = proj.velocity

            pos_x = x + vel_x * delta_time * proj.SPEED
            pos_y = y + vel_y * delta_time * proj.SPEED

            proj.position = (pos_x, pos_y)

    def check_collisions(self) -> None:
        pass

    def loop(self) -> None:
        """
        Entry point for main update loop
        """
        LOGGER.info("main loop up!")
        self.last_iter_time = 0
        while self.running:
            start_time = time.time()

            update_data = b""
            for _, item in self.connections.items():
                update_data += PayloadFormat.UPDATE.pack(
                    item.id,
                    item.position[0],
                    item.position[1],
                    item.score
                )
            pack = Packet(PacketType.UPDATE, 0, update_data)
            self.broadcast(pack)

            self.update_projectiles(time.time() - self.last_iter_time)
            self.check_collisions()

            self._wait_for_tick(start_time)

    def _wait_for_tick(self, start_time) -> None:
        """
        Waiting for the next tick to be due, targetting self.tick_rate
        """
        end_time = time.time()
        self.last_iter_time = end_time
        target = 1 / self.tick_rate
        delta_time = end_time - start_time
        time.sleep(target - delta_time)

    def onboard_player(self, packet, addr) -> None:
        self._player_index += 1

        name = packet.payload.decode()
        self.connections[addr] = Connection(addr)
        self.connections[addr].name = name
        self.connections[addr].id = self._player_index
        packet = Packet(PacketType.ONBOARD, 1, PayloadFormat.ONBOARD.pack(self._player_index))
        self._send_packet(packet, addr)

    def handle_request(self, data: bytes, addr) -> None:
        LOGGER.debug("handling data: %s from %s", data, addr)
        try:
            packet = Packet.deserialize(data)
        except ValueError as e:
            LOGGER.error(e)
            return

        if packet.packet_type == PacketType.CONNECT:
            self.onboard_player(packet, addr)

        if packet.packet_type == PacketType.COORDINATES:
            _, x, y = PayloadFormat.COORDINATES.unpack(packet.payload)
            position = (x, y)
            self.connections[addr].position = position

        if packet.packet_type == PacketType.SHOOT:
            x_pos, y_pos, x_vel, y_vel = PayloadFormat.SHOOT.unpack(packet.payload)
            proj = Projectile()
            proj.position = (x_pos, y_pos)
            proj.velocity = (x_vel, y_vel)
            self.projectiles[len(self.projectiles)] = proj

            self.broadcast(packet)

    def broadcast(self, packet: Packet) -> None:
        for addr in self.connections.keys():
            self._send_packet(packet, addr)

    def start(self, address: str = "127.0.0.1", port: int = 5001) -> None:
        """
        Start the UDP server
        """
        LOGGER.info("starting UDP server")
        self.running = True
        self.sock.bind((address, port))
        threading.Thread(target=self.loop, daemon=True).start()

        while self.running:
            data, addr = self.sock.recvfrom(BUFF_SIZE)
            threading.Thread(target=self.handle_request,
                             args=(data, addr)).start()


if __name__ == "__main__":
    LOGGER.setLevel(logging.DEBUG)
    s = Server()
    s.start()
