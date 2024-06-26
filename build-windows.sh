#!/usr/bin/sh

wine pyinstaller --onefile --windowed main.py
cp -r assets dist
cp -r arenas dist
zip -r dist.zip dist
