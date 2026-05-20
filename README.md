# OpenVPN3 Tray Manager

Minimalna aplikacja w zasobniku systemowym do zarządzania połączeniem OpenVPN3 na Linuksie.

Wyświetla ikonę w trayu, pozwala połączyć/rozłączyć VPN jednym kliknięciem, obsługuje autoryzację OAuth (otwiera przeglądarkę) i powiadamia o błędach połączenia.

![Zrzut ekranu ikony w zasobniku](https://via.placeholder.com/400x80?text=VPN+tray+icon)

## Wymagania

- Linux z pulpitem obsługującym **StatusNotifierItem** (KDE Plasma, GNOME z rozszerzeniem [AppIndicator](https://extensions.gnome.org/extension/615/appindicator-support/), XFCE, itp.)
- [`openvpn3`](https://openvpn.net/cloud-docs/owner/connectors/connector-user-guides/openvpn-3-client-for-linux.html) – klient OpenVPN3 w wersji 3.x
- Skonfigurowany profil VPN (`openvpn3 configs-list`)
- Python 3.9+

### Zależności Pythona

| Pakiet | apt | pip |
|--------|-----|-----|
| `dbus-python` | `python3-dbus` | `dbus-python` |
| `PyGObject` | `python3-gi` | `PyGObject` |
| `Pillow` *(zalecane)* | `python3-pil` | `Pillow` |

> Bez Pillow ikony ładowane są przez PyQt6 (fallback). Pillow jest szybsze i nie wymaga Qt.

```bash
sudo apt install python3-dbus python3-gi python3-pil
```

## Instalacja

```bash
git clone https://github.com/magik092/openvpn3-tray-manager.git ~/vpn-manager
cd ~/vpn-manager
bash install.sh
```

Skrypt zapyta o nazwę Twojego profilu VPN i skonfiguruje autostart. To jednorazowa akcja – przy każdym kolejnym logowaniu aplikacja uruchomi się automatycznie.

Aby sprawdzić nazwę swojego profilu:

```bash
openvpn3 configs-list
```

## Uruchamianie ręczne

```bash
python3 ~/vpn-manager/vpn-tray.py
```

## Zmiana profilu VPN

Wystarczy ponownie uruchomić instalator:

```bash
bash ~/vpn-manager/install.sh
```

## Funkcje

- 🟢 **Połączony** – zielona ikona, tooltip „VPN: Połączony ✓"
- 🟠 **Łączenie** – pomarańczowa migająca ikona
- 🔴 **Błąd** – czerwona migająca ikona + powiadomienie systemowe
- 🔐 **OAuth** – przycisk w menu otwierający autoryzację w przeglądarce
- **Restart sesji** – przycisk do resetowania zawieszonego połączenia

## Struktura plików

```
vpn-manager/
├── vpn-tray.py        # główny skrypt
├── vpn-tray.desktop   # plik autostartu
├── install.sh         # instalator
├── icon_on.png        # ikona – połączony
└── icon_off.png       # ikona – rozłączony
```

Konfiguracja (nazwa profilu) zapisywana jest w `~/.config/vpn-manager/config`.

## Licencja

MIT
