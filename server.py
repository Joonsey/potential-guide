import socket
import threading
import time
import logging
import pygame

from arena import Arena
from packet import LifecycleType, Packet, PacketType, PayloadFormat, Projectile
from settings import (
    BUFF_SIZE,
    ROUND_INTERVAL,
    WAITING_TIME,
    SCREEN_WIDTH,
    SCREEN_HEIGHT
)



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
        self.position: tuple[float, float] = (0, 0)
        self.rotation = 0
        self.barrel_rotation: float = 0
        self.name = ""
        self.score = 0
        self.alive = True


class Server:
    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.running = False
        self.connections: dict[tuple[str, int], Connection] = {}
        self.projectiles: dict[int, Projectile] = {}
        self._player_index = 0
        self._projectile_index = 0
        self.lifecycle_state: LifecycleType = LifecycleType.WAITING_ROOM
        self.lifecycle_context = 0

        self.arena = Arena("arena", (SCREEN_WIDTH, SCREEN_HEIGHT))  # TODO!!: refactor

        self.tile_collisions = [
            pygame.Rect(tile.position[0],
                        tile.position[1], tile.width, tile.height)
            for tile in self.arena.get_colliders()
        ]

    def reset(self) -> None:
        for player in self.connections.values():
            # Resurrecting all players
            player.alive = True

        self.projectiles.clear()

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

    def update_projectiles(self, collision_list: list[pygame.Rect], dt: float) -> None:
        temp_proj = self.projectiles.copy()
        keys_to_remove = []
        for proj_id, proj in temp_proj.items():
            proj.grace_period = max(0, proj.grace_period - dt)
            x, y = proj.position
            vel_x, vel_y = proj.velocity
            colided = False

            # Calculate new potential position
            new_pos_x = x + vel_x * dt * proj.speed
            new_pos_y = y + vel_y * dt * proj.speed

            # Check for vertical collisions
            if any(pygame.Rect(x, new_pos_y, 8, 8).colliderect(rect) for rect in collision_list):
                colided = True

                # Reflect the velocity on the y-axis
                vel_y = -vel_y
                # Set new position with reflected velocity
                new_pos_y = y + vel_y * dt * Projectile.SPEED


            # Check for horizontal collisions
            if any(pygame.Rect(new_pos_x, y, 8, 8).colliderect(rect) for rect in collision_list):
                colided = True
                # Reflect the velocity on the x-axis
                vel_x = -vel_x
                # Set new position with reflected velocity
                new_pos_x = x + vel_x * dt * Projectile.SPEED

            # Update the projectile's position and velocity
            if colided:
                if proj.remaining_bounces == 0:
                    keys_to_remove.append(proj_id)
                    continue
                proj.remaining_bounces -= 1

            proj.position = (new_pos_x, new_pos_y)
            proj.velocity = (vel_x, vel_y)

        for key in keys_to_remove:
            del temp_proj[key]
        self.projectiles = temp_proj

    def update_lifecycle(self) -> None:
        if self.lifecycle_state == LifecycleType.WAITING_ROOM:
            if len(self.connections) == self.arena.players_count:
                self.lifecycle_state = LifecycleType.STARTING
                self.lifecycle_context = time.time() + WAITING_TIME

        elif len(self.connections) < self.arena.players_count:
            self.lifecycle_state = LifecycleType.WAITING_ROOM
            self.lifecycle_context = len(self.connections)

        elif self.lifecycle_state == LifecycleType.PLAYING:
            remaining_players = list(
                filter(lambda x: x.alive, self.connections.values()))
            if len(remaining_players) == 1:
                remaining_players[0].score += 1
                self.lifecycle_state = LifecycleType.NEW_ROUND
                self.lifecycle_context = time.time() + ROUND_INTERVAL

        elif self.lifecycle_state in [LifecycleType.NEW_ROUND, LifecycleType.STARTING] and time.time() >= self.lifecycle_context:
            self.lifecycle_state = LifecycleType.PLAYING

    def check_lifecycle(self) -> None:
        old_state = self.lifecycle_state
        self.update_lifecycle()
        if old_state != self.lifecycle_state:
            packet = Packet(PacketType.LIFECYCLE_CHANGE, 0, PayloadFormat.LIFECYCLE_CHANGE.pack(
                self.lifecycle_state, self.lifecycle_context))
            self.broadcast(packet)
            if self.lifecycle_state in [LifecycleType.PLAYING]:
                self.reset()
                i = 0
                for addr, player in self.connections.items():
                    new_pos = self.arena.spawn_positions[i]
                    i += 1

                    packet = Packet(
                        PacketType.FORCE_MOVE, 0,
                        PayloadFormat.COORDINATES.pack(
                            player.id, *new_pos, 0, 0
                        ))

                    player.position = new_pos

                    self._send_packet(packet, addr)



            if self.lifecycle_state == LifecycleType.WAITING_ROOM:
                for player in self.connections.values():
                    player.score = 0

    def check_tank_hit(self) -> None:
        projs_hit = []

        for proj in self.projectiles.values():
            proj_rect = (proj.position[0], proj.position[1], 8, 8)
            for player in self.connections.values():
                if player.id == proj.sender_id and proj.grace_period:
                    # if sender is owner, and there is grace period left we skip
                    continue

                player_rect = (player.position[0], player.position[1], 16, 16)
                if check_collision(proj_rect, player_rect):
                    projs_hit.append(proj.id)
                    player.alive = False
                    self.send_hit(proj.id, player.id)

        for proj_id in projs_hit:
            del self.projectiles[proj_id]

    def loop(self) -> None:
        """
        Entry point for main update loop
        """
        LOGGER.info("main loop up!")
        last_iter_time = 0
        while self.running:
            start_time = time.time()

            update_data = b""
            for _, item in self.connections.items():
                update_data += PayloadFormat.UPDATE.pack(
                    item.id,
                    item.position[0],
                    item.position[1],
                    item.rotation,
                    item.barrel_rotation,
                    item.score
                )
            pack = Packet(PacketType.UPDATE, 0, update_data)
            self.broadcast(pack)

            self.check_lifecycle()

            last_iter_time = self._wait_for_tick(start_time, 20)

    def _wait_for_tick(self, start_time: float, tick_rate: int) -> float:
        """
        Waiting for the next tick to be due
        """
        end_time = time.time()
        target = 1 / tick_rate
        delta_time = end_time - start_time
        time.sleep(max(target - delta_time, 0))
        return end_time

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
            _, x, y, rotation, barrel_rotation = PayloadFormat.COORDINATES.unpack(packet.payload)
            position = (x, y)
            self.connections[addr].position = position
            self.connections[addr].rotation = rotation
            self.connections[addr].barrel_rotation = barrel_rotation

        if packet.packet_type == PacketType.DISCONNECT:
            player_id = self.connections[addr].id
            del self.connections[addr]
            packet.payload = PayloadFormat.DISCONNECT.pack(player_id)
            self.broadcast(packet)

        if packet.packet_type == PacketType.SHOOT:
            _, x_pos, y_pos, x_vel, y_vel, projectile_type = PayloadFormat.SHOOT.unpack(
                packet.payload)

            new_id = self._projectile_index
            self._projectile_index += 1

            proj = Projectile(projectile_type)
            proj.id = new_id
            proj.position = (x_pos, y_pos)
            proj.velocity = (x_vel, y_vel)
            proj.sender_id = self.connections[addr].id
            self.projectiles[new_id] = proj

            packet.payload = PayloadFormat.SHOOT.pack(
                new_id, x_pos, y_pos, x_vel, y_vel, projectile_type)

            self.broadcast(packet)

    def broadcast(self, packet: Packet) -> None:
        for addr in self.connections.keys():
            self._send_packet(packet, addr)

    def simulation_loop(self):
        """
        Entry point for game simulation loop
        """
        LOGGER.info("simulation loop up!")
        last_iter_time = 0
        while self.running:
            start_time = time.time()
            self.update_projectiles(self.tile_collisions, time.time() - last_iter_time)
            self.check_tank_hit()

            last_iter_time = self._wait_for_tick(start_time, 60)

    def start(self, address: str = "0.0.0.0", port: int = 5555) -> None:
        """
        Start the UDP server
        """
        LOGGER.info("starting UDP server")
        self.running = True
        self.sock.bind((address, port))
        threading.Thread(target=self.loop, daemon=True).start()
        threading.Thread(target=self.simulation_loop, daemon=True).start()

        while self.running:
            data, addr = self.sock.recvfrom(BUFF_SIZE)
            threading.Thread(target=self.handle_request,
                             args=(data, addr)).start()


if __name__ == "__main__":
    LOGGER.setLevel(logging.DEBUG)
    s = Server()
    s.start()
