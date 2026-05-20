#!/usr/bin/env bash
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$HOME/.config/vpn-manager"
CONFIG_FILE="$CONFIG_DIR/config"
AUTOSTART_DIR="$HOME/.config/autostart"
DESKTOP_SRC="$REPO_DIR/vpn-tray.desktop"
DESKTOP_DST="$AUTOSTART_DIR/vpn-tray.desktop"

echo "=== OpenVPN3 Tray Manager – instalator ==="
echo

# ── 1. Zależności systemowe ────────────────────────────────────────────────────
echo "Sprawdzam zależności Pythona..."
MISSING=()
python3 -c "import dbus" 2>/dev/null || MISSING+=("python3-dbus")
python3 -c "from gi.repository import GLib" 2>/dev/null || MISSING+=("python3-gi")
python3 -c "from PIL import Image" 2>/dev/null || MISSING+=("python3-pil (pip: Pillow)")

if [ ${#MISSING[@]} -gt 0 ]; then
    echo
    echo "Brakuje następujących pakietów:"
    for pkg in "${MISSING[@]}"; do
        echo "  - $pkg"
    done
    echo
    echo "Zainstaluj je np. przez:"
    echo "  sudo apt install python3-dbus python3-gi python3-pil"
    echo "  # lub: pip install dbus-python PyGObject Pillow"
    echo
    read -rp "Kontynuować mimo to? [t/N] " cont
    [[ "$cont" =~ ^[tTyY]$ ]] || exit 1
fi

# ── 2. Nazwa profilu VPN ───────────────────────────────────────────────────────
echo
if [ -f "$CONFIG_FILE" ]; then
    CURRENT=$(cat "$CONFIG_FILE")
    echo "Znaleziono istniejącą konfigurację: $CURRENT"
    read -rp "Podaj nazwę profilu VPN (Enter = zostaw '$CURRENT'): " VPN_NAME
    VPN_NAME="${VPN_NAME:-$CURRENT}"
else
    echo "Podaj nazwę profilu VPN (widoczna w: openvpn3 configs-list)"
    read -rp "Nazwa profilu: " VPN_NAME
    if [ -z "$VPN_NAME" ]; then
        echo "Błąd: nazwa profilu nie może być pusta." >&2
        exit 1
    fi
fi

# ── 3. Zapisz konfigurację ─────────────────────────────────────────────────────
mkdir -p "$CONFIG_DIR"
echo "$VPN_NAME" > "$CONFIG_FILE"
echo "✓ Konfiguracja zapisana: $CONFIG_FILE"

# ── 4. Plik .desktop z autostartem ────────────────────────────────────────────
mkdir -p "$AUTOSTART_DIR"
sed "s|~/vpn-manager|$REPO_DIR|g" "$DESKTOP_SRC" > "$DESKTOP_DST"
chmod +x "$DESKTOP_DST"
echo "✓ Autostart skonfigurowany: $DESKTOP_DST"

# ── 5. Uprawnienia do skryptu ─────────────────────────────────────────────────
chmod +x "$REPO_DIR/vpn-tray.py"
echo "✓ Uprawnienia do vpn-tray.py ustawione"

# ── 6. Gotowe ──────────────────────────────────────────────────────────────────
echo
echo "=== Instalacja zakończona! ==="
echo
echo "Uruchom aplikację teraz:"
echo "  python3 $REPO_DIR/vpn-tray.py"
echo
echo "Przy następnym logowaniu uruchomi się automatycznie."
