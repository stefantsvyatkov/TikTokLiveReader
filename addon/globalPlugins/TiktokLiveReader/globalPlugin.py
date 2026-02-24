from pathlib import Path
import configparser
import datetime
import json
import threading
import time

from . import client
from globalPluginHandler import GlobalPlugin as NVDA_GlobalPlugin
from scriptHandler import script
import addonHandler
import gui
import ui
import wx

addonHandler.initTranslation()

client._cached_translate = _

ADDON_DIR = Path(__file__).resolve().parent
CONFIG_FILE = ADDON_DIR / "config.ini"
POS_FILE = ADDON_DIR / "positions.json"

LOG_DIR = Path.home() / "Documents" / "TikTok live"
STATS_FILE = LOG_DIR / "stats.txt"
SPEECH_BUFFER_FILE = LOG_DIR / "speechbuffer.json"
DEBUG_LOG = LOG_DIR / "debug.log"

def _log_debug(msg):
    try:
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"GP {datetime.datetime.now()}: {msg}\n")
    except Exception:
        pass

FILES = [
    (_("Comments"), "comments.txt"),
    (_("Events"), "events.txt"),
    (_("Followers"), "followers.txt"),
    (_("Gifts"), "gifts.txt"),
    (_("Likes"), "likes.txt"),
    (_("Shares"), "shares.txt"),
    (_("Stats"), "stats.txt"),
    (_("Top gifters"), "top gifters.txt"),
    (_("Top likes"), "top likes.txt"),
    (_("Visitors"), "visitors.txt"),
]

NAV_GESTURES = {
    "kb:control+shift+downArrow": "nextItem",
    "kb:control+shift+upArrow": "prevItem",
    "kb:control+shift+home": "firstItem",
    "kb:control+shift+end": "lastItem",
    "kb:control+shift+leftArrow": "prevFile",
    "kb:control+shift+rightArrow": "nextFile",
    "kb:NVDA+control+shift+s": "toggleAutoSpeak",
    "kb:NVDA+control+shift+r": "clearTextFiles",
    "kb:NVDA+control+shift+v": "reportViewers",
    "kb:NVDA+shift+control+p": "togglePlaySounds",
}


TRACKED_KEYS = {"comments", "followers", "gifts", "likes", "visitors"}


def _filename_key_map():
    m = {}
    for i, (_label, fname) in enumerate(FILES):
        base = fname.split(".")[0].lower().replace(" ", "")
        m[i] = base
    return m


INDEX_TO_KEY = _filename_key_map()


class SpeechManager:
    def __init__(self, plugin):
        self._running = False
        self._thread = None
        self.plugin = plugin

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None

    def speak(self, text):
        try:
            with open(SPEECH_BUFFER_FILE, "a", encoding="utf-8") as f:
                rec = {"text": text, "time": time.time()}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _worker(self):
        
        last_pos = 0
        if SPEECH_BUFFER_FILE.exists():
            last_pos = SPEECH_BUFFER_FILE.stat().st_size
            
        while self._running:
            if not SPEECH_BUFFER_FILE.exists():
                time.sleep(0.5)
                continue
                
            try:
                curr_size = SPEECH_BUFFER_FILE.stat().st_size
                if curr_size < last_pos:
                    last_pos = 0
                
                if curr_size > last_pos:
                    with open(SPEECH_BUFFER_FILE, "r", encoding="utf-8") as f:
                        f.seek(last_pos)
                        lines = f.readlines()
                        last_pos = f.tell()
                        
                    for line in lines:
                        if not self._running:
                            break
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            _log_debug(f"Speaking: {line}")
                            data = json.loads(line)
                            txt = data.get("text", "")
                            if txt:
                                ui.message(txt)
                                time.sleep(float(self.plugin.autoSpeakDelay))
                        except Exception as e:
                            _log_debug(f"Speech error: {e}")
            except Exception:
                pass
            
            time.sleep(0.5)


class GlobalPlugin(NVDA_GlobalPlugin):
    __gestures = {
        "kb:NVDA+control+shift+t": "toggleActive",
        "kb:NVDA+control+shift+l": "openSettingsDialog",
    }

    def __init__(self):
        super().__init__()
        self.active = False
        self.autoSpeak = False

        self.index = -1
        self._watcherThread = None
        self._settingsDialog = None
        self.speech_manager = SpeechManager(self)
        self.currentFileIndex = 0
        self.filePositions = {i: -1 for i in range(len(FILES))}
        self.username, self.prefs, self.auto_speak_prefs, self.clearOnStart, self.cleanUsernames, self.retryCount, self.playSounds, self.soundVolume, self.autoSpeak = self._load_config()
        self.autoSpeakDelay = 1.0 # Default delay for auto speak
        
        client.update_config(self.username, self.prefs, self.auto_speak_prefs, self.playSounds, self.soundVolume, self.clearOnStart, self.cleanUsernames)

        if not self.clearOnStart:
            self._load_positions_json()
            self.index = self.filePositions.get(self.currentFileIndex, -1)
            
        if self.autoSpeak:
             self.speech_manager.start()

    def _load_config(self):
        try:
            cfg = configparser.ConfigParser()
            if CONFIG_FILE.exists():
                cfg.read(CONFIG_FILE, encoding="utf-8")
            
            if "main" not in cfg:
                cfg["main"] = {"username": ""}
                
            
            if "events" not in cfg:
                if "auto_read" in cfg:
                    cfg["events"] = cfg["auto_read"]
                else:
                    cfg["events"] = {
                        "comments": "true",
                        "followers": "false",
                        "gifts": "false",
                        "likes": "false",
                        "shares": "false",
                        "visitors": "false",
                    }
    
            if "auto_speak" not in cfg:
                cfg["auto_speak"] = {
                    "comments": "true",
                    "followers": "false",
                    "gifts": "false",
                    "likes": "false",
                    "shares": "false",
                    "visitors": "false",
                }
    
            if "behavior" not in cfg:
                cfg["behavior"] = {"clear_on_start": "true", "clean_usernames": "false", "retry_count": "3"}
                
            if "sounds" not in cfg:
                cfg["sounds"] = {"play_sounds": "false", "volume": "100"}
    
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                cfg.write(f)
                
            return (
                cfg.get("main", "username", fallback=""),
                {
                    "comments": cfg.getboolean("events", "comments", fallback=True),
                    "followers": cfg.getboolean("events", "followers", fallback=False),
                    "gifts": cfg.getboolean("events", "gifts", fallback=False),
                    "likes": cfg.getboolean("events", "likes", fallback=False),
                    "shares": cfg.getboolean("events", "shares", fallback=False),
                    "visitors": cfg.getboolean("events", "visitors", fallback=False),
                },
                {
                    "comments": cfg.getboolean("auto_speak", "comments", fallback=True),
                    "followers": cfg.getboolean("auto_speak", "followers", fallback=False),
                    "gifts": cfg.getboolean("auto_speak", "gifts", fallback=False),
                    "likes": cfg.getboolean("auto_speak", "likes", fallback=False),
                    "shares": cfg.getboolean("auto_speak", "shares", fallback=False),
                    "visitors": cfg.getboolean("auto_speak", "visitors", fallback=False),
                },
                cfg.getboolean("behavior", "clear_on_start", fallback=True),
                cfg.getboolean("behavior", "clean_usernames", fallback=False),
                cfg.getint("behavior", "retry_count", fallback=3),
                cfg.getboolean("sounds", "play_sounds", fallback=False),
                cfg.getint("sounds", "volume", fallback=100),
                cfg.getboolean("auto_speak", "enabled", fallback=False), 
            )
        except Exception as e:
            _log_debug(f"Config load error: {e}")
            return ("", {}, {}, True, False, 3, False, 100, False)

    def _save_config(self, username, prefs, auto_speak_prefs, clear_on_start, clean_usernames, retry_count, play_sounds, volume):
        cfg = configparser.ConfigParser()
        cfg["main"] = {"username": username}
        cfg["events"] = {k: "true" if v else "false" for k, v in prefs.items()}
        cfg["auto_speak"] = {k: "true" if v else "false" for k, v in auto_speak_prefs.items()}
        cfg["auto_speak"]["enabled"] = "true" if self.autoSpeak else "false"
        cfg["behavior"] = {
            "clear_on_start": "true" if clear_on_start else "false",
            "clean_usernames": "true" if clean_usernames else "false",
            "retry_count": str(retry_count),
        }
        cfg["sounds"] = {
            "play_sounds": "true" if play_sounds else "false",
            "volume": str(volume)
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)
        self.username = username
        self.prefs = prefs
        self.auto_speak_prefs = auto_speak_prefs
        self.clearOnStart = clear_on_start
        self.cleanUsernames = clean_usernames
        self.retryCount = retry_count
        self.playSounds = play_sounds
        self.soundVolume = volume
        
        client.update_config(self.username, self.prefs, self.auto_speak_prefs, self.playSounds, self.soundVolume, self.clearOnStart, self.cleanUsernames)

    def _load_positions_json(self):
        try:
            data = json.loads(POS_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {"version": 1, "files": {}}
        for i in range(len(FILES)):
            k = INDEX_TO_KEY[i]
            if k in TRACKED_KEYS:
                self.filePositions[i] = int(data.get("files", {}).get(k, {}).get("line", -1))

    def _save_positions_json(self):
        try:
            data = {"version": 1, "files": {}}
            for i in range(len(FILES)):
                k = INDEX_TO_KEY[i]
                if k in TRACKED_KEYS:
                    data["files"][k] = {"line": int(self.filePositions.get(i, -1))}
            POS_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _bind_nav(self):
        for g, s in NAV_GESTURES.items():
            self.bindGesture(g, s)

    def _unbind_nav(self):
        self.clearGestureBindings()
        for g, s in self.__gestures.items():
            self.bindGesture(g, s)

    def _get_current_file(self):
        name, filename = FILES[self.currentFileIndex]
        return name, LOG_DIR / filename

    def _load_items(self):
        _label, file = self._get_current_file()
        try:
            with file.open("r", encoding="utf-8") as f:
                return [ln.strip() for ln in f if ln.strip()]
        except FileNotFoundError:
            return []

    def _speak_current(self, items):
        if 0 <= self.index < len(items):
            if FILES[self.currentFileIndex][1] == "stats.txt":
                ui.message(items[self.index])
            else:
                num = self.index + 1
                total = len(items)
                # Translators: Announced when navigating items. {item} is the content, {num} is current position, {total} is total count.
                ui.message(_("{item} ({num} of {total})").format(item=items[self.index], num=num, total=total))
        else:
            # Translators: Announced when there is no entry at the current position.
            ui.message(_("No entries"))


    # Translators: Description shown in NVDA Input Gestures dialog.
    @script(description=_("Toggle TikTok Live Reader on or off"), category=_("TikTok Live Reader"))
    def script_toggleActive(self, gesture):
        if self._settingsDialog:
            return
        self.active = not self.active
        if self.active:
            self._bind_nav()
            self.index = self.filePositions.get(self.currentFileIndex, -1) if not self.clearOnStart else -1
            if self.autoSpeak:
                self.speech_manager.start()
            else:
                self.speech_manager.stop()
            # Translators: Announced when the addon is turned on.
            ui.message(_("TikTok Live Reader On"))

            def on_conn():
                # Translators: Announced when successfully connected to a TikTok live. {username} is the streamer name.
                ui.message(_("Connected to user: {username}").format(username=self.username))

            def on_retry():
                # Translators: Announced when attempting to reconnect.
                ui.message(_("Attempting to connect..."))

            def on_fail():
                # Translators: Announced when connection fails after all retries.
                ui.message(_("Connection unsuccessful."))
                self.active = False
                self._unbind_nav()
                client.disconnect()
                self.speech_manager.stop()
                self._cleanup_temp_files()

            client.connect(username=self.username, on_connect=on_conn, on_retry=on_retry, on_fail=on_fail, retry_count=self.retryCount)
        else:
            self._unbind_nav()
            # Translators: Announced when the addon is turned off.
            ui.message(_("TikTok Live Reader Off"))
            client.disconnect()
            self.speech_manager.stop()
            self._cleanup_temp_files()

    def _cleanup_temp_files(self):
        try:
            if SPEECH_BUFFER_FILE.exists():
                SPEECH_BUFFER_FILE.unlink()
            if POS_FILE.exists():
                POS_FILE.unlink()
        except Exception:
            pass

    # Translators: Description shown in NVDA Input Gestures dialog.
    @script(description=_("Toggle automatic speaking of new events"), category=_("TikTok Live Reader"))
    def script_toggleAutoSpeak(self, gesture):
        if not self.active:
            gesture.send()
            return
        self.autoSpeak = not self.autoSpeak
        
        self._save_config(
            self.username, 
            self.prefs, 
            self.auto_speak_prefs,
            self.clearOnStart, 
            self.cleanUsernames, 
            self.retryCount, 
            self.playSounds,
            self.soundVolume
        )
        
        if self.autoSpeak:
            # Translators: Announced when auto speak is enabled.
            ui.message(_("Auto speak On"))
            self.speech_manager.start()
        else:
            # Translators: Announced when auto speak is disabled.
            ui.message(_("Auto speak Off"))
            self.speech_manager.stop()

    # Translators: Description shown in NVDA Input Gestures dialog.
    @script(
        description=_("Toggle sound playback for selected events"),
        category=_("TikTok Live Reader")
    )
    def script_togglePlaySounds(self, gesture):
        if not self.active:
            gesture.send()
            return

        self.playSounds = not self.playSounds
        
        self._save_config(
            self.username, 
            self.prefs, 
            self.auto_speak_prefs,
            self.clearOnStart, 
            self.cleanUsernames, 
            self.retryCount, 
            self.playSounds,
            self.soundVolume
        )
        
        client.update_config(self.username, self.prefs, self.auto_speak_prefs, self.playSounds, self.soundVolume, self.clearOnStart, self.cleanUsernames)
        
        if self.playSounds:
            # Translators: Announced when sounds are enabled.
            ui.message(_("Sounds On"))
        else:
            # Translators: Announced when sounds are disabled.
            ui.message(_("Sounds Off"))

    # Translators: Description shown in NVDA Input Gestures dialog.
    @script(description=_("Open TikTok Live Reader settings"), category=_("TikTok Live Reader"))
    def script_openSettingsDialog(self, gesture):
        if self._settingsDialog:
            self._settingsDialog.Raise()
            return
        wx.CallAfter(self._showSettingsDialog)

    def _showSettingsDialog(self):
        if self._settingsDialog:
            return
        was_active = self.active
        if was_active:
            self.active = False
            self._unbind_nav()
            self.autoSpeak = False
            client.disconnect()
            
        client.sound_manager.start()
            
        # Translators: Title of the settings dialog.
        dlg = wx.Dialog(gui.mainFrame, title=_("TikTok Live Reader Settings"))
        self._settingsDialog = dlg
        nb = wx.Notebook(dlg)

        p_general = wx.Panel(nb)
        p_events = wx.Panel(nb)
        p_autospeak = wx.Panel(nb)

        s_general = wx.BoxSizer(wx.VERTICAL)
        
        # Translators: Label for the username text field in settings.
        lbl_user = wx.StaticText(p_general, label=_("&User name"))
        txt_user = wx.TextCtrl(p_general, value=self.username)
        # Translators: Checkbox label in settings.
        chk_clear = wx.CheckBox(p_general, label=_("&Clear text files on startup"))
        # Translators: Checkbox label in settings.
        chk_strip = wx.CheckBox(p_general, label=_("Cl&ean user names"))

        chk_clear.SetValue(self.clearOnStart)
        chk_strip.SetValue(self.cleanUsernames)

        # Translators: Label for the retry count spinner in settings.
        lbl_retry = wx.StaticText(p_general, label=_("Connection &retry count"))
        spin_retry = wx.SpinCtrl(p_general, value=str(self.retryCount), min=1, max=10)
        
        s_general.Add(lbl_user, flag=wx.ALL, border=5)
        s_general.Add(txt_user, flag=wx.EXPAND | wx.ALL, border=5)
        s_general.Add(chk_clear, flag=wx.ALL, border=5)
        s_general.Add(chk_strip, flag=wx.ALL, border=5)
        s_general.Add(lbl_retry, flag=wx.ALL, border=5)
        s_general.Add(spin_retry, flag=wx.ALL, border=5)
        p_general.SetSizer(s_general)

        s_events = wx.BoxSizer(wx.VERTICAL)
        chk_ev_comments = wx.CheckBox(p_events, label=_("&Comments"))
        chk_ev_followers = wx.CheckBox(p_events, label=_("&Followers"))
        chk_ev_gifts = wx.CheckBox(p_events, label=_("&Gifts"))
        chk_ev_likes = wx.CheckBox(p_events, label=_("&Likes"))
        chk_ev_shares = wx.CheckBox(p_events, label=_("&Shares"))
        chk_ev_visitors = wx.CheckBox(p_events, label=_("&Visitors"))

        chk_ev_comments.SetValue(self.prefs.get("comments", True))
        chk_ev_followers.SetValue(self.prefs.get("followers", False))
        chk_ev_gifts.SetValue(self.prefs.get("gifts", False))
        chk_ev_likes.SetValue(self.prefs.get("likes", False))
        chk_ev_shares.SetValue(self.prefs.get("shares", False))
        chk_ev_visitors.SetValue(self.prefs.get("visitors", False))

        for chk in [chk_ev_comments, chk_ev_followers, chk_ev_gifts, chk_ev_likes, chk_ev_shares, chk_ev_visitors]:
            s_events.Add(chk, flag=wx.ALL, border=5)

        s_events.Add(wx.StaticLine(p_events), flag=wx.EXPAND|wx.ALL, border=5)

        # Translators: Checkbox to enable playing sounds for selected events.
        chk_play_sounds = wx.CheckBox(p_events, label=_("&Play sounds for the selected events"))
        chk_play_sounds.SetValue(self.playSounds)
        s_events.Add(chk_play_sounds, flag=wx.ALL, border=5)

        # Translators: Label for volume slider.
        lbl_volume = wx.StaticText(p_events, label=_("V&olume"))
        slider_volume = wx.Slider(p_events, value=self.soundVolume, minValue=0, maxValue=100, style=wx.SL_HORIZONTAL, name=_("V&olume"))
        s_events.Add(lbl_volume, flag=wx.ALL, border=5)
        s_events.Add(slider_volume, flag=wx.EXPAND | wx.ALL, border=5)

        # Translators: Button to learn sounds.
        btn_learn = wx.Button(p_events, label=_("L&earn sounds"))
        
        self._learning_thread = None
        self._stop_learning = threading.Event()

        s_events.Add(btn_learn, flag=wx.ALL, border=5)

        def on_toggle_sounds(evt):
            is_checked = chk_play_sounds.IsChecked()
            slider_volume.Enable(is_checked)
            lbl_volume.Enable(is_checked)
            btn_learn.Enable(is_checked)
            if not is_checked and self._learning_thread and self._learning_thread.is_alive():
                self._stop_learning.set()
                btn_learn.SetLabel(_("L&earn sounds"))
            
        def on_volume_change(evt):
            vol = slider_volume.GetValue()
            client.sound_manager.set_volume(vol)
            
        chk_play_sounds.Bind(wx.EVT_CHECKBOX, on_toggle_sounds)
        slider_volume.Bind(wx.EVT_SLIDER, on_volume_change)
        
        on_toggle_sounds(None)

        def on_learn_sounds(evt):
             if self._learning_thread and self._learning_thread.is_alive():
                 self._stop_learning.set()
                 btn_learn.SetLabel(_("L&earn sounds"))
                 return

             self._stop_learning.clear()
             btn_learn.SetLabel(_("St&op"))

             try:
                 initial_vol = slider_volume.GetValue()
             except Exception:
                 initial_vol = 100

             def _learner(vol):
                 try:
                     if client.sound_manager._running:
                         client.sound_manager.stop()
                         time.sleep(0.2)
                     client.sound_manager.start()
                     
                     sequence = [
                         (_("Comment"), "comments"),
                         (_("Follower"), "followers"),
                         (_("Gift"), "gifts"),
                         (_("Like"), "likes"),
                         (_("Sharing"), "shares"),
                         (_("Visitor"), "visitors"),
                     ]
                     
                     client.sound_manager.set_volume(vol)
                     
                     for label, event_key in sequence:
                         if self._stop_learning.is_set():
                             break
                         
                         ui.message(label)
                         
                         for _i in range(10):
                             if self._stop_learning.is_set():
                                 break
                             time.sleep(0.1)
                         
                         if self._stop_learning.is_set():
                             break

                         done = threading.Event()
                         client.sound_manager.play(event_key, play_file=True, post_delay=0.0, on_complete=lambda: done.set())
                         
                         start_wait = time.time()
                         while not done.is_set():
                             if self._stop_learning.is_set():
                                 break
                             if time.time() - start_wait > 5.0:
                                 break
                             time.sleep(0.1)
                         
                         if self._stop_learning.is_set():
                             break

                         time.sleep(0.5)
                 
                 except Exception:
                     pass
                 finally:
                     wx.CallAfter(btn_learn.SetLabel, _("L&earn sounds"))
                     
             self._learning_thread = threading.Thread(target=_learner, args=(initial_vol,), daemon=True)
             self._learning_thread.start()

        btn_learn.Bind(wx.EVT_BUTTON, on_learn_sounds)
        p_events.SetSizer(s_events)

        s_autospeak = wx.BoxSizer(wx.VERTICAL)
        # Translators: Checkbox to enable automatic speaking for selected events.
        chk_auto_speak = wx.CheckBox(p_autospeak, label=_("&Auto speak selected events"))
        chk_auto_speak.SetValue(self.autoSpeak)
        s_autospeak.Add(chk_auto_speak, flag=wx.ALL, border=5)
        
        sl_as1 = wx.StaticLine(p_autospeak)
        s_autospeak.Add(sl_as1, flag=wx.EXPAND|wx.ALL, border=5)

        # Translators: Section description or label
        lbl_as_desc = wx.StaticText(p_autospeak, label=_("Automatically speak:"))
        s_autospeak.Add(lbl_as_desc, flag=wx.ALL, border=5)
        
        chk_as_comments = wx.CheckBox(p_autospeak, label=_("&Comments"))
        chk_as_followers = wx.CheckBox(p_autospeak, label=_("&Followers"))
        chk_as_gifts = wx.CheckBox(p_autospeak, label=_("&Gifts"))
        chk_as_likes = wx.CheckBox(p_autospeak, label=_("&Likes"))
        chk_as_shares = wx.CheckBox(p_autospeak, label=_("&Shares"))
        chk_as_visitors = wx.CheckBox(p_autospeak, label=_("&Visitors"))

        chk_as_comments.SetValue(self.auto_speak_prefs.get("comments", True))
        chk_as_followers.SetValue(self.auto_speak_prefs.get("followers", False))
        chk_as_gifts.SetValue(self.auto_speak_prefs.get("gifts", False))
        chk_as_likes.SetValue(self.auto_speak_prefs.get("likes", False))
        chk_as_shares.SetValue(self.auto_speak_prefs.get("shares", False))
        chk_as_visitors.SetValue(self.auto_speak_prefs.get("visitors", False))

        sub_chks = [chk_as_comments, chk_as_followers, chk_as_gifts, chk_as_likes, chk_as_shares, chk_as_visitors]
        for chk in sub_chks:
            s_autospeak.Add(chk, flag=wx.ALL, border=5)

        sl_as2 = wx.StaticLine(p_autospeak)
        s_autospeak.Add(sl_as2, flag=wx.EXPAND|wx.ALL, border=5)

        def on_toggle_auto_speak(evt):
            is_checked = chk_auto_speak.IsChecked()
            sl_as1.Show(is_checked)
            lbl_as_desc.Show(is_checked)
            for chk in sub_chks:
                chk.Show(is_checked)
            sl_as2.Show(is_checked)
            p_autospeak.Layout()

        chk_auto_speak.Bind(wx.EVT_CHECKBOX, on_toggle_auto_speak)
        on_toggle_auto_speak(None)
        
        p_autospeak.SetSizer(s_autospeak)

        # Translators: Tab name in settings dialog.
        nb.AddPage(p_general, _("General"))
        # Translators: Tab name in settings dialog.
        nb.AddPage(p_events, _("Events"))
        # Translators: Tab name in settings dialog.
        nb.AddPage(p_autospeak, _("Auto speak"))

        topsizer = wx.BoxSizer(wx.VERTICAL)
        topsizer.Add(nb, 1, wx.EXPAND | wx.ALL, 5)
        btn_sizer = wx.StdDialogButtonSizer()
        btn_ok = wx.Button(dlg, wx.ID_OK, _("OK"))
        # Translators: Cancel button label in the settings dialog.
        btn_cancel = wx.Button(dlg, wx.ID_CANCEL, _("Cancel"))
        btn_ok.SetDefault()
        btn_sizer.AddButton(btn_ok)
        btn_sizer.AddButton(btn_cancel)
        btn_sizer.Realize()
        topsizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 5)
        dlg.SetSizerAndFit(topsizer)
        dlg.CentreOnScreen()
        dlg.Raise()
        txt_user.SetFocus()
        txt_user.SetInsertionPointEnd()

        if dlg.ShowModal() == wx.ID_OK:
            self.autoSpeak = chk_auto_speak.IsChecked()
            
            if self.active:
                if self.autoSpeak:
                    self.speech_manager.start()
                else:
                    self.speech_manager.stop()
                    
            prefs = {
                "comments": chk_ev_comments.IsChecked(),
                "followers": chk_ev_followers.IsChecked(),
                "gifts": chk_ev_gifts.IsChecked(),
                "likes": chk_ev_likes.IsChecked(),
                "shares": chk_ev_shares.IsChecked(),
                "visitors": chk_ev_visitors.IsChecked(),
            }
            auto_speak_prefs = {
                "comments": chk_as_comments.IsChecked(),
                "followers": chk_as_followers.IsChecked(),
                "gifts": chk_as_gifts.IsChecked(),
                "likes": chk_as_likes.IsChecked(),
                "shares": chk_as_shares.IsChecked(),
                "visitors": chk_as_visitors.IsChecked(),
            }
            
            self._save_config(
                txt_user.GetValue().strip(), 
                prefs, 
                auto_speak_prefs,
                chk_clear.IsChecked(), 
                chk_strip.IsChecked(), 
                spin_retry.GetValue(), 
                chk_play_sounds.IsChecked(),
                slider_volume.GetValue()
            )
        
        if hasattr(self, "_stop_learning"):
            self._stop_learning.set()
            
        dlg.Destroy()
        self._settingsDialog = None

    def _persist_index(self):
        if not self.clearOnStart:
            self.filePositions[self.currentFileIndex] = self.index
            self._save_positions_json()

    @script(description=_("Next item"))
    def script_nextItem(self, gesture):
        if not self.active:
            return
        items = self._load_items()
        if not items:
            # Translators: Announced when a file has no entries.
            ui.message(_("No entries"))
            return
        if self.index == -1:
            self.index = 0
        elif self.index < len(items) - 1:
            self.index += 1
        self._persist_index()
        self._speak_current(items)

    @script(description=_("Previous item"))
    def script_prevItem(self, gesture):
        if not self.active:
            return
        items = self._load_items()
        if not items:
            ui.message(_("No entries"))
            return
        if self.index == -1:
            self.index = 0
        elif self.index > 0:
            self.index -= 1
        self._persist_index()
        self._speak_current(items)

    @script(description=_("First item"))
    def script_firstItem(self, gesture):
        if not self.active:
            return
        items = self._load_items()
        if not items:
            ui.message(_("No entries"))
            return
        self.index = 0
        self._persist_index()
        self._speak_current(items)

    @script(description=_("Last item"))
    def script_lastItem(self, gesture):
        if not self.active:
            return
        items = self._load_items()
        if not items:
            ui.message(_("No entries"))
            return
        self.index = len(items) - 1
        self._persist_index()
        self._speak_current(items)

    @script(description=_("Previous file"))
    def script_prevFile(self, gesture):
        if not self.active:
            return
        self.filePositions[self.currentFileIndex] = self.index
        self.currentFileIndex = (self.currentFileIndex - 1) % len(FILES)
        self.index = self.filePositions.get(self.currentFileIndex, -1)
        self._persist_index()
        name, _path = self._get_current_file()
        ui.message(name)

    @script(description=_("Next file"))
    def script_nextFile(self, gesture):
        if not self.active:
            return
        self.filePositions[self.currentFileIndex] = self.index
        self.currentFileIndex = (self.currentFileIndex + 1) % len(FILES)
        self.index = self.filePositions.get(self.currentFileIndex, -1)
        self._persist_index()
        name, _path = self._get_current_file()
        ui.message(name)

    # Translators: Description shown in NVDA Input Gestures dialog.
    @script(description=_("Clear all log files and reset positions"), category=_("TikTok Live Reader"))
    def script_clearTextFiles(self, gesture):
        if not self.active:
            return
        client._clear_all_text_files()
        for i in range(len(FILES)):
            self.filePositions[i] = -1
        self.index = -1
        try:
            POS_FILE.write_text(json.dumps({"version": 1, "files": {}}, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        client.reset_accumulators()
        # Translators: Announced after clearing all log files.
        ui.message(_("All files cleared."))

    # Translators: Description shown in NVDA Input Gestures dialog.
    @script(description=_("Report the current number of live viewers"), category=_("TikTok Live Reader"))
    def script_reportViewers(self, gesture):
        if not self.active:
            # Translators: Announced when trying to use a feature while the addon is off.
            ui.message(_("Addon is not active."))
            return
        count = getattr(client, "viewer_count", 0)
        # Translators: Announced when reporting viewer count. {count} is the number.
        ui.message(_("{count} viewers").format(count=count))

    def terminate(self):
        try:
            client.disconnect()
            if hasattr(self, "speech_manager"):
                self.speech_manager.stop()
        except Exception:
            pass
        return super().terminate()
