# Panks

tank dualing game!

## Setup

```sh
poetry install
poetry run python server.py

# in a new terminal

poetry run python main.py
```

## Compile for windows on linux

```sh 
sudo apt install wine
curl https://www.python.org/ftp/python/3.11.1/python-3.11.1-amd64.exe
wine python-3.11.1-amd64.exe
# complete installation, add python to path!

rm python-3.11.1-amd64.exe
wine pip install pyinstaller pygame-ce # alternatively additional dependencies
wine pyisntaller --onefile --windowed main.py
```

A 'main.exe' file should appear in the 'build' directory. It still needs to be able to source the assets directory when shipped however, so remember to copy the assets directory over.

Same procedure would apply if you for whatever reason wanted to build a windows executable of the server. Please don't.
