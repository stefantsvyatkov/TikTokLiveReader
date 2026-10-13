from pathlib import Path
import json
import re
import threading
import time

from . import announcer, pipeline, session, settings, store
from .i18n import _
from globalPluginHandler import GlobalPlugin as NVDA_GlobalPlugin
from scriptHandler import script
import gui
from gui import message
import ui
import wx


def _add_event_checkboxes(parent, sizer, values):
    labels = (
        ("comments", _("&Comments")),
        ("followers", _("&Followers")),
        ("gifts", _("&Gifts")),
        ("likes", _("&Likes")),
        ("requests", _("&Requests")),
        ("shares", _("&Shares")),
        ("visitors", _("&Visitors")),
    )
    checks = {}
    for key, label in labels:
        chk = wx.CheckBox(parent, label=label)
        chk.SetValue(bool(values.get(key, settings.DEFAULT_EVENT_PREFS[key])))
        sizer.Add(chk, flag=wx.ALL, border=5)
        checks[key] = chk
    return checks



FILES = [
    ("Comments", "comments.txt"),
    ("Events", "events.txt"),
    ("Followers", "followers.txt"),
    ("Gifts", "gifts.txt"),
    ("Likes", "likes.txt"),
    ("Requests", "requests.txt"),
    ("Shares", "shares.txt"),
    ("Stats", "stats.txt"),
    ("Top gifters", "top gifters.txt"),
    ("Top likes", "top likes.txt"),
    ("Visitors", "visitors.txt"),
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


TRACKED_KEYS = {"comments", "followers", "gifts", "likes", "visitors", "shares", "requests"}


def _filename_key_map():
    m = {}
    for i, (_label, fname) in enumerate(FILES):
        base = fname.split(".")[0].lower().replace(" ", "")
        m[i] = base
    return m


INDEX_TO_KEY = _filename_key_map()


class GlobalPlugin(NVDA_GlobalPlugin):
    __gestures = {
        "kb:NVDA+control+shift+t": "toggleActive",
        "kb:NVDA+control+shift+l": "openSettingsDialog",
    }

    def __init__(self):
        super().__init__()
        self.active = False

        self.index = -1
        self._watcherThread = None
        self._settingsDialog = None
        self.speech_manager = announcer.SpeechReader()
        self.currentFileIndex = 0
        self.filePositions = {i: -1 for i in range(len(FILES))}
        settings.migrate_user_files()
        self.settings = settings.load_and_complete()
        self._sessionConnected = False

        store.set_folder(self.settings.text_files_destination)
        session.apply_settings(self.settings)

        if not self.settings.clear_on_start:
            self._load_positions_json()
            self.index = self.filePositions.get(self.currentFileIndex, -1)
            
        if self.settings.auto_speak_enabled:
             self.speech_manager.start()

    def _apply_settings(self, new):
        settings.save(new)
        self.settings = new
        session.apply_settings(new)

    def _load_positions_json(self):
        try:
            data = json.loads(settings.POSITIONS_PATH.read_text(encoding="utf-8"))
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
            settings.POSITIONS_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
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
        return _(name), store.path(filename)

    def _load_items(self):
        return store.read_entries(FILES[self.currentFileIndex][1])

    def _report_no_items(self):
        try:
            available = store.folder.is_dir()
        except Exception:
            available = False
        if available:
            ui.message(_("No entries"))
        else:
            # Translators: Announced when the folder holding the text files cannot be reached,
            # for example when it is on a removable drive that has been unplugged.
            ui.message(_("The text files folder is not available"))

    def _speak_current(self, items):
        if 0 <= self.index < len(items):
            if FILES[self.currentFileIndex][1] == "stats.txt":
                ui.message(items[self.index])
            else:
                num = self.index + 1
                total = len(items)
                # Translators: Announced when navigating list items. {item} is content, {num} is current position, {total} is total count.
                ui.message(_("{item} ({num} of {total})").format(item=items[self.index], num=num, total=total))
        else:
            ui.message(_("No entries"))


    def _connection_callbacks(self):
        def on_conn():
            self._ensure_temp_files_exist()
            self._sessionConnected = True
            # Translators: Announced when successfully connected to a TikTok live. {username} is the streamer's name.
            ui.message(_("Connected to user: {username}").format(username=self.settings.username))

        def on_retry():
            ui.message(_("Attempting to connect..."))

        def stop_session():
            self.active = False
            self._unbind_nav()
            session.disconnect()
            self.speech_manager.stop()

        def on_fail():
            ui.message(_("Connection unsuccessful."))
            stop_session()
            self._cleanup_temp_files()

        def on_live_end():
            # Translators: Announced when the streamer has ended the live.
            ui.message(_("The live has ended"))
            stop_session()
            self._archive_session(self.settings.username)
            self._cleanup_temp_files()

        return on_conn, on_retry, on_fail, on_live_end

    def _archive_session(self, username):
        if not self.settings.backup_sessions or not self._sessionConnected:
            return
        self._sessionConnected = False
        store.archive_session(username)

    @script(description=_("Toggle TikTok Live Reader on or off"), category="TikTok Live Reader")
    def script_toggleActive(self, gesture):
        if self._settingsDialog:
            return
            
        test_username = self.settings.username.strip().lstrip('@')
        if not self.active and len(test_username) < 2:
            ui.message(_("Please enter a valid username"))
            return
            
        self.active = not self.active
        if self.active:
            self._bind_nav()
            if not self.settings.clear_on_start:
                self._load_positions_json()
            self.index = self.filePositions.get(self.currentFileIndex, -1)
            if self.settings.auto_speak_enabled:
                self.speech_manager.start()
            else:
                self.speech_manager.stop()
            ui.message(_("TikTok Live Reader On"))

            on_conn, on_retry, on_fail, on_live_end = self._connection_callbacks()
            store.set_folder(self.settings.text_files_destination)
            session.connect(username=self.settings.username, on_connect=on_conn, on_retry=on_retry, on_fail=on_fail, on_live_end=on_live_end, retry_count=self.settings.retry_count)
        else:
            self._unbind_nav()
            ui.message(_("TikTok Live Reader Off"))
            session.disconnect()
            self.speech_manager.stop()
            self._archive_session(self.settings.username)
            self._cleanup_temp_files()

    def _cleanup_temp_files(self, hard_reset=False):
        try:
            announcer.remove_speech_buffer()
            
            if hard_reset:
                if settings.POSITIONS_PATH.exists():
                    settings.POSITIONS_PATH.unlink()
                if hasattr(self, 'filePositions'):
                    self.filePositions = {i: -1 for i in range(len(FILES))}
                    self.index = -1
            else:
                self._save_positions_json()
        except Exception:
            pass

    def _ensure_temp_files_exist(self):
        try:
            announcer.ensure_speech_buffer()
            if not settings.POSITIONS_PATH.exists():
                with open(settings.POSITIONS_PATH, "w", encoding="utf-8") as f:
                    json.dump({"version": 1, "files": {}}, f)
        except Exception:
            pass

    @script(description=_("Toggle automatic speaking of new events"), category="TikTok Live Reader")
    def script_toggleAutoSpeak(self, gesture):
        if not self.active:
            gesture.send()
            return
        self.settings.auto_speak_enabled = not self.settings.auto_speak_enabled
        self._apply_settings(self.settings)

        if self.settings.auto_speak_enabled:
            ui.message(_("Auto speak On"))
            self.speech_manager.start()
        else:
            ui.message(_("Auto speak Off"))
            self.speech_manager.stop()

    @script(
        description=_("Toggle sound playback for selected events"),
        category="TikTok Live Reader"
    )
    def script_togglePlaySounds(self, gesture):
        if not self.active:
            gesture.send()
            return

        self.settings.play_sounds = not self.settings.play_sounds
        self._apply_settings(self.settings)

        if self.settings.play_sounds:
            ui.message(_("Sounds On"))
        else:
            ui.message(_("Sounds Off"))

    @script(description=_("Open TikTok Live Reader settings"), category="TikTok Live Reader")
    def script_openSettingsDialog(self, gesture):
        if self._settingsDialog:
            self._settingsDialog.Raise()
            return
        wx.CallAfter(self._showSettingsDialog)

    def _showSettingsDialog(self):
        if self._settingsDialog:
            return
        was_active = self.active
        old_username = self.settings.username
        if was_active:
            self.speech_manager.stop()
            announcer.sound_manager.clear()
            announcer.set_settings_open(True)
            
        announcer.sound_manager.start()
            
        dlg = wx.Dialog(gui.mainFrame, title=_("TikTok Live Reader Settings"))
        self._settingsDialog = dlg
        nb = wx.Notebook(dlg)

        p_general = wx.Panel(nb)
        p_events = wx.Panel(nb)
        p_autospeak = wx.Panel(nb)
        p_sounds = wx.Panel(nb)

        s_general = wx.BoxSizer(wx.VERTICAL)
        
        lbl_user = wx.StaticText(p_general, label=_("&User name"))
        txt_user = wx.TextCtrl(p_general, value=self.settings.username)
        lbl_destination = wx.StaticText(p_general, label=_("Text files &destination"))
        destination_row = wx.FlexGridSizer(rows=1, cols=2, vgap=0, hgap=5)
        destination_row.AddGrowableCol(0, 1)
        self.settings.text_files_destination = str(store.usable_folder(self.settings.text_files_destination))
        txt_destination = wx.TextCtrl(
            p_general,
            value=self.settings.text_files_destination,
            size=(400, -1),
        )
        txt_destination.Bind(wx.EVT_CHAR, lambda evt: None)
        txt_destination.Bind(wx.EVT_TEXT_PASTE, lambda evt: None)
        btn_browse_destination = wx.Button(p_general, label=_("&Browse..."))
        destination_row.Add(txt_destination, flag=wx.EXPAND)
        destination_row.Add(btn_browse_destination, flag=wx.ALIGN_CENTER_VERTICAL)

        def on_browse_destination(evt):
            current_directory = txt_destination.GetValue()
            if not Path(current_directory).is_dir():
                current_directory = str(settings.DEFAULT_LOG_DIR)
            current_directory = settings.resolve_destination(current_directory)
            with wx.DirDialog(
                dlg,
                _("Select text files destination"),
                defaultPath=current_directory,
                style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST,
            ) as directory_dialog:
                if directory_dialog.ShowModal() == wx.ID_OK:
                    txt_destination.SetValue(directory_dialog.GetPath())
                    txt_destination.SetFocus()

        btn_browse_destination.Bind(wx.EVT_BUTTON, on_browse_destination)
        chk_clear = wx.CheckBox(p_general, label=_("&Clear text files on startup"))
        chk_strip = wx.CheckBox(p_general, label=_("Cl&ean user names"))
        chk_backup = wx.CheckBox(p_general, label=_("&Archive each live session"))

        chk_clear.SetValue(self.settings.clear_on_start)
        chk_strip.SetValue(self.settings.clean_usernames)
        chk_backup.SetValue(self.settings.backup_sessions)

        lbl_retry = wx.StaticText(p_general, label=_("Connection &retry count"))
        spin_retry = wx.SpinCtrl(p_general, value=str(self.settings.retry_count), min=1, max=10)
        
        s_general.Add(lbl_user, flag=wx.ALL, border=5)
        s_general.Add(txt_user, flag=wx.EXPAND | wx.ALL, border=5)
        s_general.Add(lbl_destination, flag=wx.LEFT | wx.RIGHT | wx.TOP, border=5)
        s_general.Add(destination_row, flag=wx.EXPAND | wx.ALL, border=5)
        s_general.Add(chk_clear, flag=wx.ALL, border=5)
        s_general.Add(chk_strip, flag=wx.ALL, border=5)
        s_general.Add(chk_backup, flag=wx.ALL, border=5)
        s_general.Add(lbl_retry, flag=wx.ALL, border=5)
        s_general.Add(spin_retry, flag=wx.ALL, border=5)
        p_general.SetSizer(s_general)

        s_events = wx.BoxSizer(wx.VERTICAL)
        event_checks = _add_event_checkboxes(p_events, s_events, self.settings.events)
        p_events.SetSizer(s_events)

        s_sounds = wx.BoxSizer(wx.VERTICAL)
        chk_play_sounds = wx.CheckBox(p_sounds, label=_("&Play sounds for the selected events"))
        chk_play_sounds.SetValue(self.settings.play_sounds)
        s_sounds.Add(chk_play_sounds, flag=wx.ALL, border=5)

        sl_s1 = wx.StaticLine(p_sounds)
        s_sounds.Add(sl_s1, flag=wx.EXPAND|wx.ALL, border=5)

        sound_checks = _add_event_checkboxes(p_sounds, s_sounds, self.settings.sounds)
        sound_sub_chks = list(sound_checks.values())

        sl_s2 = wx.StaticLine(p_sounds)
        s_sounds.Add(sl_s2, flag=wx.EXPAND|wx.ALL, border=5)

        lbl_volume = wx.StaticText(p_sounds, label=_("V&olume"))
        slider_volume = wx.Slider(p_sounds, value=self.settings.volume, minValue=0, maxValue=100, style=wx.SL_HORIZONTAL, name=_("V&olume"))
        s_sounds.Add(lbl_volume, flag=wx.ALL, border=5)
        s_sounds.Add(slider_volume, flag=wx.EXPAND | wx.ALL, border=5)

        btn_learn = wx.Button(p_sounds, label=_("L&earn sounds"))
        
        self._learning_thread = None
        self._stop_learning = threading.Event()

        s_sounds.Add(btn_learn, flag=wx.ALL, border=5)

        def on_toggle_sounds(evt):
            is_checked = chk_play_sounds.IsChecked()
            sl_s1.Show(is_checked)
            for chk in sound_sub_chks:
                chk.Show(is_checked)
            sl_s2.Show(is_checked)
            lbl_volume.Show(is_checked)
            slider_volume.Show(is_checked)
            btn_learn.Show(is_checked)
            p_sounds.Layout()
            if not is_checked and self._learning_thread and self._learning_thread.is_alive():
                self._stop_learning.set()
                btn_learn.SetLabel(_("L&earn sounds"))
            
        def on_volume_change(evt):
            vol = slider_volume.GetValue()
            announcer.sound_manager.set_volume(vol)
            
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
                      for _wait_step in range(20):
                          if self._stop_learning.is_set():
                              return
                          time.sleep(0.1)
                          
                      sequence = [
                          (_("Comment"), "comments"),
                          (_("Follower"), "followers"),
                          (_("Gift"), "gifts"),
                          (_("Like"), "likes"),
                          (_("Guest request"), "requests"),
                          (_("Sharing"), "shares"),
                          (_("Visitor"), "visitors"),
                      ]
                      
                      announcer.sound_manager.set_volume(vol)
                      
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
                          announcer.sound_manager.play(event_key, play_file=True, post_delay=0.0, on_complete=lambda d=done: d.set())
                          
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
        p_sounds.SetSizer(s_sounds)

        s_autospeak = wx.BoxSizer(wx.VERTICAL)
        chk_auto_speak = wx.CheckBox(p_autospeak, label=_("&Auto speak selected events"))
        chk_auto_speak.SetValue(self.settings.auto_speak_enabled)
        s_autospeak.Add(chk_auto_speak, flag=wx.ALL, border=5)
        
        sl_as1 = wx.StaticLine(p_autospeak)
        s_autospeak.Add(sl_as1, flag=wx.EXPAND|wx.ALL, border=5)

        auto_speak_checks = _add_event_checkboxes(p_autospeak, s_autospeak, self.settings.auto_speak)
        sub_chks = list(auto_speak_checks.values())

        sl_as2 = wx.StaticLine(p_autospeak)
        s_autospeak.Add(sl_as2, flag=wx.EXPAND|wx.ALL, border=5)

        def on_toggle_auto_speak(evt):
            is_checked = chk_auto_speak.IsChecked()
            sl_as1.Show(is_checked)
            for chk in sub_chks:
                chk.Show(is_checked)
            sl_as2.Show(is_checked)
            p_autospeak.Layout()

        chk_auto_speak.Bind(wx.EVT_CHECKBOX, on_toggle_auto_speak)
        on_toggle_auto_speak(None)
        
        p_autospeak.SetSizer(s_autospeak)

        nb.AddPage(p_general, _("General"))
        nb.AddPage(p_events, _("Events"))
        nb.AddPage(p_autospeak, _("Auto speak"))
        nb.AddPage(p_sounds, _("Sounds"))

        topsizer = wx.BoxSizer(wx.VERTICAL)
        topsizer.Add(nb, 1, wx.EXPAND | wx.ALL, 5)
        btn_sizer = wx.StdDialogButtonSizer()
        btn_ok = wx.Button(dlg, wx.ID_OK, _("OK"))
        
        def on_ok(evt):
            val = txt_user.GetValue().strip().lstrip('@')
            if len(val) < 2 or not re.match(r'^[a-zA-Z0-9_\.\-]+$', val):
                ui.message(_("Please enter a valid username"))
                txt_user.SetFocus()
                return
            evt.Skip()
            
        btn_ok.Bind(wx.EVT_BUTTON, on_ok)
        
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

        res = dlg.ShowModal()
        
        if hasattr(self, "_stop_learning"):
            self._stop_learning.set()
            
        if was_active:
            announcer.set_settings_open(False)
            
        if res == wx.ID_OK:
            self._apply_settings(settings.Settings(
                username=txt_user.GetValue().strip().lstrip('@'),
                text_files_destination=txt_destination.GetValue(),
                events={k: chk.IsChecked() for k, chk in event_checks.items()},
                auto_speak={k: chk.IsChecked() for k, chk in auto_speak_checks.items()},
                sounds={k: chk.IsChecked() for k, chk in sound_checks.items()},
                auto_speak_enabled=chk_auto_speak.IsChecked(),
                clear_on_start=chk_clear.IsChecked(),
                clean_usernames=chk_strip.IsChecked(),
                retry_count=spin_retry.GetValue(),
                backup_sessions=chk_backup.IsChecked(),
                play_sounds=chk_play_sounds.IsChecked(),
                volume=slider_volume.GetValue(),
            ))
            
            new_username = txt_user.GetValue().strip().lstrip('@')
            
            if was_active:
                if new_username != old_username:
                    self.active = False
                    self._unbind_nav()
                    session.disconnect()
                    self._archive_session(old_username)
                    self._cleanup_temp_files(hard_reset=True)
                    
                    self.active = True
                    announcer.sound_manager.clear()
                    self._bind_nav()
                    if not self.settings.clear_on_start:
                        self._load_positions_json()
                    self.index = self.filePositions.get(self.currentFileIndex, -1)
                    if self.settings.auto_speak_enabled:
                        self.speech_manager.start()
                        
                    on_conn, on_retry, on_fail, on_live_end = self._connection_callbacks()
                    store.set_folder(self.settings.text_files_destination)
                    session.connect(username=self.settings.username, on_connect=on_conn, on_retry=on_retry, on_fail=on_fail, on_live_end=on_live_end, retry_count=self.settings.retry_count)
                else:
                    if self.settings.auto_speak_enabled:
                        self.speech_manager.start()
        else:
            if was_active and self.settings.auto_speak_enabled:
                self.speech_manager.start()
                
        dlg.Destroy()
        self._settingsDialog = None

    def _persist_index(self):
        if not self.settings.clear_on_start:
            self.filePositions[self.currentFileIndex] = self.index
            self._save_positions_json()

    @script(description=_("Next item"))
    def script_nextItem(self, gesture):
        if not self.active:
            return
        items = self._load_items()
        if not items:
            self._report_no_items()
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
            self._report_no_items()
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
            self._report_no_items()
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
            self._report_no_items()
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

    @script(description=_("Clear all log files and reset positions"), category=_("TikTok Live Reader"))
    def script_clearTextFiles(self, gesture):
        if not self.active:
            return

        # Translators: Confirmation shown before clearing the contents of all text files.
        yes_button = message.DefaultButton.YES.value._replace(
            callback=self._clear_text_files_after_confirmation,
        )
        no_button = message.DefaultButton.NO.value._replace(
            defaultFocus=True,
            fallbackAction=True,
        )
        dialog = message.MessageDialog(
            gui.mainFrame,
            _("Are you sure you want to delete the contents of all text files?"),
            _("TikTok Live Reader"),
            message.DialogType.WARNING,
            buttons=(yes_button, no_button),
        )
        dialog.Show()

    def _clear_text_files_after_confirmation(self, payload=None):
        if not self.active:
            return

        self._cleanup_temp_files(hard_reset=True)
        announcer.sound_manager.clear()
        store.clear_all()
        
        try:
            settings.POSITIONS_PATH.write_text(json.dumps({"version": 1, "files": {}}, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
            
        pipeline.reset_accumulators()
        ui.message(_("All files cleared."))

    @script(description=_("Report the current number of live viewers"), category=_("TikTok Live Reader"))
    def script_reportViewers(self, gesture):
        if not self.active:
            ui.message(_("Addon is not active."))
            return
        count = pipeline.viewer_count
        # Translators: Announced when reporting live viewer count. {count} is the number of viewers.
        ui.message(_("{count} viewers").format(count=count))

    def terminate(self):
        try:
            session.disconnect()
            if hasattr(self, "speech_manager"):
                self.speech_manager.stop()
            self._archive_session(self.settings.username)
        except Exception:
            pass
        return super().terminate()
