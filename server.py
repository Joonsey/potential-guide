import socket
import threading
import time
import logging

from packet import Packet, PacketType, PayloadFormat

BUFF_SIZE = 1024


LOGGER = logging.getLogger("Server")


def check_collision(rect: tuple[float, float, float, float], other_rect: tuple[float, float, float, float]) -> bool:
    x1, y1, w1, h1 = rect
    x2, y2, w2, h2 = other_rect

    overlap_x = (x1 < x2 + w2) and (x2 < x1 + w1)
    overlap_y = (y1 < y2 + h2) and (y2 < y1 + h1)
    return overlap_x and overlap_y


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
        self.id = 0
        self.position: tuple[float, float] = (0, 0)
        self.velocity = (0, 0)
        self.alive = True
        self.sender_id = 0
        self.grace_period = 0.5


class Server:
    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.running = False
        self.tick_rate = 20
        self.connections: dict[tuple[str, int], Connection] = {}
        self.projectiles: dict[int, Projectile] = {}
        self._player_index = 0
        self._projectile_index = 0

    def _send(self, data: bytes, address: tuple[str, int]) -> None:
        self.sock.sendto(data, address)

    def _send_packet(self, packet: Packet, address: tuple[str, int]) -> None:
        self._send(packet.serialize(), address)

    def send_hit(self, proj_id: int, hit_it: int):
        packet = Packet(PacketType.HIT, 0,
                        PayloadFormat.HIT.pack(
                            proj_id,
                            hit_it
                        ))
        self.broadcast(packet)

    def update_projectiles(self, delta_time: float) -> None:
        for _, proj in self.projectiles.items():
            proj.grace_period = max(0, proj.grace_period - delta_time)
            if not proj.alive:
                continue

            x, y = proj.position
            vel_x, vel_y = proj.velocity

            pos_x = x + vel_x * delta_time * proj.SPEED
            pos_y = y + vel_y * delta_time * proj.SPEED

            proj.position = (pos_x, pos_y)

    def check_tank_hit(self) -> None:
        projs_hit = []

        for proj in list(filter(lambda x: x.alive, self.projectiles.values())):
            proj_rect = (proj.position[0], proj.position[1], 8, 8)
            for player in self.connections.values():
                if player.id == proj.sender_id and proj.grace_period:
                    # if sender is owner, and there is grace period left we skip
                    continue

                player_rect = (player.position[0], player.position[1], 16, 16)
                if check_collision(proj_rect, player_rect):
                    sender_list = list(
                        filter(lambda x: x.id == proj.sender_id, self.connections.values()))
                    if sender_list:
                        sender = sender_list[0]
                        sender.score += 1

                    projs_hit.append(proj.id)
                    self.send_hit(proj.id, player.id)

        for proj_id in projs_hit:
            del self.projectiles[proj_id]

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
            self.check_tank_hit()

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
        packet = Packet(PacketType.ONBOARD, 1,
                        PayloadFormat.ONBOARD.pack(self._player_index))
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
            _, x_pos, y_pos, x_vel, y_vel = PayloadFormat.SHOOT.unpack(packet.payload)

            new_id = self._projectile_index
            self._projectile_index += 1

            proj = Projectile()
            proj.id = new_id
            proj.position = (x_pos, y_pos)
            proj.velocity = (x_vel, y_vel)
            proj.sender_id = self.connections[addr].id
            self.projectiles[new_id] = proj

            packet.payload = PayloadFormat.SHOOT.pack(new_id, x_pos, y_pos, x_vel, y_vel)

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
