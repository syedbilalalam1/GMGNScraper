import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
import sys
import logging
import subprocess
import json

# Allow running from repo root without installing as a package
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if SRC_DIR.exists() and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ken_automation.scrapers.gmgn_scraper import scrape_gmgn_sync, save_addresses_to_csv


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("GMGN Address Scraper")
        self.geometry("700x480")

        # logging setup
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)
        self.log_path = logs_dir / "gmgn_gui.log"
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                logging.FileHandler(self.log_path, encoding="utf-8"),
                logging.StreamHandler(sys.stdout),
            ],
        )
        logging.info("App started")

        # state vars
        self.url_var = tk.StringVar(value="https://gmgn.ai/trade/uZy0WmVx?chain=sol")
        self.count_var = tk.IntVar(value=100)
        self.out_var = tk.StringVar(value=str(Path("output/gmgn_addresses.csv").absolute()))
        self.headless_var = tk.BooleanVar(value=False)
        self.profile_var = tk.StringVar(value=r"C:\\Users\\Bilal\\AppData\\Local\\Google\\Chrome\\User Data\\Profile 53")
        self.proxy_var = tk.StringVar(value="")
        self.cdp_var = tk.StringVar(value="")
        self.engine_var = tk.StringVar(value="puppeteer")
        self.chrome_path_var = tk.StringVar(value="")

        # layout
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="URL").grid(row=0, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frm, textvariable=self.url_var, width=68).grid(row=0, column=1, columnspan=3, sticky=tk.EW)

        # Wallet -> Address URL builder
        self.wallet_var = tk.StringVar(value="")
        ttk.Label(frm, text="Wallet (Solana)").grid(row=1, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frm, textvariable=self.wallet_var, width=54).grid(row=1, column=1, columnspan=2, sticky=tk.EW)
        ttk.Button(frm, text="Make URL", command=self.make_wallet_url).grid(row=1, column=3, sticky=tk.W)

        ttk.Label(frm, text="Count").grid(row=2, column=0, sticky=tk.W, pady=4)
        ttk.Spinbox(frm, from_=1, to=1000, textvariable=self.count_var, width=10).grid(row=2, column=1, sticky=tk.W)

        ttk.Label(frm, text="Output CSV / Folder").grid(row=3, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frm, textvariable=self.out_var, width=54).grid(row=3, column=1, columnspan=2, sticky=tk.EW)
        ttk.Button(frm, text="Browse", command=self.browse_out).grid(row=3, column=3, sticky=tk.W)

        self.progress = ttk.Progressbar(frm, mode="indeterminate")
        self.progress.grid(row=4, column=0, columnspan=4, sticky=tk.EW, pady=10)

        self.start_btn = ttk.Button(frm, text="Start", command=self.on_start)
        self.start_btn.grid(row=5, column=0, sticky=tk.W, pady=8)
        self.view_log_btn = ttk.Button(frm, text="View Logs", command=self.open_logs)
        self.view_log_btn.grid(row=5, column=3, sticky=tk.E, padx=(8, 0))
        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(frm, textvariable=self.status_var).grid(row=5, column=2, sticky=tk.W)

        ttk.Label(frm, text="Chrome Profile").grid(row=6, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frm, textvariable=self.profile_var, width=54).grid(row=6, column=1, columnspan=2, sticky=tk.EW)
        ttk.Button(frm, text="Browse", command=self.browse_profile).grid(row=6, column=3, sticky=tk.W)

        ttk.Checkbutton(frm, text="Headless", variable=self.headless_var).grid(row=7, column=0, sticky=tk.W)

        ttk.Label(frm, text="Proxy (optional)").grid(row=8, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frm, textvariable=self.proxy_var, width=54).grid(row=8, column=1, columnspan=2, sticky=tk.EW)
        ttk.Label(frm, text="e.g. http://user:pass@host:port").grid(row=8, column=3, sticky=tk.W)

        ttk.Label(frm, text="CDP URL (optional)").grid(row=9, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frm, textvariable=self.cdp_var, width=54).grid(row=9, column=1, columnspan=2, sticky=tk.EW)
        ttk.Label(frm, text="e.g. http://localhost:9222").grid(row=9, column=3, sticky=tk.W)

        ttk.Label(frm, text="Engine").grid(row=10, column=0, sticky=tk.W, pady=4)
        engine_cb = ttk.Combobox(frm, textvariable=self.engine_var, values=["playwright", "puppeteer"], state="readonly", width=20)
        engine_cb.grid(row=10, column=1, sticky=tk.W)

        ttk.Label(frm, text="Chrome Path (optional)").grid(row=11, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frm, textvariable=self.chrome_path_var, width=54).grid(row=11, column=1, columnspan=2, sticky=tk.EW)
        ttk.Button(frm, text="Browse", command=self.browse_chrome).grid(row=11, column=3, sticky=tk.W)

        frm.columnconfigure(1, weight=1)
        frm.columnconfigure(2, weight=1)

    def make_wallet_url(self) -> None:
        # Build https://gmgn.ai/sol/address/<userKey>_<wallet>
        wallet = self.wallet_var.get().strip()
        if not wallet:
            messagebox.showwarning("Wallet required", "Enter a Solana wallet address first.")
            return
        cur = self.url_var.get().strip()
        user_key = "uZy0WmVx"  # default fallback
        try:
            # Try extract from /trade/<key>
            import re
            m = re.search(r"/trade/([A-Za-z0-9]+)", cur)
            if m:
                user_key = m.group(1)
            else:
                # Try /address/<key>_...
                m2 = re.search(r"/address/([A-Za-z0-9]+)_", cur)
                if m2:
                    user_key = m2.group(1)
        except Exception:
            pass
        new_url = f"https://gmgn.ai/sol/address/{user_key}_{wallet}"
        self.url_var.set(new_url)

    def browse_out(self) -> None:
        # For panel mode we save a folder; for list mode it's CSV
        url = self.url_var.get().strip()
        is_address = "/sol/address/" in url
        if is_address:
            folder = filedialog.askdirectory(title="Select output folder for JSON panels")
            if folder:
                self.out_var.set(folder)
        else:
            path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
            if path:
                self.out_var.set(path)

    def browse_profile(self) -> None:
        folder = filedialog.askdirectory(title="Select Chrome Profile folder or User Data root")
        if folder:
            self.profile_var.set(folder)

    def browse_chrome(self) -> None:
        path = filedialog.askopenfilename(title="Select chrome.exe", filetypes=[("Chrome Executable", "chrome.exe")])
        if path:
            self.chrome_path_var.set(path)

    def on_start(self) -> None:
        logging.info("Start clicked")
        self.start_btn.config(state=tk.DISABLED)
        self.progress.start(10)
        self.status_var.set("Opening site…")
        t = threading.Thread(target=self.run_scrape, daemon=True)
        t.start()

    def run_scrape(self) -> None:
        try:
            logging.info(
                "Scraping URL=%s count=%s headless=%s engine=%s",
                self.url_var.get(), self.count_var.get(), self.headless_var.get(), self.engine_var.get(),
            )
            engine = self.engine_var.get()
            url = self.url_var.get().strip()
            is_address = "/sol/address/" in url
            if engine == "puppeteer":
                if is_address:
                    # panels mode
                    # Ensure out_var points to a folder, not a CSV file
                    try:
                        outv = self.out_var.get().strip()
                        if not outv or outv.lower().endswith('.csv'):
                            default_dir = Path("output/panels").resolve()
                            default_dir.mkdir(parents=True, exist_ok=True)
                            self.out_var.set(str(default_dir))
                    except Exception:
                        pass
                    result = self.run_node_puppeteer(panels_mode=True)
                    # result expected: { paths: {panels, recentpnl, deployedtokens} }
                    self.after(0, lambda: self.on_done(success=True, count=0, path=str(result.get('outdir',''))))
                    return
                else:
                    addrs = self.run_node_puppeteer()
            else:
                addrs = scrape_gmgn_sync(
                    url=self.url_var.get(),
                    expected_count=self.count_var.get(),
                    headless=self.headless_var.get(),
                    browser_channel="chrome",
                    chrome_profile_path=self.profile_var.get().strip() or None,
                    proxy=self.proxy_var.get().strip() or None,
                    cdp_url=self.cdp_var.get().strip() or None,
                )
            out_path = Path(self.out_var.get())
            save_addresses_to_csv(addrs, out_path)
            logging.info("Saved %s addresses to %s", len(addrs), out_path)
            self.after(0, lambda: self.on_done(success=True, count=len(addrs), path=str(out_path)))
        except Exception as e:
            logging.exception("Scrape failed: %s", e)
            self.after(0, lambda err=e: self.on_done(success=False, error=str(err)))

    def on_done(self, success: bool, count: int = 0, path: str = "", error: str = "") -> None:
        self.progress.stop()
        self.start_btn.config(state=tk.NORMAL)
        if success:
            # If saving CSV (addresses) vs folder (panels)
            if path.lower().endswith('.csv'):
                self.status_var.set(f"Done: {count} addresses saved")
                messagebox.showinfo("Done", f"Saved {count} addresses to\n{path}")
            else:
                self.status_var.set("Done: panels saved")
                messagebox.showinfo("Done", f"Saved panels JSON to\n{path}")
        else:
            self.status_var.set("Failed")
            messagebox.showerror("Error", error)

    def open_logs(self) -> None:
        try:
            folder = str(Path(self.log_path).parent.resolve())
            subprocess.Popen(["explorer", folder])
        except Exception as e:
            logging.error("Failed to open logs folder: %s", e)

    def run_node_puppeteer(self, panels_mode: bool = False) -> list[str] | dict:
        try:
            node_script = Path(__file__).resolve().parents[1] / "node_scraper" / "gmgn_puppeteer.js"
            if not node_script.exists():
                raise FileNotFoundError(f"Node script not found: {node_script}")
            args = [
                "node",
                str(node_script),
                "--url", self.url_var.get(),
                "--count", str(self.count_var.get()),
                "--headless", "true" if self.headless_var.get() else "false",
            ]
            if panels_mode:
                args.append("--panels")
                # outdir defaults to chosen output path or ./output/panels
                outdir = self.out_var.get().strip()
                if not outdir:
                    outdir = str(Path("output/panels").resolve())
                    self.out_var.set(outdir)
                args.extend(["--outdir", outdir])
            profile = self.profile_var.get().strip()
            if profile:
                args.extend(["--profile", profile])
            proxy = self.proxy_var.get().strip()
            if proxy:
                args.extend(["--proxy", proxy])
            cdp = self.cdp_var.get().strip()
            if cdp:
                args.extend(["--cdp", cdp])
            chrome_path = self.chrome_path_var.get().strip()
            if chrome_path:
                args.extend(["--chrome", chrome_path])

            # Provide a session file path for Puppeteer persistence
            session_dir = Path(".sessions")
            session_dir.mkdir(parents=True, exist_ok=True)
            session_file = session_dir / "gmgn_ai_session.json"
            args.extend(["--session", str(session_file.resolve())])

            logging.info("Running puppeteer-extra script: %s", " ".join(args))

            # Stream stderr for status events
            proc = subprocess.Popen(
                args,
                cwd=str(node_script.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )

            def reader_thread():
                try:
                    if proc.stderr:
                        for line in proc.stderr:
                            line = (line or '').strip()
                            if not line:
                                continue
                            logging.info("puppeteer: %s", line)
                            if line.startswith('[STATUS]'):
                                if 'PAGE_OPENED' in line:
                                    self.after(0, lambda: self.status_var.set('Site opened. Waiting login...'))
                                elif 'WAITING_LOGIN' in line:
                                    self.after(0, lambda: self.status_var.set('Waiting for login...'))
                                elif 'LOGGED_IN' in line:
                                    self.after(0, lambda: self.status_var.set('Logged in. Countdown 10s...'))
                                elif 'COUNTDOWN' in line:
                                    try:
                                        parts = line.split()
                                        sec = parts[-1]
                                        self.after(0, lambda s=sec: self.status_var.set(f'Scraping starts in {s}s'))
                                    except Exception:
                                        pass
                except Exception:
                    pass

            t = threading.Thread(target=reader_thread, daemon=True)
            t.start()

            out = proc.stdout.read() if proc.stdout else ''
            proc.wait(timeout=240)
            data = json.loads(out.strip()) if out and out.strip().startswith('{') else {"addresses": []}
            if panels_mode:
                return data
            addrs = data.get("addresses", []) or []
            return list(dict.fromkeys(addrs))
        except Exception as e:
            logging.exception("Node puppeteer run failed: %s", e)
            return {} if panels_mode else []


if __name__ == "__main__":
    App().mainloop()
