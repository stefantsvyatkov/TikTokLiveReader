from . import announcer, dialogs, pipeline, positions, session, settings, store
from .i18n import _
from globalPluginHandler import GlobalPlugin as NVDA_GlobalPlugin
from scriptHandler import script
import gui
from gui import message
import ui
import wx
from logHandler import log


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
	# One category in Input gestures for every script (1.8 mixed three ways, F24).
	scriptCategory = _("TikTok Live Reader")

	__gestures = {
		"kb:NVDA+control+shift+t": "toggleActive",
		"kb:NVDA+control+shift+l": "openSettingsDialog",
	}

	def __init__(self):
		super().__init__()
		self.active = False

		self.index = -1
		self._settingsDialog = None
		self._connectionToken = None
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
		lines = positions.read()
		for i in range(len(FILES)):
			k = INDEX_TO_KEY[i]
			if k in TRACKED_KEYS:
				self.filePositions[i] = int(lines.get(k, {}).get("line", -1))

	def _save_positions_json(self):
		positions.write(
			{
				INDEX_TO_KEY[i]: self.filePositions.get(i, -1)
				for i in range(len(FILES))
				if INDEX_TO_KEY[i] in TRACKED_KEYS
			}
		)

	def _follow_auto_speak(self):
		"""Read new events aloud exactly while auto speak is on."""
		if self.settings.auto_speak_enabled:
			self.speech_manager.start()
		else:
			self.speech_manager.stop()

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
				ui.message(
					# Translators: Announced when navigating list items. {item} is content, {num} is current position, {total} is total count.
					_("{item} ({num} of {total})").format(item=items[self.index], num=num, total=total)
				)
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
			self._connectionToken = None
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

		token = self._connectionToken = object()

		def on_main_thread(callback):
			# The connection thread reports; NVDA's speech and gestures belong to
			# the main thread (F3). A report of a session switched off since is dropped.
			def run():
				if self._connectionToken is token:
					callback()

			return lambda: wx.CallAfter(run)

		return tuple(on_main_thread(callback) for callback in (on_conn, on_retry, on_fail, on_live_end))

	def _archive_session(self, username):
		if not self.settings.backup_sessions or not self._sessionConnected:
			return
		self._sessionConnected = False
		store.archive_session(username)

	@script(description=_("Toggle TikTok Live Reader on or off"))
	def script_toggleActive(self, gesture):
		if self._settingsDialog:
			return

		test_username = self.settings.username.strip().lstrip("@")
		if not self.active and len(test_username) < 2:
			ui.message(_("Please enter a valid username"))
			return

		self.active = not self.active
		if self.active:
			self._bind_nav()
			if not self.settings.clear_on_start:
				self._load_positions_json()
			self.index = self.filePositions.get(self.currentFileIndex, -1)
			self._follow_auto_speak()
			ui.message(_("TikTok Live Reader On"))

			on_conn, on_retry, on_fail, on_live_end = self._connection_callbacks()
			store.set_folder(self.settings.text_files_destination)
			session.connect(
				username=self.settings.username,
				on_connect=on_conn,
				on_retry=on_retry,
				on_fail=on_fail,
				on_live_end=on_live_end,
				retry_count=self.settings.retry_count,
			)
		else:
			self._connectionToken = None
			self._unbind_nav()
			ui.message(_("TikTok Live Reader Off"))
			session.disconnect()
			self.speech_manager.stop()
			self._archive_session(self.settings.username)
			self._cleanup_temp_files()

	def _cleanup_temp_files(self, hard_reset=False):
		try:
			announcer.forget_pending_speech()

			if hard_reset:
				positions.remove()
				if hasattr(self, "filePositions"):
					self.filePositions = {i: -1 for i in range(len(FILES))}
					self.index = -1
			else:
				self._save_positions_json()
		except Exception:
			log.debugWarning("TikTok Live Reader: cleaning up after a session", exc_info=True)

	def _ensure_temp_files_exist(self):
		try:
			positions.create_if_missing()
		except Exception:
			log.debugWarning("TikTok Live Reader: creating the positions file", exc_info=True)

	@script(description=_("Toggle automatic speaking of new events"))
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

	@script(description=_("Toggle sound playback for selected events"))
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

	@script(description=_("Open TikTok Live Reader settings"))
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
		self.settings.text_files_destination = str(store.usable_folder(self.settings.text_files_destination))
		# NVDA's way to show a dialog: its main frame takes the foreground first, so
		# the dialog does not open behind the focused window (F35).
		gui.mainFrame.prePopup()
		try:
			dlg = dialogs.SettingsDialog(gui.mainFrame, self.settings)
			self._settingsDialog = dlg
			res = dlg.ShowModal()
		finally:
			gui.mainFrame.postPopup()
		dlg.stop_learning()

		if was_active:
			announcer.set_settings_open(False)

		if res == wx.ID_OK:
			self._apply_settings(dlg.chosen_settings())
			new_username = self.settings.username

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
					session.connect(
						username=self.settings.username,
						on_connect=on_conn,
						on_retry=on_retry,
						on_fail=on_fail,
						on_live_end=on_live_end,
						retry_count=self.settings.retry_count,
					)
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

	@script(description=_("Clear all log files and reset positions"))
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
		positions.reset()

		pipeline.reset_accumulators()
		ui.message(_("All files cleared."))

	@script(description=_("Report the current number of live viewers"))
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
			log.exception("TikTok Live Reader: closing")
		return super().terminate()
