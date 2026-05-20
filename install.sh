#!/usr/bin/env bash
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$HOME/.config/vpn-manager"
CONFIG_FILE="$CONFIG_DIR/config"
AUTOSTART_DIR="$HOME/.config/autostart"
DESKTOP_DST="$AUTOSTART_DIR/vpn-tray.desktop"

echo "=== OpenVPN3 Tray Manager – installer ==="
echo

# ── 1. Python dependencies ─────────────────────────────────────────────────────
echo "Checking Python dependencies..."
MISSING=()
python3 -c "import dbus" 2>/dev/null         || MISSING+=("python3-dbus")
python3 -c "from gi.repository import GLib" 2>/dev/null || MISSING+=("python3-gi")
python3 -c "from PIL import Image" 2>/dev/null           || MISSING+=("python3-pil  (pip: Pillow)")

if [ ${#MISSING[@]} -gt 0 ]; then
    echo
    echo "Missing packages:"
    for pkg in "${MISSING[@]}"; do echo "  - $pkg"; done
    echo
    echo "Install them with:"
    echo "  sudo apt install python3-dbus python3-gi python3-pil"
    echo "  # or: pip install dbus-python PyGObject Pillow"
    echo
    read -rp "Continue anyway? [y/N] " cont
    [[ "$cont" =~ ^[yY]$ ]] || exit 1
fi

# ── 2. VPN profile name ────────────────────────────────────────────────────────
echo
CURRENT_VPN=""
CURRENT_LANG="pl"

if [ -f "$CONFIG_FILE" ]; then
    while IFS='=' read -r key value; do
        key="${key// /}"; value="${value// /}"
        [[ "$key" == "vpn_profile" ]] && CURRENT_VPN="$value"
        [[ "$key" == "language"    ]] && CURRENT_LANG="$value"
    done < "$CONFIG_FILE"
fi

# Try to list available VPN profiles
VPN_PROFILES=()
if command -v openvpn3 &>/dev/null; then
    while IFS= read -r line; do
        # Skip header/separator lines, grab first word (profile name)
        [[ "$line" =~ ^[-\ ]*$ ]] && continue
        [[ "$line" =~ ^Configuration ]] && continue
        name=$(echo "$line" | awk '{print $1}')
        [ -n "$name" ] && VPN_PROFILES+=("$name")
    done < <(openvpn3 configs-list 2>/dev/null)
fi

if [ ${#VPN_PROFILES[@]} -gt 0 ]; then
    echo "Available VPN profiles:"
    for i in "${!VPN_PROFILES[@]}"; do
        marker=""
        [[ "${VPN_PROFILES[$i]}" == "$CURRENT_VPN" ]] && marker=" (current)"
        echo "  $((i+1))) ${VPN_PROFILES[$i]}$marker"
    done
    echo
    if [ -n "$CURRENT_VPN" ]; then
        read -rp "Choose profile [1-${#VPN_PROFILES[@]}] or type name (Enter = keep '$CURRENT_VPN'): " vpn_choice
    else
        read -rp "Choose profile [1-${#VPN_PROFILES[@]}] or type name: " vpn_choice
    fi

    if [ -z "$vpn_choice" ] && [ -n "$CURRENT_VPN" ]; then
        VPN_NAME="$CURRENT_VPN"
    elif [[ "$vpn_choice" =~ ^[0-9]+$ ]] && [ "$vpn_choice" -ge 1 ] && [ "$vpn_choice" -le "${#VPN_PROFILES[@]}" ]; then
        VPN_NAME="${VPN_PROFILES[$((vpn_choice-1))]}"
    else
        VPN_NAME="$vpn_choice"
    fi
else
    # openvpn3 not found or no profiles – manual entry
    echo "Enter your VPN profile name (shown by: openvpn3 configs-list)"
    if [ -n "$CURRENT_VPN" ]; then
        read -rp "VPN profile name (Enter = keep '$CURRENT_VPN'): " VPN_NAME
        VPN_NAME="${VPN_NAME:-$CURRENT_VPN}"
    else
        read -rp "VPN profile name: " VPN_NAME
    fi
fi

if [ -z "$VPN_NAME" ]; then
    echo "Error: profile name cannot be empty." >&2
    exit 1
fi

# ── 3. Language ────────────────────────────────────────────────────────────────
echo
echo "Choose interface language:"
echo "  1) Polski          [pl]  (default)"
echo "  2) English         [en]"
echo "  3) Deutsch         [de]"
echo "  4) Italiano        [it]"
echo "  5) Français        [fr]"
echo "  6) Čeština         [cs]"
echo "  7) Slovenčina      [sk]"
echo "  8) 中文 (简体)      [zh]"
echo

if [ -n "$CURRENT_LANG" ] && [ "$CURRENT_LANG" != "pl" ]; then
    read -rp "Language [1-8] (Enter = keep '$CURRENT_LANG'): " lang_choice
else
    read -rp "Language [1-8] (Enter = pl): " lang_choice
fi

case "$lang_choice" in
    1|"") LANGUAGE="pl" ;;
    2)    LANGUAGE="en" ;;
    3)    LANGUAGE="de" ;;
    4)    LANGUAGE="it" ;;
    5)    LANGUAGE="fr" ;;
    6)    LANGUAGE="cs" ;;
    7)    LANGUAGE="sk" ;;
    8)    LANGUAGE="zh" ;;
    *)
        # If they typed a code directly (e.g. "en"), accept it
        if echo "pl en de it fr cs sk zh" | grep -qw "$lang_choice"; then
            LANGUAGE="$lang_choice"
        else
            echo "Invalid choice, defaulting to pl."
            LANGUAGE="pl"
        fi
        ;;
esac

# ── 4. Save config ─────────────────────────────────────────────────────────────
mkdir -p "$CONFIG_DIR"
cat > "$CONFIG_FILE" <<EOF
vpn_profile=$VPN_NAME
language=$LANGUAGE
EOF
echo "✓ Config saved: $CONFIG_FILE"

# ── 5. Autostart .desktop file ─────────────────────────────────────────────────
mkdir -p "$AUTOSTART_DIR"
cat > "$DESKTOP_DST" <<EOF
[Desktop Entry]
Name=VPN Manager
Comment=OpenVPN3 tray manager
Exec=/usr/bin/python3 $REPO_DIR/vpn-tray.py
Icon=network-vpn
Terminal=false
Type=Application
Categories=Network;
StartupNotify=false
EOF
chmod +x "$DESKTOP_DST"
echo "✓ Autostart configured: $DESKTOP_DST"

# ── 6. Script permissions ──────────────────────────────────────────────────────
chmod +x "$REPO_DIR/vpn-tray.py"
echo "✓ vpn-tray.py permissions set"

# ── 7. Done ────────────────────────────────────────────────────────────────────
echo
echo "=== Installation complete! ==="
echo
echo "It will start automatically on every login."
echo "Starting the app now..."
echo

# Kill any running instance first, then launch fresh
pkill -f vpn-tray.py 2>/dev/null || true
sleep 0.5
nohup python3 "$REPO_DIR/vpn-tray.py" >/dev/null 2>&1 &
echo "✓ VPN Manager started (PID $!)"
