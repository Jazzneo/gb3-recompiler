# GB3 co-op over the internet

The Recompiler's co-op runs through a small server that one player's Deck or PC hosts
(**Network → Host on this device**). Friends on the same Wi-Fi just pick **Join a host** and **Search**.
Friends somewhere else join the same way over **Tailscale**, a free virtual LAN. No ports to open, no
server to rent.

| Where your friend is | Host picks | Friend picks |
|---|---|---|
| Same Wi-Fi / LAN | Friends join over: the same Wi-Fi / LAN | Join a host → Search |
| No router (two Decks) | turn on a hotspot on the host Deck, Wi-Fi option | connect to that hotspot, Join → Search |
| Anywhere (internet) | Friends join over: **Tailscale** | Join a host → Search (finds the host on Tailscale) |

## Tailscale, step by step

Tailscale is free for personal use (up to 100 devices). You make the account yourself on its website.

1. **Each player, once:** Recompiler → Network / co-op… → **Set up Tailscale…**. A terminal opens and
   walks through it:
   - **Steam Deck:** it installs Tailscale with Tailscale's own Deck installer
     (github.com/tailscale-dev/deck-tailscale, a system extension that survives SteamOS updates). It
     asks for your deck password. If you never set one: open Konsole and type `passwd` first.
   - **Bazzite:** Tailscale is built in; it only signs in. Other Linux: it tells you the one install command.
   - Then it prints a **login link** (and a QR code): open it, sign in or make a free account, approve
     the device.
2. **Connect the two players:** both sign in to the **same** Tailscale account, or the host shares their
   device with the friend: login.tailscale.com → Machines → (host device) → **Share…** → send the invite.
3. **Host:** Network → Host on this device → Friends join over: **Tailscale** → user name → Save → Play.
   The window shows the host's Tailscale address (100.x.y.z) with a Copy button.
4. **Friend:** Network → Join a host → **Search**: the host shows up as "(100.x.y.z, Tailscale)". Pick
   it, or keep "Join the first host found automatically". User name → Save → Play.

**Test connection** in the Network window checks everything without starting the game.

Tailscale on the Deck keeps running in Game Mode after setup. To turn it off: Desktop Mode, Konsole,
`sudo tailscale down` (back on: `sudo tailscale up`).

## Advanced: your own always-on server (VPS)

Only needed for a public server that is on when no player hosts. Any x86-64 Linux machine works
(a cloud VM, a home server).

### Example: Oracle Cloud "Always Free"


1. Make an account at cloud.oracle.com (a card is asked for identity; Always Free resources are not
   charged).
2. **Compute → Instances → Create instance.** Image: *Canonical Ubuntu 24.04*. Shape: **VM.Standard.E2.1.Micro
   (AMD, Always Free)**. Do not pick an Ampere (ARM) shape: the server is built for x86-64. Add your
   SSH key, create.
3. **Open the ports in Oracle's firewall:** instance → *Subnet* → *Default Security List* → *Add Ingress
   Rules* (source `0.0.0.0/0`):
   - TCP, destination port `31313`
   - TCP, destination port `31315`
   - UDP, destination port `31314`
   - UDP, destination port `3478`
4. SSH in (`ssh ubuntu@<public IP>`) and run:
   ```bash
   sudo apt-get update && sudo apt-get install -y python3 curl xz-utils
   curl -LO https://github.com/Jazzneo/gb3-recompiler/releases/download/v1.2.0/GB3-Recompiler-v1.2.0-Linux-x86_64.tar.xz
   tar xf GB3-Recompiler-v1.2.0-Linux-x86_64.tar.xz
   sudo bash GB3-Recompiler-v1.2.0/server/install-server.sh
   ```
   (For a newer release, change the version in both names.) Add `--key SOMETHING` to let only
   your friends create accounts.
5. It prints `address <public IP>:31313`. Every player: Recompiler → **Network** → *Online server (advanced)* →
   that address (+ the key if you set one) → a user name → **Save**. Done; Play starts online.

Update: download the new release and run the same `install-server.sh` again (accounts stay).
Remove: `sudo bash server/install-server.sh --uninstall`.
Logs: `journalctl -u gb3-server` and `/var/lib/gb3-server/shadnet.log`.

## Notes

- Over Tailscale everything is encrypted (WireGuard). On a plain LAN or a VPS it is not (shadNet's
  plain TCP login). Each player's password is
  random and only used for this server; nothing else is at stake. Use `--key` on a public server.
- Game traffic goes player to player. When routers block that, the server's relay (UDP 3478)
  carries it; that needs the VM's bandwidth, which the free tier has plenty of for 4 players.
- The user name you pick in the Recompiler is your Online ID in co-op. It is created on the server
  the first time you play; the name is per server (the same name can be taken on another server).

## Source

shadNet server 0.1.9 (GPL-2.0-or-later, https://github.com/shadps4-emu/shadNet, commit a53dad5)
plus `shadnet-gb3.diff` (psport signaling header; room messages to oneself, which GB3's host needs).
Libraries: unmodified Fedora 45 packages (`runtime/shadnet/share/PACKAGES.txt`).
`gb3net.py` (start/stop, LAN discovery, relay, accounts) is part of the Recompiler (its licence).
