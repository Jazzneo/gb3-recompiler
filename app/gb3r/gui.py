"""One window: pick PKG -> Install -> Play. Tk, sized for a Steam Deck screen (1280x800)."""
import os
import queue
import subprocess
import threading

from . import core, gui_net

BG = '#11161d'
PANEL = '#1a212b'
FG = '#e6edf3'
DIM = '#8b98a8'
ACCENT = '#e0a526'
GOOD = '#5fbf6a'
BAD = '#e5534b'


def main():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    cfg = core.load_config()
    root = tk.Tk()
    root.title(core.APP_NAME)
    root.configure(background=BG)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    w, h = min(1180, sw - 40), min(760, sh - 60)
    root.geometry('%dx%d+%d+%d' % (w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 3)))
    root.minsize(860, 600)

    style = ttk.Style(root)
    try:
        style.theme_use('clam')
    except tk.TclError:
        pass
    base_font = ('DejaVu Sans', 11)
    style.configure('.', background=BG, foreground=FG, font=base_font)
    style.configure('TFrame', background=BG)
    style.configure('Card.TFrame', background=PANEL)
    style.configure('TLabel', background=BG, foreground=FG)
    style.configure('Card.TLabel', background=PANEL, foreground=FG)
    style.configure('Dim.TLabel', background=PANEL, foreground=DIM, font=('DejaVu Sans', 10))
    style.configure('Head.TLabel', background=PANEL, foreground=ACCENT, font=('DejaVu Sans', 12, 'bold'))
    style.configure('Title.TLabel', background=BG, foreground=FG, font=('DejaVu Sans', 17, 'bold'))
    style.configure('Sub.TLabel', background=BG, foreground=DIM)
    style.configure('TButton', padding=(12, 6), background='#2b3542', foreground=FG)
    style.map('TButton', background=[('active', '#38455a'), ('disabled', '#222a33')],
              foreground=[('disabled', '#5c6672')])
    style.configure('Primary.TButton', background=ACCENT, foreground='#111111', font=('DejaVu Sans', 12, 'bold'))
    style.map('Primary.TButton', background=[('active', '#f0b93a'), ('disabled', '#5a4a22')])
    style.configure('TCheckbutton', background=PANEL, foreground=FG)
    style.map('TCheckbutton', background=[('active', PANEL)])
    style.configure('Card.TRadiobutton', background=PANEL, foreground=FG)
    style.map('Card.TRadiobutton', background=[('active', PANEL)])
    style.configure('TEntry', fieldbackground='#0d1218', foreground=FG, insertcolor=FG)
    style.configure('TCombobox', fieldbackground='#0d1218', foreground=FG, background='#2b3542', arrowcolor=FG)
    style.map('TCombobox', fieldbackground=[('readonly', '#0d1218')], foreground=[('readonly', FG)],
              selectbackground=[('readonly', '#0d1218')], selectforeground=[('readonly', FG)])

    head = ttk.Frame(root, padding=(18, 12, 18, 6))
    head.pack(fill='x')
    ttk.Label(head, text='Recompiler  ·  GUNDAM BREAKER 3 BREAK EDITION', style='Title.TLabel').pack(anchor='w')
    ttk.Label(head, style='Sub.TLabel', wraplength=w - 60, justify='left',
              text='Turns your own PS4 PKG (CUSA07651) into a Linux / Steam Deck install through psport, '
                   'with the 720p, Xbox-button and shop-lighting fixes. No game data ships with this tool.'
              ).pack(anchor='w', pady=(2, 0))

    body = ttk.Frame(root, padding=(18, 4, 18, 8))
    body.pack(fill='both', expand=True)
    body.columnconfigure(0, weight=3, uniform='c')
    body.columnconfigure(1, weight=2, uniform='c')
    body.rowconfigure(1, weight=1)

    # --- card 1: files
    c1 = ttk.Frame(body, style='Card.TFrame', padding=12)
    c1.grid(row=0, column=0, sticky='nsew', padx=(0, 8), pady=(0, 8))
    c1.columnconfigure(0, weight=1)
    ttk.Label(c1, text='1  Your game PKG and where to install', style='Head.TLabel').grid(row=0, column=0, columnspan=3, sticky='w')
    pkg_var = tk.StringVar(value=cfg.get('pkg', ''))
    dir_var = tk.StringVar(value=cfg.get('install_dir', core.default_install_dir()))
    pkg_info = tk.StringVar(value='')

    ttk.Label(c1, text='PKG file (base game, not an update)', style='Dim.TLabel').grid(row=1, column=0, columnspan=3, sticky='w', pady=(8, 0))
    ttk.Entry(c1, textvariable=pkg_var).grid(row=2, column=0, sticky='ew')

    def browse_pkg():
        start = os.path.dirname(pkg_var.get()) if pkg_var.get() else os.path.expanduser('~')
        p = filedialog.askopenfilename(parent=root, title='Your GUNDAM BREAKER 3 PKG', initialdir=start,
                                       filetypes=[('PS4 PKG', '*.pkg *.PKG'), ('All files', '*')])
        if p:
            pkg_var.set(p)
            check_pkg()

    def find_pkg():
        busy_set(True, 'Searching for PKGs...')

        def work():
            found = core.find_pkgs()
            root.after(0, lambda: found_pkgs(found))
        threading.Thread(target=work, daemon=True).start()

    def found_pkgs(found):
        busy_set(False)
        if not found:
            pkg_info.set('No CUSA07651 PKG found in ~/Downloads, ~/Games, home or mounted drives.')
            return
        pkg_var.set(found[0])
        check_pkg()
        if len(found) > 1:
            log('Found %d PKGs: %s' % (len(found), '; '.join(found)))

    ttk.Button(c1, text='Browse…', command=browse_pkg).grid(row=2, column=1, padx=(6, 0))
    ttk.Button(c1, text='Find', command=find_pkg).grid(row=2, column=2, padx=(6, 0))
    ttk.Label(c1, textvariable=pkg_info, style='Dim.TLabel', wraplength=600).grid(row=3, column=0, columnspan=3, sticky='w')

    ttk.Label(c1, text='Install folder (needs ~14 GB free; a microSD is fine)', style='Dim.TLabel').grid(row=4, column=0, columnspan=3, sticky='w', pady=(8, 0))
    ttk.Entry(c1, textvariable=dir_var).grid(row=5, column=0, sticky='ew')

    def browse_dir():
        p = filedialog.askdirectory(parent=root, title='Install folder', initialdir=os.path.dirname(dir_var.get()) or '~')
        if p:
            if not os.path.basename(p).startswith('GB3-Recompiler') and not os.path.exists(os.path.join(p, 'gb3r.json')):
                p = os.path.join(p, 'GB3-Recompiler')
            dir_var.set(p)
            refresh()
    ttk.Button(c1, text='Browse…', command=browse_dir).grid(row=5, column=1, padx=(6, 0))

    def open_dir():
        d = dir_var.get()
        if os.path.isdir(d):
            subprocess.Popen(['xdg-open', d], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ttk.Button(c1, text='Open', command=open_dir).grid(row=5, column=2, padx=(6, 0))

    def check_pkg(*_):
        p = pkg_var.get().strip()
        if not p:
            pkg_info.set('')
            return
        if not os.path.isfile(p):
            pkg_info.set('File not found.')
            return
        ok, msg = core.check_pkg(p)
        pkg_info.set(('OK: ' if ok else 'Problem: ') + msg)

    # --- card 2: options
    c2 = ttk.Frame(body, style='Card.TFrame', padding=12)
    c2.grid(row=0, column=1, sticky='nsew', pady=(0, 8))
    ttk.Label(c2, text='2  Fixes and options', style='Head.TLabel').pack(anchor='w')
    inst0 = core.Install(dir_var.get())
    opts0 = inst0.state()['options']
    xbox_var = tk.BooleanVar(value=opts0['xbox'])
    r720_var = tk.BooleanVar(value=opts0['render720'])
    async_var = tk.BooleanVar(value=opts0['async'])
    fps_var = tk.StringVar(value=opts0['fps'])
    ttk.Checkbutton(c2, text='720p render patch (v2.6) + shader fix', variable=r720_var).pack(anchor='w', pady=(8, 0))
    ttk.Label(c2, style='Dim.TLabel', wraplength=330,
              text='Steady 30 FPS on Steam Deck. Off = stock 1080p (about 25 FPS on a Deck).').pack(anchor='w', padx=(24, 0))
    ttk.Checkbutton(c2, text='Xbox / Steam Deck button art', variable=xbox_var).pack(anchor='w', pady=(6, 0))
    ttk.Label(c2, style='Dim.TLabel', wraplength=330,
              text='A/B/X/Y glyphs, controller pictures, EX prompts and skill-slot badges.').pack(anchor='w', padx=(24, 0))
    ttk.Checkbutton(c2, text='Background shader compiles (fewer hitches)', variable=async_var).pack(anchor='w', pady=(6, 0))
    row = ttk.Frame(c2, style='Card.TFrame')
    row.pack(anchor='w', pady=(8, 0))
    ttk.Label(row, text='Frame rate', style='Card.TLabel').pack(side='left')
    ttk.Combobox(row, textvariable=fps_var, values=('30', '60', 'uncapped'), state='readonly', width=10).pack(side='left', padx=(8, 0))
    ttk.Label(c2, style='Dim.TLabel', wraplength=330,
              text='Always on: shop box lighting fix, save fix, PSN prompt skip, mission-end crash fix, F1 menu.').pack(anchor='w', pady=(8, 0))

    # Network / co-op lives in its own window; this card shows the choice and opens it.
    netrow = ttk.Frame(c1, style='Card.TFrame')
    netrow.grid(row=6, column=0, columnspan=3, sticky='ew', pady=(18, 0))
    net_btn = ttk.Button(netrow, text='Network / co-op…')
    net_btn.pack(side='left')
    net_var = tk.StringVar(value='')
    ttk.Label(netrow, textvariable=net_var, style='Dim.TLabel', wraplength=460, justify='left').pack(side='left', padx=(10, 0))

    def opts():
        return {'xbox': xbox_var.get(), 'render720': r720_var.get(), 'async': async_var.get(), 'fps': fps_var.get()}

    # --- card 3: log
    c3 = ttk.Frame(body, style='Card.TFrame', padding=12)
    c3.grid(row=1, column=0, sticky='nsew', padx=(0, 8))
    c3.rowconfigure(1, weight=1)
    c3.columnconfigure(0, weight=1)
    ttk.Label(c3, text='Log', style='Head.TLabel').grid(row=0, column=0, sticky='w')
    text = tk.Text(c3, background='#0b1016', foreground='#c9d1d9', insertbackground=FG, relief='flat',
                   font=('DejaVu Sans Mono', 10), wrap='word', height=10)
    text.grid(row=1, column=0, sticky='nsew', pady=(6, 0))
    sb = ttk.Scrollbar(c3, command=text.yview)
    sb.grid(row=1, column=1, sticky='ns', pady=(6, 0))
    text.configure(yscrollcommand=sb.set, state='disabled')

    # --- card 4: status + actions
    c4 = ttk.Frame(body, style='Card.TFrame', padding=12)
    c4.grid(row=1, column=1, sticky='nsew')
    ttk.Label(c4, text='3  Install and play', style='Head.TLabel').pack(anchor='w')
    status_var = tk.StringVar(value='')
    ttk.Label(c4, textvariable=status_var, style='Dim.TLabel', wraplength=330, justify='left').pack(anchor='w', pady=(6, 8))
    install_btn = ttk.Button(c4, text='Install', style='Primary.TButton')
    install_btn.pack(fill='x')
    play_btn = ttk.Button(c4, text='Play', style='Primary.TButton')
    play_btn.pack(fill='x', pady=(8, 0))
    grid = ttk.Frame(c4, style='Card.TFrame')
    grid.pack(fill='x', pady=(10, 0))
    grid.columnconfigure(0, weight=1)
    grid.columnconfigure(1, weight=1)
    imp_btn = ttk.Button(grid, text='Import old saves')
    bak_btn = ttk.Button(grid, text='Back up saves')
    rst_btn = ttk.Button(grid, text='Restore original files')
    chk_btn = ttk.Button(grid, text='Check setup')
    imp_btn.grid(row=0, column=0, sticky='ew', padx=(0, 4))
    bak_btn.grid(row=0, column=1, sticky='ew')
    rst_btn.grid(row=1, column=0, sticky='ew', padx=(0, 4), pady=(6, 0))
    chk_btn.grid(row=1, column=1, sticky='ew', pady=(6, 0))
    busy_var = tk.StringVar(value='')
    ttk.Label(c4, textvariable=busy_var, style='Dim.TLabel').pack(anchor='w', pady=(8, 0))

    # --- plumbing
    q = queue.Queue()
    state = {'busy': False, 'game': None}
    buttons = [install_btn, play_btn, imp_btn, bak_btn, rst_btn, chk_btn, net_btn]

    def log(msg):
        q.put(msg)

    def pump():
        try:
            while True:
                msg = q.get_nowait()
                text.configure(state='normal')
                text.insert('end', msg + '\n')
                if int(text.index('end-1c').split('.')[0]) > 4000:
                    text.delete('1.0', '500.0')
                text.see('end')
                text.configure(state='disabled')
        except queue.Empty:
            pass
        root.after(100, pump)

    def busy_set(on, label=''):
        state['busy'] = on
        busy_var.set(label if on else '')
        for b in buttons:
            b.state(['disabled'] if on else ['!disabled'])
        if not on:
            refresh()

    def refresh(*_):
        net_var.set(gui_net.summary())
        inst = core.Install(dir_var.get())
        lines = core.status(dir_var.get())
        status_var.set('\n'.join(lines[1:]))
        install_btn.configure(text='Apply options' if inst.has_game() and inst.has_runtime() else 'Install')
        if not state['busy']:
            play_btn.state(['!disabled'] if os.path.exists(inst.play) and inst.has_game() else ['disabled'])
            rst_btn.state(['!disabled'] if inst.has_game() else ['disabled'])

    def remember():
        cfg['pkg'] = pkg_var.get().strip()
        cfg['install_dir'] = dir_var.get().strip()
        core.save_config(cfg)

    def run_job(label, fn):
        if state['busy']:
            return
        remember()
        busy_set(True, label)

        def work():
            try:
                fn()
            except Exception as e:  # noqa: BLE001 - shown to the player
                log('ERROR: %s' % e)
                root.after(0, lambda: messagebox.showerror(core.APP_NAME, str(e), parent=root))
            finally:
                root.after(0, lambda: busy_set(False))
        threading.Thread(target=work, daemon=True).start()

    def on_install():
        d = dir_var.get().strip()
        inst = core.Install(d)
        if not inst.has_game():
            p = pkg_var.get().strip()
            if not p:
                messagebox.showinfo(core.APP_NAME, 'Pick your GUNDAM BREAKER 3 PKG first (Browse… or Find).', parent=root)
                return
            ok, msg = core.check_pkg(p)
            if not ok:
                messagebox.showerror(core.APP_NAME, msg, parent=root)
                return
            run_job('Installing (unpacking takes a few minutes)…', lambda: core.install(d, p, opts(), log))
        elif not inst.has_runtime():
            run_job('Installing…', lambda: core.install(d, None, opts(), log))
        else:
            run_job('Applying options…', lambda: core.apply_options(d, opts(), log))

    def on_play():
        if state['game'] and state['game'].poll() is None:
            messagebox.showinfo(core.APP_NAME, 'The game is already running.', parent=root)
            return
        remember()
        inst = core.Install(dir_var.get())
        sd = inst.save_dir()
        old = None if os.path.isdir(sd) and os.listdir(sd) else core.find_old_saves(inst)
        if old and messagebox.askyesno(core.APP_NAME, 'This install has no save yet, but one was found in\n%s\n\n'
                                       'Copy it here before playing? (The original stays where it is.)' % old,
                                       parent=root):
            core.import_saves(inst, log, [os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(old))))])
        try:
            p = core.play(dir_var.get())
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(core.APP_NAME, str(e), parent=root)
            return
        state['game'] = p
        log('== Game started (log follows)')

        def follow():
            for line in p.stdout:
                log(line.rstrip('\n'))
            log('== Game exited (code %s)' % p.wait())
        threading.Thread(target=follow, daemon=True).start()

    def on_restore():
        if not messagebox.askyesno(core.APP_NAME, 'Put the original game files back (no Xbox art, no 720p)?\n'
                                   'Saves are not touched. Install / Apply options re-applies the mods.', parent=root):
            return
        run_job('Restoring…', lambda: core.restore_all(dir_var.get(), log))

    def on_import():
        inst = core.Install(dir_var.get())
        if not inst.has_runtime():
            messagebox.showinfo(core.APP_NAME, 'Install first, then import saves.', parent=root)
            return
        src = filedialog.askdirectory(parent=root, title='Older psport bundle folder (holds user/savedata) - Cancel = search the usual places',
                                      initialdir=os.path.expanduser('~/Applications'))
        run_job('Importing saves…', lambda: core.import_saves(inst, log, [src] if src else None))

    net_btn.configure(command=lambda: gui_net.open_window(root, lambda: dir_var.get().strip(), log, refresh,
                                                          (PANEL, FG, DIM)))
    install_btn.configure(command=on_install)
    play_btn.configure(command=on_play)
    rst_btn.configure(command=on_restore)
    imp_btn.configure(command=on_import)
    bak_btn.configure(command=lambda: run_job('Backing up saves…', lambda: core.backup_saves(core.Install(dir_var.get()), log)))
    chk_btn.configure(command=lambda: run_job('Checking…', lambda: [log(l) for l in core.status(dir_var.get())]
                                              + [core.fix_interp(core.Install(dir_var.get()), log)
                                                 if core.Install(dir_var.get()).has_runtime() else log('psport runtime not installed yet')]))
    pkg_var.trace_add('write', lambda *_: root.after(300, check_pkg))
    dir_var.trace_add('write', lambda *_: root.after(300, refresh))

    log('%s %s' % (core.APP_NAME, core.APP_VERSION))
    log('Steam Deck detected.' if core.is_steamos() else 'Desktop Linux.')
    log('In game, F1 opens the psport menu. For Game Mode, add "GUNDAM BREAKER 3 (psport)" '
        'through Steam > Add a Non-Steam Game after installing.')
    check_pkg()
    refresh()
    pump()
    root.mainloop()
    return 0
