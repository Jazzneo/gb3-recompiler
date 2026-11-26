#!/usr/bin/env bash
# Set up Tailscale for GB3 co-op over the internet (opened in a terminal by the Recompiler's
# Network window). Tailscale is a free virtual LAN: every device signed in to your Tailscale
# account (or shared with you) can reach the others as if on the same Wi-Fi.
#
# Steam Deck (SteamOS): installs tailscale-dev/deck-tailscale, Tailscale's own Deck installer: a
# system extension that survives SteamOS updates and leaves the read-only OS untouched. It needs
# your "deck" password (sudo): set one first with `passwd` if you never did.
# Other Linux: the distribution's package (Bazzite has Tailscale built in).
# You create / sign in to the Tailscale account yourself in the browser link it prints.
set -u
pause() { read -r -p "$1 [Enter = continue, Ctrl+C = stop] " _; }
say() { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }
ts() { command -v tailscale >/dev/null 2>&1 && echo tailscale || { [[ -x /opt/tailscale/tailscale ]] && echo /opt/tailscale/tailscale; }; }

say "GB3 co-op: Tailscale setup"
if [[ -n $(ts) ]] && $(ts) ip -4 >/dev/null 2>&1; then
    echo "Tailscale is already on: this device is $($(ts) ip -4 | head -1)."
    pause "Nothing to do. Close this window."
    exit 0
fi

steamos=0
grep -qi steamos /etc/os-release 2>/dev/null && steamos=1

if [[ -z $(ts) ]]; then
    if ((steamos)); then
        say "Step 1/2: install Tailscale (deck-tailscale, by Tailscale)"
        echo "This downloads https://github.com/tailscale-dev/deck-tailscale and runs its installer"
        echo "with sudo. It asks for your deck password (set one with 'passwd' if you have none)."
        pause "Install now?"
        set -e
        cd ~
        if [[ -d deck-tailscale/.git ]]; then git -C deck-tailscale pull --ff-only; else git clone https://github.com/tailscale-dev/deck-tailscale.git; fi
        cd ~/deck-tailscale
        sudo bash tailscale.sh
        # shellcheck disable=SC1091
        [[ -f /etc/profile.d/tailscale.sh ]] && source /etc/profile.d/tailscale.sh
        set +e
    else
        say "Tailscale is not installed"
        if command -v rpm-ostree >/dev/null 2>&1; then
            echo "Bazzite / Fedora Atomic:   sudo rpm-ostree install tailscale   then reboot"
        elif command -v dnf >/dev/null 2>&1; then
            echo "Fedora:   sudo dnf install tailscale"
        elif command -v apt-get >/dev/null 2>&1; then
            echo "Debian/Ubuntu:   curl -fsSL https://tailscale.com/install.sh | sh"
        elif command -v pacman >/dev/null 2>&1; then
            echo "Arch:   sudo pacman -S tailscale"
        else
            echo "See https://tailscale.com/download/linux"
        fi
        echo "Then:   sudo systemctl enable --now tailscaled   and run this setup again."
        pause "Close this window."
        exit 1
    fi
fi

say "Step 2/2: sign in"
sudo systemctl enable --now tailscaled 2>/dev/null || true
echo "A link appears below: open it (or scan the QR code with your phone), sign in or create a free"
echo "Tailscale account, and approve this device. Your friend signs in to the same account, or you"
echo "share your device with them from the Tailscale admin page (Share)."
pause "Sign in now?"
sudo "$(ts)" up --qr --operator="$USER"
if $(ts) ip -4 >/dev/null 2>&1; then
    say "Done: this device is $($(ts) ip -4 | head -1) on Tailscale"
    echo "Back in the Recompiler: Network > host: 'Friends join over: Tailscale', or join: Search."
else
    say "Tailscale did not come up; run this again or see https://tailscale.com/kb"
fi
pause "Close this window."
