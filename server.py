import math
import os
import socket
import threading
import time
import logging
import random
import pygame

from arena import Arena, Tile
from packet import Packet, PacketType, PayloadFormat
from settings import (
    BUFF_SIZE,
    CLEANUP_INTERVAL,
    DECISIVE_SCORE,
    GAME_INTERVAL,
    ROUND_INTERVAL,
    WAITING_ROOM_ID,
    WAITING_TIME,
)
from shared import NON_LETHAL_LIFECYCLES, LifecycleType, OnboardType, Projectile, ProjectileType, check_collision, get_distance


LOGGER = logging.getLogger("Server")


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
        self.ready = False
        self.time_last_packet = time.time()
        self.wins = 0


class Server:
    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.running = False
        self.connections: dict[tuple[str, int], Connection] = {}
        self.spectators: list[tuple[Packet, tuple[str, int]]] = []
        self.projectiles: dict[int, Projectile] = {}
        self._player_index = 0
        self._projectile_index = 0
        self.lifecycle_state: LifecycleType = LifecycleType.WAITING_ROOM
        self.lifecycle_context = 0
        self.round_index = 0

        self._current_arena = 0
        arena_names = os.listdir('arenas')
        arena_names.sort()
        self.arenas = [Arena(os.path.join('arenas', file)) for file in arena_names ]
        self.tile_collisions = []
        self.current_arena = WAITING_ROOM_ID


    @property
    def arena(self) -> Arena:
        return self.arenas[self.current_arena]

    def reset(self) -> None:
        for player in self.connections.values():
            # Resurrecting all players
            player.alive = True

        self.projectiles.clear()

    @property
    def current_arena(self) -> int:
        return self._current_arena

    @current_arena.setter
    def current_arena(self, val: int) -> None:
        self.tile_collisions = [
            pygame.Rect(tile.position[0],
                        tile.position[1], tile.width, tile.height)
            for tile in self.arenas[val].get_colliders()
        ]
        self.interactable_tiles = list(filter(lambda x: x.interactable, self.arenas[val].tiles))
        self._current_arena = val

    def new_arena(self):
        eligible_arenas = list(filter(lambda x: x.players_count >= len(self.connections), self.arenas))
        waiting_room = self.arenas[WAITING_ROOM_ID]
        if waiting_room in eligible_arenas:
            eligible_arenas.remove(waiting_room)
        chosen_arena = random.choice(eligible_arenas)
        self.current_arena = self.arenas.index(chosen_arena)

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

    def check_interactive_projectiles(self, projectile: Projectile, interactable_tiles_list: list[Tile]) -> None:
        new_pos_x, new_pos_y = projectile.position
        for tile in interactable_tiles_list:
            if (pygame.Rect(tile.position[0], tile.position[1], tile.width, tile.height)
                    .colliderect(pygame.Rect(new_pos_x, new_pos_y, 8, 8))):
                projectile.remaining_bounces = 0

    def update_projectiles(self, collision_list: list[pygame.Rect], interactable_tiles_list: list[Tile], dt: float) -> None:
        temp_proj = self.projectiles.copy()
        keys_to_remove = []
        for proj_id, proj in temp_proj.items():
            proj.grace_period = max(0, proj.grace_period - dt)
            if proj.lobbed:
                hit_pos = Projectile.update_lobbed_projectile(proj, dt)
                if hit_pos:
                    self.check_interactive_projectiles(proj, interactable_tiles_list)

                    if proj.projectile_type == ProjectileType.SHOCKWAVE:
                        for projectile in temp_proj.values():
                            # the newly made projectile gets deleted by the server instantly.
                            # we know that we always convert to sniper shots. for now. So we can simply check for this case
                            if proj != projectile and projectile.projectile_type != ProjectileType.SNIPER:
                                distance = get_distance(projectile.position, (hit_pos.x, hit_pos.y))
                                if distance < proj.radius:
                                    keys_to_remove.append(projectile.id)

                    if proj.hurts:
                        for player in list(filter(lambda x: x.alive, self.connections.values())):
                            if player.id == proj.sender_id and proj.grace_period:
                                # if sender is owner, and there is grace period left we skip
                                continue

                            player_center_pos = player.position[0] - 16, player.position[1] - 16
                            distance = get_distance(player_center_pos, proj.position)

                            if distance < proj.radius:
                                player.alive = self.lifecycle_state in NON_LETHAL_LIFECYCLES
                                self.send_hit(proj.id, player.id)
            else:
                Projectile.update_projectile(proj, collision_list, dt)
                self.check_interactive_projectiles(proj, interactable_tiles_list)

            if proj.remaining_bounces == 0:
                keys_to_remove.append(proj_id)

        for key in set(keys_to_remove):
            del self.projectiles[key]

    def update_lifecycle(self) -> None:
        if self.lifecycle_state == LifecycleType.WAITING_ROOM:
            if all(p.ready for p in self.connections.copy().values()):
                self.lifecycle_state = LifecycleType.STARTING
                self.lifecycle_context = time.time() + WAITING_TIME

        elif not len(self.connections.copy().values()):
            self.lifecycle_state = LifecycleType.WAITING_ROOM
            self.lifecycle_context = len(self.connections)
            self.current_arena = WAITING_ROOM_ID

        elif not all(p.ready for p in self.connections.copy().values()):
            self.lifecycle_state = LifecycleType.WAITING_ROOM
            self.lifecycle_context = len(self.connections)
            self.current_arena = WAITING_ROOM_ID

        elif self.lifecycle_state == LifecycleType.PLAYING:
            remaining_players = list(
                filter(lambda x: x.alive, self.connections.values()))
            if len(remaining_players) == 1:
                remaining_players[0].score += 1
                self.lifecycle_state = LifecycleType.NEW_ROUND
                self.lifecycle_context = time.time() + ROUND_INTERVAL
                self.round_index += 1
            if len(remaining_players) == 0:
                self.lifecycle_state = LifecycleType.NEW_ROUND
                self.lifecycle_context = time.time() + ROUND_INTERVAL
                self.round_index = 0
                return

            for player in self.connections.values():
                if player.score >= DECISIVE_SCORE:
                    self.current_arena = WAITING_ROOM_ID
                    self.round_index = 0
                    self.lifecycle_state = LifecycleType.DONE
                    self.new_game_time = time.time() + GAME_INTERVAL
                    self.lifecycle_context = player.id
                    player.wins += 1

        elif self.lifecycle_state == LifecycleType.DONE and time.time() >= self.new_game_time:
            self.lifecycle_state = LifecycleType.WAITING_ROOM
            self.lifecycle_context = len(self.connections)
            self.round_index = 0

        elif self.lifecycle_state in [LifecycleType.NEW_ROUND, LifecycleType.STARTING]:
            if time.time() >= self.lifecycle_context:
                self.lifecycle_state = LifecycleType.PLAYING
                self.new_arena()
                self.lifecycle_context = self.current_arena

    def check_lifecycle(self) -> None:
        old_state = self.lifecycle_state
        self.update_lifecycle()
        if old_state != self.lifecycle_state:
            packet = Packet(PacketType.LIFECYCLE_CHANGE, 0, PayloadFormat.LIFECYCLE_CHANGE.pack(
                self.lifecycle_state, self.lifecycle_context))
            self.broadcast(packet)
            if self.lifecycle_state in [LifecycleType.PLAYING, LifecycleType.DONE]:
                self.reset()
                i = 0
                for addr, player in self.connections.items():
                    new_pos = self.arena.spawn_positions[i % len(self.arena.spawn_positions)]
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

                for packet, addr in self.spectators:
                    self.onboard_player(packet, addr)

                self.spectators = []

    def check_tank_hit(self) -> None:
        projs_hit = []

        for proj in list(filter(lambda x: not x.lobbed, self.projectiles.values())):
            proj_rect = (proj.position[0], proj.position[1], 8, 8)
            for player in list(filter(lambda x: x.alive, self.connections.values())):
                if player.id == proj.sender_id and proj.grace_period:
                    # if sender is owner, and there is grace period left we skip
                    continue

                player_rect = (player.position[0], player.position[1], 16, 16)
                if check_collision(proj_rect, player_rect):
                    projs_hit.append(proj.id)
                    player.alive = self.lifecycle_state in NON_LETHAL_LIFECYCLES
                    self.send_hit(proj.id, player.id)

        for proj_id in projs_hit:
            if proj_id in self.projectiles.keys():
                del self.projectiles[proj_id]

    def broadcast_for_spectators(self, packet: Packet):
        for _, addr in self.spectators:
            self._send_packet(packet, addr)

    def cleanup_stale_connections(self, now: float) -> None:
        addr_to_cleanup = []
        for addr, conn in self.connections.copy().items():
            if conn.time_last_packet <= now - CLEANUP_INTERVAL:
                packet = Packet(PacketType.DISCONNECT, 0, PayloadFormat.DISCONNECT.pack(conn.id))
                self.broadcast(packet)
                addr_to_cleanup.append(addr)

        for addr in addr_to_cleanup:
            del self.connections[addr]


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
                    item.score,
                    item.ready,
                    item.wins > 0
                )
            pack = Packet(PacketType.UPDATE, 0, update_data)
            self.broadcast(pack)

            self.check_lifecycle()

            self.cleanup_stale_connections(time.time())

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
                        PayloadFormat.ONBOARD.pack(OnboardType.PLAY, self._player_index))
        self._send_packet(packet, addr)

    def allow_new_connection(self) -> bool:
        return self.lifecycle_state in [LifecycleType.STARTING, LifecycleType.WAITING_ROOM]

    def handle_request(self, data: bytes, addr) -> None:
        LOGGER.debug("handling data: %s from %s", data, addr)
        try:
            packet = Packet.deserialize(data)
        except ValueError as e:
            LOGGER.error(e)
            return

        if packet.packet_type == PacketType.CONNECT:
            if self.allow_new_connection():
                self.onboard_player(packet, addr)
            else:
                self.spectators.append((packet, addr))
                packet = Packet(PacketType.ONBOARD, 1,
                                PayloadFormat.ONBOARD.pack(OnboardType.SPECTATE, self.current_arena))
                self._send_packet(packet, addr)

        if packet.packet_type == PacketType.DISCONNECT:
            try:
                player_id = self.connections[addr].id
                del self.connections[addr]
                packet.payload = PayloadFormat.DISCONNECT.pack(player_id)
                self.broadcast(packet)
            except:
                self.spectators = list(filter(lambda x: x[1] != addr, self.spectators))

        if addr not in self.connections:
            return

        self.connections[addr].time_last_packet = time.time()

        if packet.packet_type == PacketType.COORDINATES:
            _, x, y, rotation, barrel_rotation = PayloadFormat.COORDINATES.unpack(
                packet.payload)
            position = (x, y)
            self.connections[addr].position = position
            self.connections[addr].rotation = rotation
            self.connections[addr].barrel_rotation = barrel_rotation


        if packet.packet_type == PacketType.READY:
            ready, = PayloadFormat.READY.unpack(packet.payload)
            self.connections[addr].ready = ready

        if packet.packet_type == PacketType.SHOOT:
            _, x_pos, y_pos, x_vel, y_vel, projectile_type, _ = PayloadFormat.SHOOT.unpack(
                packet.payload)

            new_id = self._projectile_index
            self._projectile_index += 1

            sender_id = self.connections[addr].id
            proj = Projectile(projectile_type)
            proj.id = new_id
            proj.position = (x_pos, y_pos)
            proj.velocity = (x_vel, y_vel)
            proj.sender_id = sender_id
            self.projectiles[new_id] = proj

            packet.payload = PayloadFormat.SHOOT.pack(
                new_id, x_pos, y_pos, x_vel, y_vel, projectile_type, sender_id)

            self.broadcast(packet)

    def broadcast(self, packet: Packet) -> None:
        for addr in self.connections.copy().keys():
            self._send_packet(packet, addr)

        self.broadcast_for_spectators(packet)

    def simulation_loop(self):
        """
        Entry point for game simulation loop
        """
        LOGGER.info("simulation loop up!")
        last_iter_time = 0
        while self.running:
            start_time = time.time()
            self.update_projectiles(
                self.tile_collisions, self.interactable_tiles, time.time() - last_iter_time)
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
