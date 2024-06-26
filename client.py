from enum import IntEnum, auto
import time
import socket
import logging
import threading

from packet import Packet, PacketType, PayloadFormat
from settings import BUFF_SIZE, WAITING_ROOM_ID
from shared import LifecycleType, OnboardType, Projectile, ProjectileType


LOGGER = logging.getLogger("Client")


class EventType(IntEnum):
    FORCE_MOVE = auto()
    HIT = auto()
    RESSURECT = auto()
    WINNER = auto()


class Event:
    def __init__(self) -> None:
        self.event_type: EventType
        self.data: tuple

class Player:
    def __init__(self) -> None:
        # used for interpolation
        self.old_position: tuple[float, float] | None = None
        self.position: tuple[float, float] = (0, 0)
        self.rotation = 0
        self.barrel_rotation: float = 0
        self.id = 0
        self.name = ""
        self.score = 0
        self.interpolation_t: float = 0
        self.alive = True
        self.ready = False
        self.has_crown = False

    def __repr__(self) -> str:
        return f"<Player {self.name}, {self.position}, {self.score}>"


class Client:
    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.address: str = "127.0.0.1"
        self.port: int = 30000
        self._sequence_number = 0
        self.players: dict[int, Player] = {}
        self.projectiles: list[Projectile] = []
        self.id = 0
        self.running = False
        self.current_arena = 0
        self.spectating = False

        self.event_queue: list[Event] = []
        self.lifecycle_state: LifecycleType = LifecycleType.WAITING_ROOM
        self.lifecycle_context: float = 0

    def reset(self) -> None:
        for player in self.players.values():
            # Resurrecting all players
            player.alive = True

        self.projectiles.clear()

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

    def connect(self, address: str) -> None:
        self.address = address
        packet = Packet(PacketType.CONNECT,
                        self.sequence_number, b"connecting!")
        self._send_packet(packet)

    def disconnect(self) -> None:
        packet = Packet(PacketType.DISCONNECT,
                        self.sequence_number, b"disconnecting!")
        self._send_packet(packet)
        self.running = False

    def send_ready(self, ready: bool = True) -> None:
        packet = Packet(PacketType.READY,
                        self.sequence_number, PayloadFormat.READY.pack(ready))
        self._send_packet(packet)

    def handle_update_packet(self, packet: Packet) -> None:
        size = PayloadFormat.UPDATE.size
        player_count = len(packet.payload) // size

        for i in range(player_count):
            data = packet.payload[i * size: size + size * i]
            id, x, y, rotation, barrel_rotation, score, ready, has_crown = PayloadFormat.UPDATE.unpack(data)

            buff = self.players.copy()
            if id in buff.keys():
                player = buff[id]
                player.old_position = player.position
                player.position = (x, y)
                player.interpolation_t = 0
            else:
                player = Player()
                player.position = (x, y)

            player.score = score
            player.id = id
            player.rotation = rotation
            player.barrel_rotation = barrel_rotation
            player.ready = ready
            player.has_crown = has_crown
            self.players[id] = player

    def handle_lifecycle_change(self, state: LifecycleType, context: float) -> None:
        self.lifecycle_state = LifecycleType(state)
        self.lifecycle_context = context

        if state == LifecycleType.WAITING_ROOM:
            self.current_arena = WAITING_ROOM_ID
            event = Event()
            event.event_type = EventType.RESSURECT
            self.event_queue.append(event)

        if state == LifecycleType.NEW_ROUND:
            ...

        if state == LifecycleType.DONE:
            event = Event()
            event.event_type = EventType.WINNER
            event.data = (int(context), )
            self.event_queue.append(event)

            event = Event()
            event.event_type = EventType.RESSURECT
            self.event_queue.append(event)
            self.current_arena = WAITING_ROOM_ID

            self.reset()
            self.reset()

        if state in [LifecycleType.PLAYING]:
            event = Event()
            event.event_type = EventType.RESSURECT
            self.event_queue.append(event)
            self.current_arena = int(context)

            self.reset()

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
            onboard_type, data = PayloadFormat.ONBOARD.unpack(packet.payload)
            onboard_type = OnboardType(onboard_type)
            if onboard_type == OnboardType.PLAY:
                self.id = data
                self.spectating = False
            else:  #if onboard_type == OnboardType.SPECTATE
                self.id = 0
                self.spectating = True
                self.current_arena = data

        if packet.packet_type == PacketType.DISCONNECT:
            player_id, = PayloadFormat.DISCONNECT.unpack(packet.payload)
            if player_id in self.players.keys():
                del self.players[player_id]

        if packet.packet_type == PacketType.LIFECYCLE_CHANGE:
            state, context = PayloadFormat.LIFECYCLE_CHANGE.unpack(
                packet.payload)
            self.handle_lifecycle_change(state, context)

        if packet.packet_type == PacketType.FORCE_MOVE:
            id, x, y, rotation, barrel_rotation = PayloadFormat.COORDINATES.unpack(packet.payload)
            event = Event()
            event.event_type = EventType.FORCE_MOVE
            event.data = (x, y, rotation, barrel_rotation)
            self.event_queue.append(event)

        if packet.packet_type == PacketType.HIT:
            proj_id, hit_id = PayloadFormat.HIT.unpack(packet.payload)
            if hit_id not in self.players.keys():
                return

            self.players[hit_id].alive = self.lifecycle_state in [LifecycleType.WAITING_ROOM, LifecycleType.STARTING]
            event = Event()
            event.event_type = EventType.HIT
            event.data = (proj_id, hit_id)
            self.event_queue.append(event)

        if packet.packet_type == PacketType.SHOOT:
            id, x_pos, y_pos, x_vel, y_vel, projectile_type, sender_id = PayloadFormat.SHOOT.unpack(
                packet.payload)
            proj = Projectile(projectile_type)
            proj.position = (x_pos, y_pos)
            proj.velocity = (x_vel, y_vel)
            proj.start_position = (x_pos, y_pos)
            proj.id = id
            proj.sender_id = sender_id
            self.projectiles.append(proj)

    def listen(self) -> None:
        while self.running:
            data, addr = self.sock.recvfrom(BUFF_SIZE)
            threading.Thread(target=self.handle_response,
                             args=(data, addr)).start()

    def start(self) -> None:
        self.running = True
        threading.Thread(target=self.listen, daemon=True).start()

    def send_position(self, x: float, y: float, rotation: float, barrel_rotation: float) -> None:
        if not self.running or self.spectating:
            return

        packet = Packet(PacketType.COORDINATES, self.sequence_number,
                        PayloadFormat.COORDINATES.pack(
                            self.id, x, y,
                            rotation, barrel_rotation
                        ))
        self._send_packet(packet)

    def send_shoot(self, position: tuple[float, float], velocity: tuple[float, float], packet_type: ProjectileType) -> None:
        if not self.running or self.spectating:
            return

        packet = Packet(PacketType.SHOOT, self.sequence_number,
                        PayloadFormat.SHOOT.pack(
                            0,  # un-initialized
                            position[0],
                            position[1],
                            velocity[0],
                            velocity[1],
                            packet_type,
                            self.id
                        ))
        self._send_packet(packet)


if __name__ == "__main__":
    s = Client()
    s.connect("127.0.0.1")
    s.start()

    while True:
        time.sleep(.1)
