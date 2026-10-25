#!/bin/bash
# Builds ~/.kage/bin/KageCalendar.app (ad-hoc signed). Run with `open` so macOS attributes the permission to it.
set -e
cd "$(dirname "$0")"
APP="$HOME/.kage/bin/KageCalendar.app"
mkdir -p "$APP/Contents/MacOS"
swiftc -O main.swift -o "$APP/Contents/MacOS/kage-calendar"
cp Info.plist "$APP/Contents/Info.plist"
codesign --force -s - "$APP"
echo "$APP"
