# GB3 co-op server

The Recompiler's co-op runs through a small shadNet server. You can run it three ways:

| Where | How | Who can join |
|---|---|---|
| A Deck or PC at home | Recompiler → **Network** → *Local: host on this device* | Everyone on the same Wi-Fi/LAN (they pick *Local: join*) |
| A free cloud VM | `install-server.sh` below | Anyone on the internet (they pick *Online server* and type its address once) |
| Your own always-on Linux box | same script | same |

No ad hoc Wi-Fi is needed: for two Decks away from a router, turn on a hotspot on one of them
(SteamOS Desktop Mode → network icon → Hotspot, or a phone hotspot), connect the other to it, and use
*Local*.

## Free online server (Oracle Cloud "Always Free", step by step)

Any x86-64 Linux VM works (Google Cloud e2-micro free tier, a home server, a cheap VPS). Oracle's
free tier is the most generous:

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
5. It prints `address <public IP>:31313`. Every player: Recompiler → **Network** → *Online server* →
   that address (+ the key if you set one) → a user name → **Save**. Done; Play starts online.

Update: download the new release and run the same `install-server.sh` again (accounts stay).
Remove: `sudo bash server/install-server.sh --uninstall`.
Logs: `journalctl -u gb3-server` and `/var/lib/gb3-server/shadnet.log`.

## Notes

- Traffic is not encrypted (shadNet's plain TCP login, as on the LAN). Each player's password is
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
