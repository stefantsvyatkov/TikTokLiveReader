"""Likes come in bursts; each person's are summed until they pause."""

import threading

PAUSE = 10.0


class LikeAggregator:
	"""Reports ``report(user, count)`` once a person has not liked for ``PAUSE``
	seconds, with the likes since their last report. ``add`` takes the person's
	running total."""

	def __init__(self, report):
		self._report = report
		self._timers = {}
		self._baselines = {}
		self._current_totals = {}
		self._lock = threading.Lock()

	def add(self, user, total):
		with self._lock:
			if user in self._timers:
				self._timers[user].cancel()
			if user not in self._baselines:
				self._baselines[user] = self._current_totals.get(user, 0)
			self._current_totals[user] = total
			timer = threading.Timer(PAUSE, self._flush, args=[user])
			timer.daemon = True
			self._timers[user] = timer
			timer.start()

	def _flush(self, user):
		with self._lock:
			self._timers.pop(user, None)
			count = self._current_totals.get(user, 0) - self._baselines.pop(user, 0)
		if count > 0:
			self._report(user, count)

	def flush_pending(self):
		"""Report every pending sum now instead of after the pause."""
		for user in list(self._timers):
			timer = self._timers.get(user)
			if timer:
				timer.cancel()
			self._flush(user)

	def stop(self):
		"""Forget everything, pending sums included."""
		with self._lock:
			for timer in self._timers.values():
				timer.cancel()
			self._timers.clear()
			self._baselines.clear()
			self._current_totals.clear()
