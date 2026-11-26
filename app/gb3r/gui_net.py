"""The Network window: user name + Offline / Local host / Local join / Online server.

Everything is saved to ~/.config/gb3-recompiler/network.json; play.sh reads it at every launch
(psport/gb3net.py launch-env), so a Steam shortcut plays in the chosen mode without any options.
"""
import os
import subprocess
import threading

from . import core, net


def summary():
    c = net.load()
    if c['mode'] == 'offline':
        return 'Network: Offline'
    who = c['name'] or '(no user name yet)'
    where = {'lan-host': 'hosting on this device', 'lan-join': 'joining ' + (
        'the first host found' if (c.get('lan_host') or 'auto') == 'auto' else c['lan_host']),
        'online': c.get('server') or '(no server address)'}[c['mode']]
    return 'Network: %s, %s' % (who, where)


def open_window(root, install_dir, log, on_saved=None, styles=None):
    import tkinter as tk
    from tkinter import messagebox, ttk

    PANEL, FG, DIM = styles or ('#1a212b', '#e6edf3', '#8b98a8')
    cfg = net.load()
    w = tk.Toplevel(root)
    w.title('Network / co-op')
    w.configure(background=PANEL)
    w.transient(root)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    ww, wh = min(900, sw - 40), min(700, sh - 60)
    w.geometry('%dx%d+%d+%d' % (ww, wh, max(0, (sw - ww) // 2), max(0, (sh - wh) // 3)))
    f = ttk.Frame(w, style='Card.TFrame', padding=16)
    f.pack(fill='both', expand=True)
    f.columnconfigure(1, weight=1)

    ttk.Label(f, text='Your user name', style='Head.TLabel').grid(row=0, column=0, columnspan=3, sticky='w')
    name_var = tk.StringVar(value=cfg.get('name', ''))
    ttk.Entry(f, textvariable=name_var, width=24).grid(row=1, column=0, sticky='w', pady=(4, 0))
    name_hint = tk.StringVar()
    ttk.Label(f, textvariable=name_hint, style='Dim.TLabel', wraplength=ww - 300).grid(row=1, column=1, columnspan=2, sticky='w', padx=(10, 0))

    def check_name(*_):
        n = name_var.get().strip()
        name_hint.set('Shown to the other players as your Online ID.' if net.valid_name(n) else
                      '3-16 letters, digits, - or _ (shown to the others as your Online ID).')
    name_var.trace_add('write', check_name)
    check_name()

    ttk.Label(f, text='How to play', style='Head.TLabel').grid(row=2, column=0, columnspan=3, sticky='w', pady=(14, 0))
    mode_var = tk.StringVar(value=cfg['mode'])
    for i, m in enumerate(net.MODES):
        ttk.Radiobutton(f, text=net.MODE_NAMES[m], value=m, variable=mode_var, style='Card.TRadiobutton').grid(
            row=3 + i, column=0, columnspan=3, sticky='w', pady=(2, 0))

    box = ttk.Frame(f, style='Card.TFrame')
    box.grid(row=7, column=0, columnspan=3, sticky='nsew', pady=(12, 0))
    box.columnconfigure(1, weight=1)
    f.rowconfigure(7, weight=1)

    # --- lan-host
    host_f = ttk.Frame(box, style='Card.TFrame')
    host_f.columnconfigure(0, weight=1)
    host_state = tk.StringVar()
    ttk.Label(host_f, textvariable=host_state, style='Card.TLabel', wraplength=ww - 60, justify='left').grid(row=0, column=0, columnspan=3, sticky='w')
    ttk.Label(host_f, style='Dim.TLabel', wraplength=ww - 60, justify='left', text=(
        'The co-op server starts by itself when you press Play and stops when your game closes. '
        'Start it here to keep it on for the others without playing. The other players pick '
        '"Local: join" on the same Wi-Fi/LAN (away from a router: turn on a hotspot on one Deck and '
        'connect the other to it).')).grid(row=1, column=0, columnspan=3, sticky='w', pady=(4, 6))
    hb = ttk.Frame(host_f, style='Card.TFrame')
    hb.grid(row=2, column=0, columnspan=3, sticky='w')
    start_b = ttk.Button(hb, text='Start server')
    stop_b = ttk.Button(hb, text='Stop server')
    start_b.pack(side='left')
    stop_b.pack(side='left', padx=(6, 0))

    def host_refresh():
        st = net.server_running()
        ip = net.lan_ip()
        host_state.set('Server: %s.   This device on the network: %s' % (
            'running (port %d)' % st['port'] if st else 'off', ip))
        start_b.state(['disabled'] if st else ['!disabled'])
        stop_b.state(['!disabled'] if st else ['disabled'])

    # --- lan-join
    join_f = ttk.Frame(box, style='Card.TFrame')
    join_f.columnconfigure(0, weight=1)
    ttk.Label(join_f, text='Hosts on this network', style='Card.TLabel').grid(row=0, column=0, sticky='w')
    hosts_lb = tk.Listbox(join_f, height=5, background='#0d1218', foreground=FG, selectbackground='#38455a',
                          relief='flat', exportselection=False)
    hosts_lb.grid(row=1, column=0, columnspan=2, sticky='nsew', pady=(4, 0))
    search_b = ttk.Button(join_f, text='Search')
    search_b.grid(row=1, column=2, sticky='n', padx=(6, 0), pady=(4, 0))
    join_auto = tk.BooleanVar(value=(cfg.get('lan_host') or 'auto') == 'auto')
    ttk.Checkbutton(join_f, text='Join the first host found automatically (no typing)', variable=join_auto,
                    style='TCheckbutton').grid(row=2, column=0, columnspan=3, sticky='w', pady=(6, 0))
    ttk.Label(join_f, text='or this address', style='Dim.TLabel').grid(row=3, column=0, sticky='w', pady=(6, 0))
    manual_var = tk.StringVar(value='' if join_auto.get() else cfg.get('lan_host', ''))
    ttk.Entry(join_f, textvariable=manual_var, width=28).grid(row=4, column=0, sticky='w')
    found = []

    def pick_host(_=None):
        sel = hosts_lb.curselection()
        if sel:
            h = found[sel[0]]
            manual_var.set(h['ip'] if h['port'] == net.PORT else '%s:%d' % (h['ip'], h['port']))
            join_auto.set(False)
    hosts_lb.bind('<<ListboxSelect>>', pick_host)

    def search():
        search_b.state(['disabled'])
        hosts_lb.delete(0, 'end')
        hosts_lb.insert('end', 'searching...')

        def work():
            hs = net.discover(2.0)
            w.after(0, lambda: show(hs))
        threading.Thread(target=work, daemon=True).start()

    def show(hs):
        found[:] = hs
        hosts_lb.delete(0, 'end')
        for h in hs:
            hosts_lb.insert('end', '%s   (%s)' % (h['name'] or '?', h['ip']))
        if not hs:
            hosts_lb.insert('end', 'none found: is "Local: host on this device" on there, on the same network?')
        search_b.state(['!disabled'])
    search_b.configure(command=search)

    # --- online
    on_f = ttk.Frame(box, style='Card.TFrame')
    on_f.columnconfigure(1, weight=1)
    ttk.Label(on_f, text='Server address', style='Card.TLabel').grid(row=0, column=0, sticky='w')
    server_var = tk.StringVar(value=cfg.get('server', ''))
    ttk.Entry(on_f, textvariable=server_var, width=36).grid(row=0, column=1, sticky='w', padx=(8, 0))
    ttk.Label(on_f, text='Server key (if it has one)', style='Card.TLabel').grid(row=1, column=0, sticky='w', pady=(6, 0))
    key_var = tk.StringVar(value=cfg.get('key', ''))
    ttk.Entry(on_f, textvariable=key_var, width=24, show='•').grid(row=1, column=1, sticky='w', padx=(8, 0), pady=(6, 0))
    ttk.Label(on_f, style='Dim.TLabel', wraplength=ww - 60, justify='left', text=(
        'example: 203.0.113.7  or  gb3.example.net:31313. A free server takes about 15 minutes on '
        'Oracle Cloud\'s Always Free tier: one command, see the guide.')).grid(row=2, column=0, columnspan=2, sticky='w', pady=(6, 4))

    def open_guide():
        for p in (os.path.join(core.ROOT, 'server', 'README.md'),
                  os.path.join(install_dir(), 'server-guide.md')):
            if os.path.exists(p):
                subprocess.Popen(['xdg-open', p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
        messagebox.showinfo('Network', 'The guide is server/README.md in the release.', parent=w)
    ttk.Button(on_f, text='Free server guide…', command=open_guide).grid(row=3, column=0, sticky='w')

    panels = {'lan-host': host_f, 'lan-join': join_f, 'online': on_f}

    def mode_changed(*_):
        for m, p in panels.items():
            if m == mode_var.get():
                p.grid(row=0, column=0, columnspan=3, sticky='nsew')
            else:
                p.grid_forget()
        if mode_var.get() == 'lan-host':
            host_refresh()
        elif mode_var.get() == 'lan-join' and not found:
            search()
    mode_var.trace_add('write', mode_changed)

    result = tk.StringVar()
    ttk.Label(f, textvariable=result, style='Dim.TLabel', wraplength=ww - 60, justify='left').grid(
        row=8, column=0, columnspan=3, sticky='w', pady=(8, 0))
    bar = ttk.Frame(f, style='Card.TFrame')
    bar.grid(row=9, column=0, columnspan=3, sticky='e', pady=(8, 0))

    def collect():
        c = net.load()
        c['mode'] = mode_var.get()
        c['name'] = name_var.get().strip()
        c['server'] = server_var.get().strip()
        c['key'] = key_var.get().strip()
        c['lan_host'] = 'auto' if join_auto.get() or not manual_var.get().strip() else manual_var.get().strip()
        return c

    def validate(c):
        if c['mode'] == 'offline':
            return None
        if not net.valid_name(c['name']):
            return 'Pick a user name first (3-16 letters, digits, - or _).'
        if c['mode'] == 'online' and not c['server']:
            return 'Type the online server\'s address.'
        if c['mode'] == 'lan-host' and not os.path.exists(os.path.join(net.shadnet_dir(install_dir()), 'shadnet')):
            return 'The co-op server is not installed yet: press Install / Apply options once (needs this version).'
        return None

    def save():
        c = collect()
        err = validate(c)
        if err:
            messagebox.showinfo('Network', err, parent=w)
            return False
        net.save(c)
        log('Network saved: %s' % summary()[9:])
        if on_saved:
            on_saved()
        return True

    def test():
        if not save():
            return
        c = net.load()
        if c['mode'] == 'offline':
            result.set('Offline: nothing to test.')
            return
        result.set('Testing...')
        test_b.state(['disabled'])

        def work():
            try:
                t = net.target(c, install_dir(), log=log)
                net.ensure_account(t[0], t[1], c['name'], c.get('key', ''), t[2], log=log)
                msg = 'OK: %s is ready on %s (%s:%d). Press Play.' % (c['name'], t[3], t[0], t[1])
            except Exception as e:  # noqa: BLE001 - shown to the player
                msg = 'Problem: %s' % e
            log(msg)
            w.after(0, lambda: (result.set(msg), test_b.state(['!disabled']),
                                host_refresh() if c['mode'] == 'lan-host' else None))
        threading.Thread(target=work, daemon=True).start()

    def start_server():
        if not save():
            return
        try:
            net.server_start(install_dir(), net.load())
            log('Co-op server started')
        except Exception as e:  # noqa: BLE001
            messagebox.showerror('Network', str(e), parent=w)
        host_refresh()

    def stop_server():
        net.server_stop()
        log('Co-op server stopped')
        host_refresh()
    start_b.configure(command=start_server)
    stop_b.configure(command=stop_server)

    test_b = ttk.Button(bar, text='Test connection', command=test)
    test_b.pack(side='left')
    ttk.Button(bar, text='Save', style='Primary.TButton', command=lambda: save() and w.destroy()).pack(side='left', padx=(8, 0))
    ttk.Button(bar, text='Cancel', command=w.destroy).pack(side='left', padx=(8, 0))
    mode_changed()
    w.grab_set()
    return w
