#!/usr/bin/env python3
"""VPN tray via KDE StatusNotifierItem D-Bus protocol."""
import os
import struct
import subprocess
import sys
import threading

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

try:
    import openvpn3
    from openvpn3.constants import StatusMinor as OV3Minor
    _OV3_ERROR_MINORS = {
        OV3Minor.CONN_AUTH_FAILED,
    }
    _OV3_SDK = True
except ImportError:
    _OV3_SDK = False

POLL_INTERVAL = 10  # seconds
SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))

_CONFIG_FILE = os.path.expanduser("~/.config/vpn-manager/config")

def _load_config_name() -> str:
    if os.path.isfile(_CONFIG_FILE):
        with open(_CONFIG_FILE) as f:
            name = f.read().strip()
        if name:
            return name
    print(
        f"Błąd: brak pliku konfiguracyjnego {_CONFIG_FILE}\n"
        "Uruchom najpierw skrypt instalacyjny:\n"
        "  bash install.sh",
        file=sys.stderr,
    )
    sys.exit(1)

CONFIG_NAME = _load_config_name()
ICON_ON       = os.path.join(SCRIPT_DIR, "icon_on.png")
ICON_OFF      = os.path.join(SCRIPT_DIR, "icon_off.png")

# Stany połączenia VPN
ST_CONNECTED    = "connected"
ST_CONNECTING   = "connecting"   # sesja istnieje, ale "Client connected" jeszcze brak
ST_ERROR        = "error"        # sesja istnieje, ale wystąpił błąd (np. auth failed)
ST_DISCONNECTED = "disconnected"

SNI_IFACE  = "org.kde.StatusNotifierItem"
SNW_IFACE  = "org.kde.StatusNotifierWatcher"
SNW_PATH   = "/StatusNotifierWatcher"
MENU_IFACE = "com.canonical.dbusmenu"


# ── ikony: PNG → ARGB32 big-endian array dla SNI ──────────────────────────────

def png_to_sni_pixmap(path: str, tint_rgb=None):
    """Wczytuje PNG i konwertuje do formatu (width, height, ARGB-bytes) dla SNI.

    tint_rgb: opcjonalna krotka (R, G, B) – koloruje ikonę zachowując oryginalną alfę.
    """
    try:
        from PIL import Image, ImageOps
        img = Image.open(path).convert("RGBA")
        if tint_rgb is not None:
            alpha = img.split()[3]
            gray  = ImageOps.grayscale(img)
            tinted = ImageOps.colorize(gray, black=(0, 0, 0), white=tint_rgb)
            tinted = tinted.convert("RGBA")
            tinted.putalpha(alpha)
            img = tinted
        w, h = img.size
        pixels = list(img.getdata())
        out = bytearray(w * h * 4)
        for i, (r, g, b, a) in enumerate(pixels):
            struct.pack_into(">BBBB", out, i * 4, a, r, g, b)
        return dbus.Struct(
            (dbus.Int32(w), dbus.Int32(h), dbus.Array(bytes(out), signature="y")),
            signature=None,
        )
    except ImportError:
        pass

    # fallback: PyQt6 offscreen (bez tintowania)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QImage
    _app = QApplication.instance() or QApplication([])
    img = QImage(path).convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    raw = img.bits().asarray(w * h * 4)
    out = bytearray(w * h * 4)
    for i in range(w * h):
        b, g, r, a = raw[i*4], raw[i*4+1], raw[i*4+2], raw[i*4+3]
        struct.pack_into(">BBBB", out, i * 4, a, r, g, b)
    return dbus.Struct(
        (dbus.Int32(w), dbus.Int32(h), dbus.Array(bytes(out), signature="y")),
        signature=None,
    )


# ── VPN helpers ────────────────────────────────────────────────────────────────

def get_vpn_status():
    """Zwraca (state, status_message, auth_url).

    auth_url jest ustawiony gdy sesja czeka na autoryzację OAuth.
    Parsuje wyjście openvpn3 sessions-list blokowo – każdy nowy blok sesji
    (linia zaczynająca się od "-----" lub "        Path:") resetuje kontekst.
    """
    try:
        r = subprocess.run(
            ["openvpn3", "sessions-list"],
            capture_output=True, text=True, timeout=5,
        )
        in_our_session = False
        has_session    = False
        session_path   = None
        status_msg     = ""
        our_status_msg = ""   # persystuje przez końcowy reset "-----"
        for line in r.stdout.splitlines():
            # nowy blok sesji
            if line.startswith("-----") or line.startswith("        Path:"):
                in_our_session = False
                status_msg     = ""
                if line.startswith("        Path:"):
                    session_path = line.split()[-1]
            if CONFIG_NAME in line:
                in_our_session = True
                has_session    = True
            if in_our_session:
                if "Client connected" in line:
                    return (ST_CONNECTED, "", "")
                stripped = line.strip()
                if stripped.startswith("Status:"):
                    status_msg     = stripped[len("Status:"):].strip()
                    our_status_msg = status_msg   # zachowaj przed ewentualnym resetem
        if has_session:
            if _OV3_SDK and session_path:
                auth_url, is_error, sdk_msg = _get_session_extra(session_path)
                if is_error:
                    return (ST_ERROR, our_status_msg or sdk_msg, "")
                return (ST_CONNECTING, our_status_msg, auth_url)
            # fallback bez SDK: heurystyka po treści statusu
            low = our_status_msg.lower()
            if "failed" in low or "error" in low:
                return (ST_ERROR, our_status_msg, "")
            return (ST_CONNECTING, our_status_msg, "")
        return (ST_DISCONNECTED, "", "")
    except Exception:
        return (ST_DISCONNECTED, "", "")


def _get_session_extra(session_path: str):
    """Zwraca (auth_url, is_error, sdk_msg) dla danej ścieżki sesji przez SDK.

    auth_url – URL OAuth gdy sesja czeka na autoryzację webową.
    is_error  – True gdy sesja jest w stanie błędu (np. CONN_AUTH_FAILED).
    sdk_msg   – komunikat z SDK (fallback gdy sessions-list nie zdąży).
    """
    try:
        bus     = dbus.SystemBus()
        sessmgr = openvpn3.SessionManager(bus)
        session = sessmgr.Retrieve(session_path)
        status  = session.GetStatus()
        minor   = status["minor"]
        sdk_msg = str(status["message"])
        if minor == OV3Minor.SESS_AUTH_URL:
            return (sdk_msg, False, "")
        if minor in _OV3_ERROR_MINORS:
            return ("", True, sdk_msg)
    except Exception:
        pass
    return ("", False, "")


def run_vpn(args: list[str]):
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ── DBus Menu ──────────────────────────────────────────────────────────────────

class DbusMenu(dbus.service.Object):
    PATH = "/VpnMenu"

    # Stałe ID pozycji menu (stabilne między aktualizacjami layoutu)
    _ID_TOGGLE   = 1
    _ID_KILL     = 2
    _ID_OPEN_URL = 3
    _ID_SEP      = 9
    _ID_QUIT     = 10

    def __init__(self, bus, on_toggle, on_kill, on_open_url, on_quit):
        super().__init__(bus, self.PATH)
        self._on_toggle   = on_toggle
        self._on_kill     = on_kill
        self._on_open_url = on_open_url
        self._on_quit     = on_quit
        self._status      = ST_DISCONNECTED
        self._status_msg  = ""
        self._auth_url    = ""
        self._revision    = 0

    def set_state(self, status: str, msg: str = "", auth_url: str = ""):
        self._status     = status
        self._status_msg = msg
        self._auth_url   = auth_url
        self._revision += 1
        self.LayoutUpdated(dbus.UInt32(self._revision), dbus.Int32(0))

    def _item(self, item_id: int, props: dict):
        return dbus.Struct(
            (dbus.Int32(item_id), dbus.Dictionary(props, signature="sv"), dbus.Array([], signature="v")),
            signature=None,
        )

    @dbus.service.method(MENU_IFACE, in_signature="iias", out_signature="u(ia{sv}av)")
    def GetLayout(self, parentId, recursionDepth, propertyNames):
        items = []
        if self._status == ST_CONNECTED:
            items.append(self._item(self._ID_TOGGLE, {"label": "Rozłącz VPN",       "enabled": dbus.Boolean(True)}))
        elif self._status == ST_CONNECTING:
            if self._auth_url:
                items.append(self._item(self._ID_OPEN_URL, {"label": "🔐 Otwórz autoryzację…", "enabled": dbus.Boolean(True)}))
            else:
                items.append(self._item(5, {"label": "Trwa łączenie…",              "enabled": dbus.Boolean(False)}))
            if self._status_msg:
                items.append(self._item(6, {"label": self._status_msg,              "enabled": dbus.Boolean(False)}))
            items.append(self._item(self._ID_KILL,   {"label": "Zrestartuj sesję",  "enabled": dbus.Boolean(True)}))
        elif self._status == ST_ERROR:
            items.append(self._item(7, {"label": "❌ Błąd połączenia",              "enabled": dbus.Boolean(False)}))
            items.append(self._item(self._ID_KILL,   {"label": "Zrestartuj sesję",  "enabled": dbus.Boolean(True)}))
        else:
            items.append(self._item(self._ID_TOGGLE, {"label": "Połącz VPN",        "enabled": dbus.Boolean(True)}))
        items.append(self._item(self._ID_SEP,  {"type": "separator"}))
        items.append(self._item(self._ID_QUIT, {"label": "Wyjdź",              "enabled": dbus.Boolean(True)}))
        root = dbus.Struct(
            (dbus.Int32(0), dbus.Dictionary({}, signature="sv"), dbus.Array(items, signature="(ia{sv}av)")),
            signature=None,
        )
        return (dbus.UInt32(self._revision), root)

    @dbus.service.method(MENU_IFACE, in_signature="isvu", out_signature="")
    def Event(self, itemId, eventId, data, timestamp):
        if eventId != "clicked":
            return
        if itemId == self._ID_TOGGLE:
            self._on_toggle()
        elif itemId == self._ID_KILL:
            self._on_kill()
        elif itemId == self._ID_OPEN_URL:
            self._on_open_url()
        elif itemId == self._ID_QUIT:
            self._on_quit()

    @dbus.service.method(MENU_IFACE, in_signature="", out_signature="u")
    def GetRevision(self):
        return dbus.UInt32(self._revision)

    @dbus.service.signal(MENU_IFACE, signature="ui")
    def LayoutUpdated(self, revision, parent):
        pass

    @dbus.service.signal(MENU_IFACE, signature="a(ia{sv})a(ia{sv})")
    def ItemsPropertiesUpdated(self, updatedProps, removedProps):
        pass


# ── StatusNotifierItem ─────────────────────────────────────────────────────────

class StatusNotifierItem(dbus.service.Object):
    PATH = "/StatusNotifierItem"

    def __init__(self, bus, menu: DbusMenu):
        super().__init__(bus, self.PATH)
        self._menu       = menu
        self._status     = ST_DISCONNECTED
        self._px_on      = png_to_sni_pixmap(ICON_ON)
        self._px_off     = png_to_sni_pixmap(ICON_OFF)
        self._px_connect = png_to_sni_pixmap(ICON_OFF, tint_rgb=(255, 165, 0))
        self._px_error   = png_to_sni_pixmap(ICON_OFF, tint_rgb=(220, 50,  50))

    def _px(self):
        if self._status == ST_CONNECTED:
            return self._px_on
        if self._status == ST_CONNECTING:
            return self._px_connect
        if self._status == ST_ERROR:
            return self._px_error
        return self._px_off

    def set_state(self, status: str, msg: str = "", auth_url: str = ""):
        self._status = status
        self._menu.set_state(status, msg, auth_url)
        self.NewIcon()
        self.NewToolTip()

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ss", out_signature="v")
    def Get(self, iface, prop):
        return self.GetAll(iface).get(prop, dbus.String(""))

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        if self._status == ST_CONNECTED:
            sni_status  = "Active"
            tooltip     = "VPN: Połączony ✓"
            icon_pixmap = self._px_on
            attn_pixmap = self._px_on
        elif self._status == ST_CONNECTING:
            sni_status  = "NeedsAttention"   # tray mruga między icon a attn_icon
            tooltip     = "VPN: Łączenie…"
            icon_pixmap = self._px_off        # szary (bazowy)
            attn_pixmap = self._px_connect    # pomarańczowy (mruga)
        elif self._status == ST_ERROR:
            sni_status  = "NeedsAttention"
            tooltip     = f"VPN: Błąd – {self._menu._status_msg}" if self._menu._status_msg else "VPN: Błąd połączenia"
            icon_pixmap = self._px_off        # szary (bazowy)
            attn_pixmap = self._px_error      # czerwony (mruga)
        else:
            sni_status  = "Passive"
            tooltip     = "VPN: Rozłączony"
            icon_pixmap = self._px_off
            attn_pixmap = self._px_off
        return dbus.Dictionary({
            "Id":                  dbus.String("vpn-manager"),
            "Title":               dbus.String("VPN"),
            "Status":              dbus.String(sni_status),
            "Category":            dbus.String("ApplicationStatus"),
            "IconName":            dbus.String(""),
            "IconPixmap":          dbus.Array([icon_pixmap], signature="(iiay)"),
            "OverlayIconName":     dbus.String(""),
            "AttentionIconName":   dbus.String(""),
            "AttentionIconPixmap": dbus.Array([attn_pixmap], signature="(iiay)"),
            "ToolTip":             dbus.Struct(
                                       ("", dbus.Array([], signature="(iiay)"), tooltip, ""),
                                       signature=None,
                                   ),
            "Menu":                dbus.ObjectPath(DbusMenu.PATH),
            "ItemIsMenu":          dbus.Boolean(False),
        }, signature="sv")

    @dbus.service.signal(SNI_IFACE)
    def NewIcon(self): pass

    @dbus.service.signal(SNI_IFACE)
    def NewToolTip(self): pass

    @dbus.service.method(SNI_IFACE, in_signature="ii")
    def Activate(self, x, y):
        pass  # klik lewym — nie rób nic, menu obsługuje akcje

    @dbus.service.method(SNI_IFACE, in_signature="ii")
    def SecondaryActivate(self, x, y):
        pass

    @dbus.service.method(SNI_IFACE, in_signature="is")
    def Scroll(self, delta, orientation):
        pass


# ── główna pętla ───────────────────────────────────────────────────────────────

class VpnManager:
    def __init__(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self._bus  = dbus.SessionBus()
        self._loop = GLib.MainLoop()

        self._busy        = False
        self._last_status = ST_DISCONNECTED
        self._menu = DbusMenu(
            self._bus,
            on_toggle=self._toggle,
            on_kill=self._kill,
            on_open_url=self._open_url,
            on_quit=self._loop.quit,
        )
        self._sni = StatusNotifierItem(self._bus, self._menu)

        service_name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self._bus.request_name(service_name, dbus.bus.NAME_FLAG_DO_NOT_QUEUE)

        try:
            watcher = self._bus.get_object(SNW_IFACE, SNW_PATH)
            watcher.RegisterStatusNotifierItem(
                service_name, dbus_interface=SNW_IFACE,
            )
        except Exception as e:
            print(f"Watcher: {e}", file=sys.stderr)

        GLib.timeout_add_seconds(1, self._first_poll)
        GLib.timeout_add_seconds(POLL_INTERVAL, self._periodic_poll)

    def _first_poll(self):
        self._do_poll()
        return False

    def _periodic_poll(self):
        self._do_poll()
        return True

    def _do_poll(self):
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        status, msg, auth_url = get_vpn_status()
        GLib.idle_add(self._apply_state, status, msg, auth_url)

    def _apply_state(self, status, msg, auth_url):
        prev              = self._last_status
        self._last_status = status
        self._sni.set_state(status, msg, auth_url)
        if status == ST_ERROR and prev != ST_ERROR:
            self._notify(
                "VPN: Błąd połączenia",
                msg if msg else "Nie udało się nawiązać połączenia VPN.",
                "dialog-error",
            )

    def _notify(self, title: str, body: str, icon: str = "network-vpn"):
        try:
            obj = self._bus.get_object(
                "org.freedesktop.Notifications", "/org/freedesktop/Notifications"
            )
            dbus.Interface(obj, "org.freedesktop.Notifications").Notify(
                "VPN Manager", dbus.UInt32(0), icon, title, body,
                dbus.Array([], signature="s"),
                dbus.Dictionary({}, signature="sv"),
                dbus.Int32(7000),
            )
        except Exception as e:
            print(f"Notify: {e}", file=sys.stderr)

    def _toggle(self):
        if self._busy or self._sni._status == ST_CONNECTING:
            return
        self._busy = True
        if self._sni._status == ST_CONNECTED:
            run_vpn(["openvpn3", "session-manage", "--config", CONFIG_NAME, "--disconnect"])
        else:
            run_vpn(["openvpn3", "session-start", "--config", CONFIG_NAME])
        GLib.timeout_add_seconds(3, self._release_and_poll)

    def _open_url(self):
        url = self._menu._auth_url
        if url:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _kill(self):
        """Restartuje zawieszoną sesję: rozłącza i po chwili łączy ponownie."""
        if self._busy:
            return
        self._busy = True
        run_vpn(["openvpn3", "session-manage", "--config", CONFIG_NAME, "--disconnect"])
        GLib.timeout_add_seconds(2, self._restart_connect)

    def _restart_connect(self):
        run_vpn(["openvpn3", "session-start", "--config", CONFIG_NAME])
        GLib.timeout_add_seconds(3, self._release_and_poll)
        return False

    def _release_and_poll(self):
        self._busy = False
        self._do_poll()
        return False

    def run(self):
        self._loop.run()


def main():
    VpnManager().run()


if __name__ == "__main__":
    main()
