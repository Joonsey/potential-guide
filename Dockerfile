FROM python:3.12-slim

WORKDIR /game_server

COPY . /game_server

RUN pip3 install pygame-ce

EXPOSE 30000

CMD ["python", "server.py"]
