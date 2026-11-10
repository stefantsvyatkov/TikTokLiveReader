"""Likes come in bursts; each person's are summed until they pause."""

import threading
import time

PAUSE = 10.0
# A timer firing this early still counts as on time.
_EARLY = 0.001


class LikeAggregator:
	"""Reports ``report(user, count)`` once a person has not liked for ``PAUSE``
	seconds, with the likes since their last report. ``add`` takes the person's
	running total.

	One timer serves everyone, set for the earliest pause to end: a busy live
	brings several like messages a second, and a timer each (a thread each) made
	each like cost milliseconds and left a thread waiting per person."""

	def __init__(self, report):
		self._report = report
		self._deadlines = {}
		self._baselines = {}
		self._current_totals = {}
		self._timer = None
		self._token = None
		self._lock = threading.Lock()

	def add(self, user, total):
		with self._lock:
			if user not in self._baselines:
				self._baselines[user] = self._current_totals.get(user, 0)
			self._current_totals[user] = total
			# Moved to the end: the dict stays in deadline order.
			self._deadlines.pop(user, None)
			self._deadlines[user] = time.time() + PAUSE
			if self._timer is None:
				self._arm()

	def _arm(self):
		"""Set the timer for the earliest deadline; with ``_lock`` held."""
		if not self._deadlines:
			self._timer = None
			return
		first = next(iter(self._deadlines.values()))
		token = self._token = object()
		self._timer = threading.Timer(max(0.0, first - time.time()), self._fire, args=[token])
		self._timer.daemon = True
		self._timer.start()

	def _fire(self, token):
		with self._lock:
			# A timer cancelled while it was already firing.
			if self._timer is None or self._token is not token:
				return
			now = time.time() + _EARLY
			due = []
			for user, deadline in self._deadlines.items():
				if deadline > now:
					break
				due.append(user)
			counts = [(user, self._take(user)) for user in due]
			self._arm()
		for user, count in counts:
			if count > 0:
				self._report(user, count)

	def _take(self, user):
		"""The person's likes since their last report; with ``_lock`` held."""
		self._deadlines.pop(user, None)
		return self._current_totals.get(user, 0) - self._baselines.pop(user, 0)

	def flush_pending(self):
		"""Report every pending sum now instead of after the pause."""
		with self._lock:
			if self._timer is not None:
				self._timer.cancel()
				self._timer = None
			counts = [(user, self._take(user)) for user in list(self._deadlines)]
		for user, count in counts:
			if count > 0:
				self._report(user, count)

	def stop(self):
		"""Forget everything, pending sums included."""
		with self._lock:
			if self._timer is not None:
				self._timer.cancel()
				self._timer = None
			self._deadlines.clear()
			self._baselines.clear()
			self._current_totals.clear()
