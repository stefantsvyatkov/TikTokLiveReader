"""The settings dialog. The order controls are created in is the Tab order."""

import re
import threading
import time
from pathlib import Path

import ui
import wx

from . import announcer, settings
from .i18n import _

USER_NAME = re.compile(r"^[a-zA-Z0-9_\.\-]+$")


def clean_user_name(text):
	return text.strip().lstrip("@")


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
		check = wx.CheckBox(parent, label=label)
		check.SetValue(bool(values.get(key, settings.DEFAULT_EVENT_PREFS[key])))
		sizer.Add(check, flag=wx.ALL, border=5)
		checks[key] = check
	return checks


class SettingsDialog(wx.Dialog):
	def __init__(self, parent, current):
		super().__init__(parent, title=_("TikTok Live Reader Settings"))
		self._learning_thread = None
		self._stop_learning = threading.Event()
		notebook = wx.Notebook(self)
		general = wx.Panel(notebook)
		events = wx.Panel(notebook)
		auto_speak = wx.Panel(notebook)
		sounds = wx.Panel(notebook)

		self._build_general(general, current)
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.event_checks = _add_event_checkboxes(events, sizer, current.events)
		events.SetSizer(sizer)
		self._build_sounds(sounds, current)
		self._build_auto_speak(auto_speak, current)

		notebook.AddPage(general, _("General"))
		notebook.AddPage(events, _("Events"))
		notebook.AddPage(auto_speak, _("Auto speak"))
		notebook.AddPage(sounds, _("Sounds"))

		top = wx.BoxSizer(wx.VERTICAL)
		top.Add(notebook, 1, wx.EXPAND | wx.ALL, 5)
		buttons = wx.StdDialogButtonSizer()
		ok = wx.Button(self, wx.ID_OK, _("OK"))
		ok.Bind(wx.EVT_BUTTON, self._on_ok)
		cancel = wx.Button(self, wx.ID_CANCEL, _("Cancel"))
		ok.SetDefault()
		buttons.AddButton(ok)
		buttons.AddButton(cancel)
		buttons.Realize()
		top.Add(buttons, 0, wx.EXPAND | wx.ALL, 5)
		self.SetSizerAndFit(top)
		self.CentreOnScreen()
		self.Raise()
		self.user.SetFocus()
		self.user.SetInsertionPointEnd()

	def _build_general(self, panel, current):
		sizer = wx.BoxSizer(wx.VERTICAL)
		user_label = wx.StaticText(panel, label=_("&User name"))
		self.user = wx.TextCtrl(panel, value=current.username)
		destination_label = wx.StaticText(panel, label=_("Text files &destination"))
		destination_row = wx.FlexGridSizer(rows=1, cols=2, vgap=0, hgap=5)
		destination_row.AddGrowableCol(0, 1)
		# Read-only by swallowing typing and pasting: the folder is chosen with Browse.
		self.destination = wx.TextCtrl(panel, value=current.text_files_destination, size=(400, -1))
		self.destination.Bind(wx.EVT_CHAR, lambda evt: None)
		self.destination.Bind(wx.EVT_TEXT_PASTE, lambda evt: None)
		browse = wx.Button(panel, label=_("&Browse..."))
		destination_row.Add(self.destination, flag=wx.EXPAND)
		destination_row.Add(browse, flag=wx.ALIGN_CENTER_VERTICAL)
		browse.Bind(wx.EVT_BUTTON, self._on_browse)

		self.clear_on_start = wx.CheckBox(panel, label=_("&Clear text files on startup"))
		self.clean_usernames = wx.CheckBox(panel, label=_("Cl&ean user names"))
		self.backup_sessions = wx.CheckBox(panel, label=_("&Archive each live session"))
		self.clear_on_start.SetValue(current.clear_on_start)
		self.clean_usernames.SetValue(current.clean_usernames)
		self.backup_sessions.SetValue(current.backup_sessions)
		retry_label = wx.StaticText(panel, label=_("Connection &retry count"))
		self.retry_count = wx.SpinCtrl(panel, value=str(current.retry_count), min=1, max=10)

		sizer.Add(user_label, flag=wx.ALL, border=5)
		sizer.Add(self.user, flag=wx.EXPAND | wx.ALL, border=5)
		sizer.Add(destination_label, flag=wx.LEFT | wx.RIGHT | wx.TOP, border=5)
		sizer.Add(destination_row, flag=wx.EXPAND | wx.ALL, border=5)
		sizer.Add(self.clear_on_start, flag=wx.ALL, border=5)
		sizer.Add(self.clean_usernames, flag=wx.ALL, border=5)
		sizer.Add(self.backup_sessions, flag=wx.ALL, border=5)
		sizer.Add(retry_label, flag=wx.ALL, border=5)
		sizer.Add(self.retry_count, flag=wx.ALL, border=5)
		panel.SetSizer(sizer)

	def _build_sounds(self, panel, current):
		self._sounds_panel = panel
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.play_sounds = wx.CheckBox(panel, label=_("&Play sounds for the selected events"))
		self.play_sounds.SetValue(current.play_sounds)
		sizer.Add(self.play_sounds, flag=wx.ALL, border=5)
		first_line = wx.StaticLine(panel)
		sizer.Add(first_line, flag=wx.EXPAND | wx.ALL, border=5)
		self.sound_checks = _add_event_checkboxes(panel, sizer, current.sounds)
		second_line = wx.StaticLine(panel)
		sizer.Add(second_line, flag=wx.EXPAND | wx.ALL, border=5)
		volume_label = wx.StaticText(panel, label=_("V&olume"))
		self.volume = wx.Slider(
			panel,
			value=current.volume,
			minValue=0,
			maxValue=100,
			style=wx.SL_HORIZONTAL,
			name=_("V&olume"),
		)
		sizer.Add(volume_label, flag=wx.ALL, border=5)
		sizer.Add(self.volume, flag=wx.EXPAND | wx.ALL, border=5)
		self.learn = wx.Button(panel, label=_("L&earn sounds"))
		sizer.Add(self.learn, flag=wx.ALL, border=5)
		# Shown only while sounds are on.
		self._sound_controls = [
			first_line,
			*self.sound_checks.values(),
			second_line,
			volume_label,
			self.volume,
			self.learn,
		]

		self.play_sounds.Bind(wx.EVT_CHECKBOX, self._on_toggle_sounds)
		self.volume.Bind(
			wx.EVT_SLIDER, lambda evt: announcer.sound_manager.set_volume(self.volume.GetValue())
		)
		self._on_toggle_sounds(None)
		self.learn.Bind(wx.EVT_BUTTON, self._on_learn)
		panel.SetSizer(sizer)

	def _build_auto_speak(self, panel, current):
		self._auto_speak_panel = panel
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.auto_speak = wx.CheckBox(panel, label=_("&Auto speak selected events"))
		self.auto_speak.SetValue(current.auto_speak_enabled)
		sizer.Add(self.auto_speak, flag=wx.ALL, border=5)
		first_line = wx.StaticLine(panel)
		sizer.Add(first_line, flag=wx.EXPAND | wx.ALL, border=5)
		self.auto_speak_checks = _add_event_checkboxes(panel, sizer, current.auto_speak)
		second_line = wx.StaticLine(panel)
		sizer.Add(second_line, flag=wx.EXPAND | wx.ALL, border=5)
		# Shown only while auto speak is on.
		self._auto_speak_controls = [first_line, *self.auto_speak_checks.values(), second_line]

		self.auto_speak.Bind(wx.EVT_CHECKBOX, self._on_toggle_auto_speak)
		self._on_toggle_auto_speak(None)
		panel.SetSizer(sizer)

	def _on_browse(self, evt):
		folder = self.destination.GetValue()
		if not Path(folder).is_dir():
			folder = str(settings.DEFAULT_LOG_DIR)
		folder = settings.resolve_destination(folder)
		with wx.DirDialog(
			self,
			_("Select text files destination"),
			defaultPath=folder,
			style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST,
		) as chooser:
			if chooser.ShowModal() == wx.ID_OK:
				self.destination.SetValue(chooser.GetPath())
				self.destination.SetFocus()

	def _on_toggle_sounds(self, evt):
		shown = self.play_sounds.IsChecked()
		for control in self._sound_controls:
			control.Show(shown)
		self._sounds_panel.Layout()
		if not shown and self._learning_thread and self._learning_thread.is_alive():
			self._stop_learning.set()
			self.learn.SetLabel(_("L&earn sounds"))

	def _on_toggle_auto_speak(self, evt):
		shown = self.auto_speak.IsChecked()
		for control in self._auto_speak_controls:
			control.Show(shown)
		self._auto_speak_panel.Layout()

	def _on_learn(self, evt):
		if self._learning_thread and self._learning_thread.is_alive():
			self._stop_learning.set()
			self.learn.SetLabel(_("L&earn sounds"))
			return
		self._stop_learning.clear()
		self.learn.SetLabel(_("St&op"))
		try:
			volume = self.volume.GetValue()
		except Exception:
			volume = 100
		self._learning_thread = threading.Thread(target=self._play_each_sound, args=(volume,), daemon=True)
		self._learning_thread.start()

	def _wait(self, seconds):
		"""Sleep in short steps; False when learning was stopped meanwhile."""
		for _step in range(round(seconds / 0.1)):
			if self._stop_learning.is_set():
				return False
			time.sleep(0.1)
		return not self._stop_learning.is_set()

	def _play_each_sound(self, volume):
		"""Name each event, then play its sound, until the end or Stop."""
		try:
			if not self._wait(2.0):
				return
			sequence = (
				(_("Comment"), "comments"),
				(_("Follower"), "followers"),
				(_("Gift"), "gifts"),
				(_("Like"), "likes"),
				(_("Guest request"), "requests"),
				(_("Sharing"), "shares"),
				(_("Visitor"), "visitors"),
			)
			announcer.sound_manager.set_volume(volume)
			for label, event_key in sequence:
				if self._stop_learning.is_set():
					break
				wx.CallAfter(ui.message, label)
				if not self._wait(1.0):
					break
				played = threading.Event()
				announcer.sound_manager.play(
					event_key, play_file=True, post_delay=0.0, on_complete=played.set
				)
				started = time.time()
				while (
					not played.is_set() and not self._stop_learning.is_set() and time.time() - started <= 5.0
				):
					time.sleep(0.1)
				if self._stop_learning.is_set():
					break
				time.sleep(0.5)
		except Exception:
			pass
		finally:
			wx.CallAfter(self.learn.SetLabel, _("L&earn sounds"))

	def stop_learning(self):
		self._stop_learning.set()

	def _on_ok(self, evt):
		name = clean_user_name(self.user.GetValue())
		if len(name) < 2 or not USER_NAME.match(name):
			ui.message(_("Please enter a valid username"))
			self.user.SetFocus()
			return
		evt.Skip()

	def chosen_settings(self):
		return settings.Settings(
			username=clean_user_name(self.user.GetValue()),
			text_files_destination=self.destination.GetValue(),
			events={key: check.IsChecked() for key, check in self.event_checks.items()},
			auto_speak={key: check.IsChecked() for key, check in self.auto_speak_checks.items()},
			sounds={key: check.IsChecked() for key, check in self.sound_checks.items()},
			auto_speak_enabled=self.auto_speak.IsChecked(),
			clear_on_start=self.clear_on_start.IsChecked(),
			clean_usernames=self.clean_usernames.IsChecked(),
			retry_count=self.retry_count.GetValue(),
			backup_sessions=self.backup_sessions.IsChecked(),
			play_sounds=self.play_sounds.IsChecked(),
			volume=self.volume.GetValue(),
		)
