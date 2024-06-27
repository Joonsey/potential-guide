FROM python:3.12-slim

WORKDIR /game_server

COPY arenas /game_server/arenas
COPY server.py /game_server/server.py
COPY arena.py /game_server/arena.py
COPY packet.py /game_server/packet.py
COPY settings.py /game_server/settings.py
COPY shared.py /game_server/shared.py

RUN pip3 install pygame-ce

EXPOSE 30000

CMD ["python", "server.py"]
